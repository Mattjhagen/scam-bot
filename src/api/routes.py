import base64
import io
import json
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse

from ..config import settings
from ..core import scam_database
from ..core.database import get_db, SessionLocal
from ..core.models import CallRecord, CallStatus, ScamNumber, ScamReport, User, ScamType
from ..core.schemas import (
    ScamNumberResponse,
    ScamReportResponse,
    ScamReportCreate,
    UserCreate,
    UserResponse,
)
from ..telephony.media_stream import (
    create_session,
    end_session,
    get_session,
    handle_media_chunk,
    drain_response_queue,
    save_session_transcript,
)

router = APIRouter()

_ws_connections: dict[str, WebSocket] = {}


@router.post("/telephony/voice")
async def voice_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From", "")
    call_sid = form.get("CallSid", "")

    db = SessionLocal()
    try:
        is_scam, confidence, scam_type, db_match = scam_database.detect_scam(db, from_number, "")

        record = scam_database.create_or_update_call_record(db, call_sid, from_number)

        if is_scam and db_match:
            record.scam_detected = True
            record.scam_confidence = confidence
            record.metadata_json = record.metadata_json or {}
            record.metadata_json["scam_type"] = scam_type.value if scam_type else ""
            record.metadata_json["known_scam"] = True
            db.commit()

            resp = VoiceResponse()
            resp.say(
                "This number has been identified as a known scam source. "
                "Your call has been recorded for evidence.",
                voice="Polly.Joanna",
                language="en-US",
            )
            resp.hangup()
            return Response(content=str(resp), media_type="text/xml")

        resp = VoiceResponse()
        resp.say(
            "Hello, this is a test. Please wait while we connect you.",
            voice="alice",
            language="en-US",
        )
        resp.pause(length=1)

        if settings.PUBLIC_HOST:
            stream_url = f"wss://{settings.PUBLIC_HOST}/telephony/media-stream"
            resp.stream(
                url=stream_url,
                track="inbound_track",
                status_callback=f"https://{settings.PUBLIC_HOST}/telephony/stream-status",
            )

        if settings.RECORD_CALLS:
            resp.record(
                recording_status_callback=f"https://{settings.PUBLIC_HOST}/telephony/recording-status" if settings.PUBLIC_HOST else None,
                max_length=300,
            )

        resp.hangup()
        return Response(content=str(resp), media_type="text/xml")
    finally:
        db.close()


@router.post("/telephony/recording-status")
async def recording_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    recording_sid = form.get("RecordingSid", "")
    recording_url = form.get("RecordingUrl", "")

    db = SessionLocal()
    try:
        record = scam_database.update_call_record(
            db, call_sid,
            recording_sid=recording_sid,
            recording_url=recording_url,
            status=CallStatus.COMPLETED,
            ended_at=datetime.now(timezone.utc),
        )
        if record:
            import asyncio
            try:
                asyncio.create_task(_run_notify_async(db, call_sid))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.create_task(_run_notify_async(db, call_sid))
    finally:
        db.close()

    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="text/xml")


async def _run_notify_async(db, call_sid: str):
    from ..core.notifier import notify_user_after_call
    await notify_user_after_call(db, call_sid)


@router.post("/telephony/call-status")
async def call_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status_val = form.get("CallStatus", "")

    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
        if record:
            if status_val == "completed":
                record.status = CallStatus.COMPLETED
                record.ended_at = datetime.now(timezone.utc)
            elif status_val in ("ringing", "in-progress"):
                record.status = CallStatus.HANDLED
            db.commit()
    finally:
        db.close()

    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="text/xml")


@router.post("/telephony/stream-status")
async def stream_status(request: Request):
    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="text/xml")


@router.get("/telephony/media-stream")
async def websocket_media_stream(websocket: WebSocket):
    await websocket.accept()
    stream_sid: str = ""
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get("event", "")

            if event == "start":
                stream_sid = msg.get("stream", {}).get("sid", "")
                call_sid = msg.get("call_sid", "")
                from_number = msg.get("from", "")
                to_number = msg.get("to", "")

                session = create_session(call_sid, stream_sid, from_number, to_number)
                _ws_connections[stream_sid] = websocket

                if settings.RECORD_CALLS:
                    Path(settings.RECORDING_DIR).mkdir(parents=True, exist_ok=True)

            elif event == "media":
                if not stream_sid:
                    continue
                session = get_session(stream_sid)
                if not session:
                    continue

                payload = msg.get("media", {}).get("payload", "")
                if payload:
                    audio_data = base64.b64decode(payload)
                    await handle_media_chunk(session, audio_data)

                    if session.response_queue:
                        audio_file = await drain_response_queue(session)
                        if audio_file and Path(audio_file).exists():
                            audio_b64 = base64.b64encode(Path(audio_file).read_bytes()).decode()
                            await websocket.send_json({
                                "event": "media",
                                "stream_sid": stream_sid,
                                "media": {"payload": audio_b64},
                            })

            elif event == "stop":
                session = get_session(stream_sid)
                if session:
                    save_session_transcript(session)
                    end_session(stream_sid)
                _ws_connections.pop(stream_sid, None)
                await websocket.close()
                return

    except WebSocketDisconnect:
        end_session(stream_sid)
        _ws_connections.pop(stream_sid, None)
    except Exception as e:
        print(f"[WS] Error: {e}")
        end_session(stream_sid)
        _ws_connections.pop(stream_sid, None)
        await websocket.close()


# --- REST API endpoints ---

