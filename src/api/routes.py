import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, PlainTextResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy.ext.mutable import MutableDict
from twilio.twiml.voice_response import VoiceResponse
from twilio.request_validator import RequestValidator

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
from ..core.rate_limiter import _report_limiter

logger = logging.getLogger("scambot")
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

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _validate_twilio_request(request: Request, form_data: dict) -> bool:
    if not settings.TWILIO_AUTH_TOKEN:
        return True
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    signature = request.headers.get("X-Twilio-Signature", "")
    if settings.PUBLIC_HOST:
        url = f"https://{settings.PUBLIC_HOST}{request.url.path}"
    else:
        url = str(request.url)
    form = {k: v for k, v in form_data.items() if isinstance(v, str)}
    return validator.validate(url, form, signature)


def _require_api_key(api_key: Optional[str] = None):
    if not settings.API_KEY:
        return
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


# --- Twilio Webhooks ---

@router.post("/telephony/voice")
async def voice_webhook(request: Request):
    form = await request.form()
    from_number = form.get("From", "")
    call_sid = form.get("CallSid", "")

    if not _validate_twilio_request(request, dict(form)):
        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
                        media_type="text/xml", status_code=403)

    db = SessionLocal()
    try:
        is_scam, confidence, scam_type, db_match = scam_database.detect_scam(db, from_number, "")

        record = scam_database.create_or_update_call_record(db, call_sid, from_number)

        if is_scam and db_match:
            record.scam_detected = True
            record.scam_confidence = confidence
            if record.metadata_json is None:
                record.metadata_json = {}
            record.metadata_json["scam_type"] = scam_type.value if scam_type else ""
            record.metadata_json["known_scam"] = True
            db.commit()

            resp = VoiceResponse()
            resp.say(
                "This number has been identified as a known scam source. "
                "This call is being recorded for evidence. Please hang up.",
                voice="Polly.Joanna",
                language="en-US",
            )
            resp.hangup()
            return Response(content=str(resp), media_type="text/xml")

        resp = VoiceResponse()
        resp.say(
            "Hello, you are now connected to ScamBot. "
            "This call is being recorded for quality and evidence purposes. "
            "Please state your name and reason for calling.",
            voice="alice",
            language="en-US",
        )
        resp.pause(length=1)

        if settings.PUBLIC_HOST:
            stream_url = f"wss://{settings.PUBLIC_HOST}/telephony/media-stream"
            connect = resp.connect()
            connect.stream(
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

    if not _validate_twilio_request(request, dict(form)):
        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
                        media_type="text/xml", status_code=403)

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
            fresh_db = SessionLocal()
            asyncio.ensure_future(_run_notify_async(fresh_db, call_sid))
    finally:
        db.close()

    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="text/xml")


async def _run_notify_async(fresh_db, call_sid: str):
    from ..core.notifier import notify_user_after_call
    try:
        await notify_user_after_call(fresh_db, call_sid)
    finally:
        fresh_db.close()


@router.post("/telephony/call-status")
async def call_status(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status_val = form.get("CallStatus", "")

    if not _validate_twilio_request(request, dict(form)):
        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
                        media_type="text/xml", status_code=403)

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
    form = await request.form()
    if not _validate_twilio_request(request, dict(form)):
        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
                        media_type="text/xml", status_code=403)
    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response></Response>", media_type="text/xml")


@router.websocket("/telephony/media-stream")
async def websocket_media_stream(websocket: WebSocket):
    await websocket.accept()
    stream_sid: str = ""
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get("event", "")

            if event == "start":
                start = msg.get("start", {})
                stream_sid = msg.get("streamSid") or start.get("streamSid", "")
                call_sid = start.get("callSid", "")
                custom = start.get("customParameters", {}) or {}
                from_number = custom.get("from", "")
                to_number = custom.get("to", "")

                session = create_session(call_sid, stream_sid, from_number, to_number)
                _ws_connections[stream_sid] = websocket

                if settings.RECORD_CALLS:
                    Path(settings.RECORDING_DIR).mkdir(parents=True, exist_ok=True)

                # Test mode: scammer speaks first (Beat 1 opener)
                if settings.SCAMBOT_TEST_MODE == "scammer":
                    from ..telephony.media_stream import queue_scammer_opener

                    await queue_scammer_opener(session)

            elif event == "media":
                if not stream_sid:
                    continue
                session = get_session(stream_sid)
                if not session:
                    continue

                payload = msg.get("media", {}).get("payload", "")
                if payload:
                    ulaw_data = base64.b64decode(payload)
                    await handle_media_chunk(session, ulaw_data)

                    if session.response_queue:
                        mulaw_b64 = await drain_response_queue(session)
                        if mulaw_b64:
                            mulaw_bytes = base64.b64decode(mulaw_b64)
                            for i in range(0, len(mulaw_bytes), 160):
                                chunk = base64.b64encode(mulaw_bytes[i:i + 160]).decode()
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": chunk},
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
        logger.error("[WS] Error: %s", e)
        end_session(stream_sid)
        _ws_connections.pop(stream_sid, None)
        await websocket.close()


