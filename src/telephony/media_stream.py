import asyncio
import base64
import json
import logging
import os
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import audioop

from ..config import settings
from ..core.models import CallRecord
from ..nlp import generate_reply_async, transcribe_audio_async
from ..core.tts_engine import synthesize_tts_async, synthesize_tts_to_mulaw
from ..core import scam_database

logger = logging.getLogger("scambot")

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2  # 16-bit PCM
CHANNELS = 1

MEDIA_SILENCE_THRESHOLD = 0.01
MIN_SPEECH_DURATION = 1.5
MAX_CONVERSATION_HISTORY = 20
MAX_AUDIO_BUFFER_SECONDS = 10
SILENCE_DURATION = 0.8  # seconds of silence to end a turn
SILENCE_RMS_THRESHOLD = 400  # 16-bit PCM RMS below this counts as silence
CHUNK_DURATION = 0.02  # Twilio sends 20ms media frames


@dataclass
class StreamSession:
    call_sid: str
    stream_sid: str
    from_number: str
    to_number: str
    audio_buffer: bytes = field(default=b"")
    audio_chunks: deque = field(default_factory=deque)
    silent_chunks: int = 0
    sample_rate: int = SAMPLE_RATE
    is_processing: bool = False
    transcript_so_far: str = ""
    conversation_history: list = field(default_factory=list)
    response_queue: list = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def reset_audio(self):
        self.audio_buffer = b""
        self.audio_chunks.clear()
        self.silent_chunks = 0

    def append_audio(self, data: bytes):
        self.audio_buffer += data
        max_bytes = self.sample_rate * SAMPLE_WIDTH * MAX_AUDIO_BUFFER_SECONDS
        if len(self.audio_buffer) > max_bytes:
            self.audio_buffer = self.audio_buffer[-max_bytes:]

    def get_audio_file(self, prefix: str = "chunk") -> str:
        import time
        ts = int(time.time() * 1000)
        filename = f"{prefix}_{ts}.wav"
        filepath = Path(settings.RECORDING_DIR) / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        return str(filepath)

    def save_audio_to_wav(self, raw_audio: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        filepath = self.get_audio_file("stream")
        _pcm_to_wav(raw_audio, filepath, sample_rate=sample_rate)
        return filepath


def ulaw_to_pcm(ulaw_data: bytes) -> bytes:
    return audioop.ulaw2lin(ulaw_data, SAMPLE_WIDTH)


def _pcm_to_wav(pcm_data: bytes, output_path: str, sample_rate: int = SAMPLE_RATE,
                channels: int = CHANNELS, sample_width: int = SAMPLE_WIDTH):
    with wave.open(output_path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)


def _cleanup_old_chunks():
    if not os.path.exists(settings.RECORDING_DIR):
        return
    cutoff = datetime.now(timezone.utc).timestamp() - settings.RECORDING_RETENTION_DAYS * 86400
    if settings.RECORDING_RETENTION_DAYS <= 0:
        return
    for f in Path(settings.RECORDING_DIR).iterdir():
        if f.name.startswith("stream_") or f.name.startswith("chunk_"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass


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


async def handle_media_chunk(session: StreamSession, ulaw_data: bytes):
    pcm_data = ulaw_to_pcm(ulaw_data)
    session.append_audio(pcm_data)

    rms = audioop.rms(pcm_data, SAMPLE_WIDTH)
    if rms < SILENCE_RMS_THRESHOLD:
        session.silent_chunks += 1
    else:
        session.silent_chunks = 0

    min_bytes = session.sample_rate * SAMPLE_WIDTH * MIN_SPEECH_DURATION
    if len(session.audio_buffer) < min_bytes:
        return

    if session.is_processing:
        return

    # Wait for a pause (end of utterance) before replying, unless the
    # buffer hits the max (long monologue with no pause).
    silence_seconds = session.silent_chunks * CHUNK_DURATION
    max_bytes = session.sample_rate * SAMPLE_WIDTH * MAX_AUDIO_BUFFER_SECONDS
    if silence_seconds < SILENCE_DURATION and len(session.audio_buffer) < max_bytes:
        return

    session.is_processing = True
    await process_audio_chunk(session)


async def process_audio_chunk(session: StreamSession):
    min_bytes = session.sample_rate * SAMPLE_WIDTH * MIN_SPEECH_DURATION
    if len(session.audio_buffer) < min_bytes:
        session.is_processing = False
        return

    snapshot = session.audio_buffer
    session.reset_audio()

    audio_file = session.save_audio_to_wav(snapshot, session.sample_rate)

    try:
        transcription = await transcribe_audio_async(audio_file)
        transcription = transcription.strip()
        if not transcription:
            _cleanup_chunk_file(audio_file)
            return

        session.transcript_so_far += f"\nScammer: {transcription}"
        logger.info("[STREAM] %s: %s", session.from_number, transcription)

        from ..core.database import SessionLocal
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
                    record.metadata_json["scam_type"] = scam_type.value if scam_type else ""
            if record:
                existing = record.transcript or ""
                record.transcript = existing + f"\nScammer: {transcription}\n"
            db.commit()

            await _generate_and_queue_response(session, transcription)
        finally:
            db.close()

    except Exception as e:
        logger.error("[STREAM] Error processing audio: %s", e)
    finally:
        _cleanup_chunk_file(audio_file)
        session.is_processing = False


async def _generate_and_queue_response(session: StreamSession, transcription: str):
    try:
        persona = settings.DEFAULT_PERSONA
        reply_text = await generate_reply_async(
            transcription, persona, session.conversation_history
        )
        if not reply_text or not reply_text.strip():
            reply_text = "Hmm? Say that again, sonny, my hearing isn't what it used to be."

        session.conversation_history.extend([
            {"role": "user", "content": transcription},
            {"role": "assistant", "content": reply_text},
        ])
        session.conversation_history = session.conversation_history[-MAX_CONVERSATION_HISTORY:]

        session.transcript_so_far += f"\nAI ({persona}): {reply_text}"

        output_file = session.get_audio_file("reply_mulaw")
        mulaw_b64 = await synthesize_tts_to_mulaw(reply_text, output_file, persona)
        session.response_queue.append(mulaw_b64)
        logger.info("[STREAM] AI reply: %s...", reply_text[:80])

    except Exception as e:
        logger.error("[STREAM] Error generating reply: %s", e)


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


def _cleanup_chunk_file(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.unlink(filepath)
    except Exception:
        pass


def save_session_transcript(session: StreamSession):
    from ..core.database import SessionLocal
    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=session.call_sid).first()
        if record:
            if session.transcript_so_far:
                record.transcript = session.transcript_so_far
            if session.response_queue:
                record.metadata_json["tts_files"] = len(session.response_queue)
            db.commit()
            _cleanup_old_chunks()
    finally:
        db.close()