@router.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter_by(phone_number=user_in.phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(**user_in.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/api/scam-reports", response_model=ScamReportResponse, status_code=status.HTTP_201_CREATED)
async def submit_scam_report(report_in: ScamReportCreate, db: Session = Depends(get_db)):
    scam_number = scam_database.add_scam_report(
        db, report_in.phone_number, report_in.reported_by,
        report_in.scam_type, report_in.notes,
    )
    report = db.query(ScamReport).filter(
        ScamReport.phone_number == report_in.phone_number,
    ).order_by(ScamReport.id.desc()).first()

    if settings.SEND_SMS_NOTES and report_in.reported_by:
        import asyncio
        from ..core.notifier import send_scam_report_confirmation
        try:
            asyncio.create_task(send_scam_report_confirmation(report_in.phone_number, report.id))
        except RuntimeError:
            pass

    return report


@router.get("/api/scam-numbers", response_model=list[ScamNumberResponse])
async def list_scam_numbers(skip: int = 0, limit: int = 100, search: str = None):
    db = SessionLocal()
    try:
        query = db.query(ScamNumber)
        if search:
            like_pattern = f"%{search}%"
            query = query.filter(
                ScamNumber.phone_number.contains(search) |
                ScamNumber.caller_name.like(like_pattern)
            )
        numbers = query.offset(skip).limit(limit).all()
        return numbers
    finally:
        db.close()


@router.get("/api/calls", response_model=list)
async def list_calls(skip: int = 0, limit: int = 50):
    db = SessionLocal()
    try:
        records = db.query(CallRecord).order_by(CallRecord.started_at.desc()).offset(skip).limit(limit).all()
        return [
            {
                "id": r.id,
                "call_sid": r.call_sid,
                "from_number": r.from_number,
                "to_number": r.to_number,
                "status": r.status.value if r.status else "unknown",
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "recording_url": r.recording_url,
                "transcript": r.transcript,
                "scam_detected": r.scam_detected,
                "scam_confidence": r.scam_confidence,
            }
            for r in records
        ]
    finally:
        db.close()


@router.get("/api/calls/{call_sid}")
async def get_call_detail(call_sid: str):
    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
        if not record:
            raise HTTPException(status_code=404, detail="Call not found")
        return {
            "id": record.id,
            "call_sid": record.call_sid,
            "from_number": record.from_number,
            "to_number": record.to_number,
            "status": record.status.value if record.status else "unknown",
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "ended_at": record.ended_at.isoformat() if record.ended_at else None,
            "recording_url": record.recording_url,
            "recording_sid": record.recording_sid,
            "transcript": record.transcript,
            "scam_detected": record.scam_detected,
            "scam_confidence": record.scam_confidence,
            "metadata": record.metadata_json,
        }
    finally:
        db.close()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ScamBot", "version": "1.0.0"}


@router.get("/api/scam-types")
async def get_scam_types():
    from ..core.models import ScamType as ST
    return [{"value": t.value, "label": t.value.replace("_", " ").title()} for t in ST]


@router.get("/api/calls/{call_sid}/export", response_class=PlainTextResponse)
async def export_call_transcript(call_sid: str):
    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
        if not record:
            raise HTTPException(status_code=404, detail="Call not found")
        lines = [
            f"=== ScamBot Call Transcript ===",
            f"Call SID: {record.call_sid}",
            f"From: {record.from_number}",
            f"To: {record.to_number or 'N/A'}",
            f"Started: {record.started_at.isoformat() if record.started_at else 'N/A'}",
            f"Ended: {record.ended_at.isoformat() if record.ended_at else 'N/A'}",
            f"Scam Detected: {'Yes' if record.scam_detected else 'No'}",
            f"Confidence: {record.scam_confidence:.0%}" if record.scam_confidence > 0 else "Confidence: N/A",
            f"Recording: {record.recording_url or 'N/A'}",
            "",
            "=== Transcript ===",
            record.transcript or "No transcript available",
        ]
        text = "\n".join(lines)
        return Response(content=text, media_type="text/plain", headers={
            "Content-Disposition": f"attachment; filename=scambot_transcript_{call_sid}.txt"
        })
    finally:
        db.close()


@router.post("/api/scam-numbers/bulk-import")
async def bulk_import_scam_numbers(numbers: List[dict], db: Session = Depends(get_db)):
    added = 0
    errors = []
    for entry in numbers:
        try:
            phone = scam_database.normalize_phone_number(entry["phone_number"])
            existing = db.query(ScamNumber).filter_by(phone_number=phone).first()
            if existing:
                existing.report_count += 1
                existing.last_seen = datetime.now(timezone.utc)
                if entry.get("scam_type"):
                    existing.scam_type = ScamType(entry["scam_type"])
                if entry.get("confidence"):
                    existing.confidence = entry["confidence"]
                existing.metadata_json = existing.metadata_json or {}
                existing.metadata_json.update(entry.get("metadata_json", {}))
                db.add(existing)
            else:
                new_num = ScamNumber(
                    phone_number=phone,
                    caller_name=entry.get("caller_name"),
                    scam_type=ScamType(entry.get("scam_type", "general")),
                    notes=entry.get("notes"),
                    confidence=entry.get("confidence", 0.5),
                    is_blocked=entry.get("is_blocked", True),
                    metadata_json=entry.get("metadata_json", {}),
                )
                db.add(new_num)
                added += 1
        except Exception as e:
            errors.append({"entry": entry, "error": str(e)})
    db.commit()
    return {"added": added, "errors": errors}
