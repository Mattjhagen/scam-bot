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

    summary = ""
    if call_record.transcript:
        scam_type_str = call_record.metadata_json.get("scam_type", "") if call_record.metadata_json else ""
        summary = await _safe_summarize(call_record.transcript, scam_type_str)

    body = _build_sms_body(call_record, summary)

    phone = (user and user.phone_number) or call_record.from_number
    message_sid = await asyncio.get_event_loop().run_in_executor(
        None, call_manager.send_sms, phone, body
    )

    notification = Notification(
        call_record_id=call_record.id,
        user_id=user.id if user else None,
        phone_number=phone,
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
    lines = ["[ScamBot] Call Summary"]
    scam_type = call_record.metadata_json.get("scam_type", "Unknown") if call_record.metadata_json else "Unknown"
    lines.append(f"Scammer: {call_record.from_number}")
    lines.append(f"Scam type: {scam_type}")
    lines.append(f"Detected: {'Yes' if call_record.scam_detected else 'No'}")
    if call_record.scam_confidence > 0:
        lines.append(f"Confidence: {call_record.scam_confidence:.0%}")
    lines.append(f"Duration: {call_record.started_at}")
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

    user = db_session.query(User).filter_by(phone_number=record.from_number).first()
    if not user:
        user_match = scam_database.check_number_in_db(db_session, record.from_number)
        if user_match and user_match.metadata_json and user_match.metadata_json.get("user_phone"):
            user = db_session.query(User).filter_by(phone_number=user_match.metadata_json["user_phone"]).first()

    return await send_call_notification(db_session, record, user)


async def send_scam_report_confirmation(phone_number: str, report_id: int):
    if not settings.SEND_SMS_NOTES:
        return None
    body = (
        f"ScamBot: Thanks for your report. Your report #{report_id} for {phone_number} "
        f"has been recorded and will be reviewed. Stay safe!"
    )
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, call_manager.send_sms, phone_number, body)