# --- REST API endpoints ---

@router.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate, db: Session = Depends(get_db),
                        api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
    existing = db.query(User).filter_by(phone_number=user_in.phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(**user_in.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/api/scam-reports", response_model=ScamReportResponse, status_code=status.HTTP_201_CREATED)
async def submit_scam_report(request: Request, report_in: ScamReportCreate, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = _report_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    _, report = scam_database.add_scam_report(
        db, report_in.phone_number, report_in.reported_by,
        report_in.scam_type, report_in.notes,
    )

    if settings.SEND_SMS_NOTES and report_in.reported_by:
        import asyncio
        from ..core.notifier import send_scam_report_confirmation
        try:
            asyncio.ensure_future(send_scam_report_confirmation(report_in.reported_by, report.id, report_in.phone_number))
        except RuntimeError:
            pass

    return report


@router.get("/api/scam-numbers", response_model=list[ScamNumberResponse])
async def list_scam_numbers(skip: int = 0, limit: int = 100, search: str = None,
                            api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
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
async def list_calls(skip: int = 0, limit: int = 50,
                     api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
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
async def get_call_detail(call_sid: str, api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
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


@router.get("/api/calls/{call_sid}/export", response_class=PlainTextResponse)
async def export_call_transcript(call_sid: str, api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
    db = SessionLocal()
    try:
        record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
        if not record:
            raise HTTPException(status_code=404, detail="Call not found")
        duration_str = "Unknown"
        if record.started_at and record.ended_at:
            delta = record.ended_at - record.started_at
            secs = int(delta.total_seconds())
            duration_str = f"{secs // 60}m {secs % 60}s"

        scam_type = "Unknown"
        if record.metadata_json and record.metadata_json.get("scam_type"):
            scam_type = record.metadata_json["scam_type"]

        lines = [
            "=== ScamBot Call Transcript ===",
            f"Call SID: {record.call_sid}",
            f"From: {record.from_number}",
            f"To: {record.to_number or 'N/A'}",
            f"Started: {record.started_at.isoformat() if record.started_at else 'N/A'}",
            f"Ended: {record.ended_at.isoformat() if record.ended_at else 'N/A'}",
            f"Duration: {duration_str}",
            f"Scam Detected: {'Yes' if record.scam_detected else 'No'}",
            f"Confidence: {record.scam_confidence:.0%}" if record.scam_confidence > 0 else "Confidence: N/A",
            f"Scam Type: {scam_type}",
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
async def bulk_import_scam_numbers(numbers: List[dict], db: Session = Depends(get_db),
                                   api_key: Optional[str] = Depends(API_KEY_HEADER)):
    _require_api_key(api_key)
    added = 0
    errors = []
    for entry in numbers:
        try:
            phone = scam_database.normalize_phone_number(entry["phone_number"])
            existing = db.query(ScamNumber).filter_by(phone_number=phone).first()
            if existing:
                existing.report_count = entry.get("report_count", existing.report_count)
                existing.last_seen = datetime.now(timezone.utc)
                if entry.get("scam_type"):
                    existing.scam_type = ScamType(entry["scam_type"])
                if entry.get("confidence") is not None:
                    existing.confidence = entry["confidence"]
                if entry.get("caller_name"):
                    existing.caller_name = entry["caller_name"]
                if entry.get("notes"):
                    existing.notes = entry["notes"]
                if entry.get("is_blocked") is not None:
                    existing.is_blocked = entry["is_blocked"]
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


@router.get("/health")
async def health_check():
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        return Response(
            content=json.dumps({"status": "unhealthy", "database": "error", "error": str(e)}),
            media_type="application/json",
            status_code=503,
        )
    finally:
        db.close()
    return {"status": "healthy", "service": "ScamBot", "version": "1.0.0", "database": db_status}


@router.get("/api/scam-types")
async def get_scam_types():
    return [{"value": t.value, "label": t.value.replace("_", " ").title()} for t in ScamType]
