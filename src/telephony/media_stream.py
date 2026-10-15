import asyncio
import base64
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import settings
from ..core.models import CallRecord
from ..nlp import generate_reply_async, transcribe_audio_async
from ..core.tts_engine import synthesize_tts_async
from ..core import scam_database

MEDIA_SILENCE_THRESHOLD = 0.01
MIN_SPEECH_DURATION = 1.5  # seconds before we transcribe
MAX_CONVERSATION_HISTORY = 20


@dataclass
class StreamSession:
    call_sid: str
    stream_sid: str
    from_number: str
    to_number: str
    audio_buffer: bytes = field(default=b"")
    audio_chunks: deque = field(default_factory=deque)
    sample_rate: int = 8000
    is_processing: bool = False
    transcript_so_far: str = ""
    conversation_history: list = field(default_factory=list)
    response_queue: list = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def reset_audio(self):
        self.audio_buffer = b""
        self.audio_chunks.clear()

    def get_audio_file(self, prefix: str = "chunk") -> str:
        import time
        ts = int(time.time() * 1000)
        filename = f"{prefix}_{ts}.wav"
        filepath = Path(settings.RECORDING_DIR) / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        return str(filepath)

    def save_audio_to_wav(self, raw_audio: bytes, sample_rate: int = 8000) -> str:
        filepath = self.get_audio_file("stream")
        _pcm_to_wav(raw_audio, filepath, sample_rate=sample_rate)
        return filepath


def _pcm_to_wav(pcm_data: bytes, output_path: str, sample_rate: int = 8000,
                channels: int = 1, sample_width: int = 2):
    num_frames = len(pcm_data) // (channels * sample_width)
    with open(output_path, "wb") as f:
        import wave
        with wave.open(output_path, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_data)


_sessions: dict[str, StreamSession] = {}


def get_session(stream_sid: str) -> Optional[StreamSession]:
    return _sessions.get(stream_sid)


def create_session(call_sid: str, stream_sid: str, from_number: str, to_number: str) -> StreamSession:
    session = StreamSession(
        call_sid=call_sid,
        stream_sid=stream_sid,
        from_number=from_number,
        to_number=to_number,
    )
    _sessions[stream_sid] = session
    return session


def end_session(stream_sid: str):
    _sessions.pop(stream_sid, None)


async def handle_media_chunk(session: StreamSession, audio_data: bytes):
    session.audio_chunks.append(audio_data)
    session.audio_buffer += audio_data

    if len(session.audio_buffer) < session.sample_rate * 2 * MIN_SPEECH_DURATION:
        return

    if session.is_processing:
        return

    session.is_processing = True
    await process_audio_chunk(session)


async def process_audio_chunk(session: StreamSession):
    if len(session.audio_buffer) < session.sample_rate * 2:
        session.is_processing = False
        return

    audio_file = session.save_audio_to_wav(session.audio_buffer, session.sample_rate)
    session.reset_audio()

    try:
        transcription = await transcribe_audio_async(audio_file)
        transcription = transcription.strip()
        if not transcription:
            return

        session.transcript_so_far += f"\nScammer: {transcription}"
        print(f"[STREAM] {session.from_number}: {transcription}")

        from ..core.database import SessionLocal
        from ..core.models import CallRecord
        db = SessionLocal()
        try:
            record = db.query(CallRecord).filter_by(call_sid=session.call_sid).first()
            is_scam, confidence, scam_type, _ = scam_database.detect_scam(
                db, session.from_number, transcription
            )
            if is_scam:
                if record:
                    record.scam_detected = True
                    record.scam_confidence = max(
                        record.scam_confidence or 0, confidence
                    )
            if record and record.transcript:
                record.transcript = (record.transcript or "") + f"\nScammer: {transcription}\n"
            elif record:
                record.transcript = f"Scammer: {transcription}\n"
            db.commit()

            db_match = scam_database.check_number_in_db(db, session.from_number)
            if db_match:
                session.conversation_history.append(
                    {"role": "assistant", "content": transcription}
                )
            else:
                await _generate_and_queue_response(session, transcription, db_match)
        finally:
            db.close()

    except Exception as e:
        print(f"[STREAM] Error processing audio: {e}")
    finally:
        session.is_processing = False


async def _generate_and_queue_response(session: StreamSession, transcription: str,
                                        scam_db_entry=None):
    try:
        db_match = scam_db_entry or await _check_db_async(session.from_number)
        persona = settings.DEFAULT_PERSONA
        reply_text = await generate_reply_async(transcription, persona, session.conversation_history)

        session.conversation_history.extend([
            {"role": "assistant", "content": transcription},
            {"role": "user", "content": reply_text},
        ])
        session.conversation_history = session.conversation_history[-MAX_CONVERSATION_HISTORY:]

        session.transcript_so_far += f"\nAI ({persona}): {reply_text}"

        output_file = session.get_audio_file("reply")
        await synthesize_tts_async(reply_text, output_file)
        session.response_queue.append(output_file)
        print(f"[STREAM] AI reply: {reply_text}")

    except Exception as e:
        print(f"[STREAM] Error generating reply: {e}")


async def _check_db_async(phone_number: str):
    from ..core.database import SessionLocal
    loop = asyncio.get_event_loop()
    db = SessionLocal()
    try:
        return await loop.run_in_executor(
            None, scam_database.check_number_in_db, db, phone_number
        )
    finally:
        db.close()


async def drain_response_queue(session: StreamSession) -> Optional[str]:
    if session.response_queue:
        return session.response_queue.pop(0)
    return None


def save_session_transcript(session: StreamSession):
    from ..core.database import SessionLocal
    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=session.call_sid).first()
        if record:
            if session.transcript_so_far:
                record.transcript = session.transcript_so_far
            if session.response_queue:
                record.metadata_json = record.metadata_json or {}
                record.metadata_json["tts_files"] = len(session.response_queue)
            db.commit()
    finally:
        db.close()
