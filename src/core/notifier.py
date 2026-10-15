import asyncio
from datetime import datetime, timezone

from ..config import settings
from ..core.models import CallRecord, Notification, NotificationStatus, User
from ..core import scam_database
from ..nlp import summarize_transcript
from ..telephony.call_manager import call_manager


async def send_call_notification(db_session, call_record: CallRecord, user: User = None):
    if not settings.SEND_SMS_NOTES:
        return None

    owner_phone = settings.OWNER_PHONE
    if not owner_phone:
        print(f"[NOTIFY] OWNER_PHONE not set, skipping notification for call {call_record.call_sid}")
        return None

    summary = ""
    if call_record.transcript:
        scam_type_str = call_record.metadata_json.get("scam_type", "") if call_record.metadata_json else ""
        summary = await _safe_summarize(call_record.transcript, scam_type_str)

    body = _build_sms_body(call_record, summary)

    message_sid = await asyncio.get_event_loop().run_in_executor(
        None, call_manager.send_sms, owner_phone, body
    )

    notification = Notification(
        call_record_id=call_record.id,
        user_id=None,
        phone_number=owner_phone,
        channel="sms",
        status=NotificationStatus.SENT if message_sid else NotificationStatus.FAILED,
        content=body,
        sent_at=datetime.now(timezone.utc) if message_sid else None,
        error_message=None if message_sid else "Failed to send SMS (no Twilio client configured)",
    )
    db_session.add(notification)
    db_session.commit()
    db_session.refresh(notification)
    return notification


async def _safe_summarize(transcript: str, scam_type: str = None) -> str:
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, summarize_transcript, transcript, scam_type
        )
    except Exception:
        return transcript[:500] + ("..." if len(transcript) > 500 else "")


def _build_sms_body(call_record: CallRecord, summary: str) -> str:
    duration_str = "Unknown"
    if call_record.started_at and call_record.ended_at:
        delta = call_record.ended_at - call_record.started_at
        secs = int(delta.total_seconds())
        duration_str = f"{secs // 60}m {secs % 60}s"
    elif call_record.ended_at and call_record.started_at:
        duration_str = "Ended"

    scam_type = "Unknown"
    if call_record.metadata_json and call_record.metadata_json.get("scam_type"):
        scam_type = call_record.metadata_json["scam_type"]

    lines = ["[ScamBot] Call Summary"]
    lines.append(f"Scammer: {call_record.from_number}")
    lines.append(f"Scam type: {scam_type}")
    lines.append(f"Detected: {'Yes' if call_record.scam_detected else 'No'}")
    if call_record.scam_confidence > 0:
        lines.append(f"Confidence: {call_record.scam_confidence:.0%}")
    lines.append(f"Duration: {duration_str}")
    lines.append("")
    if summary:
        lines.append(summary[:1000])
    lines.append("")
    lines.append("Full transcript & recording available in the app.")
    return "\n".join(lines)


async def notify_user_after_call(db_session, call_sid: str):
    record = db_session.query(CallRecord).filter_by(call_sid=call_sid).first()
    if not record:
        return None
    return await send_call_notification(db_session, record, None)


async def send_scam_report_confirmation(reported_by: str, report_id: int, phone_number: str):
    if not settings.SEND_SMS_NOTES:
        return None
    if not reported_by:
        return None
    body = (
        f"ScamBot: Thanks for your report #{report_id} for {phone_number}. "
        f"It has been recorded and will be reviewed. Stay safe!"
    )
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call_manager.send_sms, reported_by, body)
