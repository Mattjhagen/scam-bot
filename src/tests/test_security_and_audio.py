import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.core.tts_engine import _cache_key, clear_cache, synthesize_tts_to_mulaw
from src.telephony.media_stream import (
    StreamSession,
    create_session,
    end_session,
    get_session,
    handle_media_chunk,
    ulaw_to_pcm,
    _pcm_to_wav,
    save_session_transcript,
)
from src.core.notifier import _build_sms_body
from src.core.models import CallRecord
from src.core.database import SessionLocal
from src.core import scam_database


def test_ulaw_to_pcm_roundtrip():
    import audioop
    pcm_original = bytes(range(256)) * 100
    ulaw = audioop.lin2ulaw(pcm_original, 2)
    pcm_restored = ulaw_to_pcm(ulaw)
    assert len(pcm_restored) == len(pcm_original)


def test_ulaw_decode_nonempty():
    import audioop
    sine_data = bytes([(i % 256) for i in range(320)])
    ulaw = audioop.lin2ulaw(sine_data, 2)
    pcm = ulaw_to_pcm(ulaw)
    assert len(pcm) > 0
    assert isinstance(pcm, bytes)


@pytest.mark.asyncio
async def test_synthesize_tts_to_mulaw_format():
    import tempfile
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = str(Path(tmpdir) / "test.mulaw")

        with patch("src.core.tts_engine.synthesize_tts_gtts") as mock_gtts:
            def fake_gtts(text, outfile):
                from pydub import AudioSegment
                from pydub.generators import Sine
                tone = Sine(440).to_audio_segment(duration=100)
                tone.export(outfile, format="mp3")
                return outfile
            mock_gtts.side_effect = fake_gtts

            from src.config import settings
            settings.TTS_PROVIDER = "gtts"
            result = await synthesize_tts_to_mulaw("hello", output_file)
            assert isinstance(result, str)
            assert len(result) > 0
            from src.core.tts_engine import _tts_cache
            _tts_cache.clear()


def test_normalize_phone_number():
    from src.core import scam_database
    assert scam_database.normalize_phone_number("(555) 123-4567") == "+15551234567"
    assert scam_database.normalize_phone_number("+15551234567") == "+15551234567"
    assert scam_database.normalize_phone_number("5551234567") == "+15551234567"


def test_normalize_invalid_phone():
    from src.core import scam_database
    result = scam_database.normalize_phone_number("not a phone")
    assert isinstance(result, str)
    assert len(result) > 0


def test_metadata_json_persistence():
    from src.core.models import CallRecord
    from src.core.database import SessionLocal, init_db
    from src.core import scam_database
    import uuid

    init_db()
    db = SessionLocal()
    scam_database.seed_database(db)

    call_sid = f"CA_META_{uuid.uuid4().hex[:8]}"
    record = CallRecord(
        call_sid=call_sid,
        from_number="+15551234567",
        status="incoming",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    record.metadata_json["scam_type"] = "tech_support"
    record.metadata_json["known_scam"] = True
    db.commit()
    db.refresh(record)

    assert record.metadata_json["scam_type"] == "tech_support"
    assert record.metadata_json["known_scam"] is True

    db.query(CallRecord).filter_by(call_sid=call_sid).delete()
    db.commit()
    db.close()


def test_conversation_history_roles():
    session = create_session("CA_ROLES", "ME_ROLES", "+15551234567", "+12025551234")

    scammer_text = "Your computer has a virus"
    ai_reply = "Well, back in '82..."

    session.conversation_history.extend([
        {"role": "user", "content": scammer_text},
        {"role": "assistant", "content": ai_reply},
    ])

    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[0]["content"] == scammer_text
    assert session.conversation_history[1]["role"] == "assistant"
    assert session.conversation_history[1]["content"] == ai_reply
    end_session("ME_ROLES")


def test_audio_buffer_retention():
    session = create_session("CA_BUF", "ME_BUF", "+15551234567", "+12025551234")

    large_data = b"\x00\x01" * 16000 * 5  # 5 seconds of audio
    session.append_audio(large_data)

    max_bytes = session.sample_rate * 2 * 10  # 10 seconds max
    assert len(session.audio_buffer) <= max_bytes
    end_session("ME_BUF")


def test_bulk_import_updates_existing():
    from src.core.database import init_db, SessionLocal
    init_db()
    db = SessionLocal()
    from src.core import scam_database
    scam_database.seed_database(db)

    from fastapi.testclient import TestClient
    from src.main import app
    with TestClient(app) as client:
        response = client.post("/api/scam-numbers/bulk-import", json=[
            {"phone_number": "+18002311500", "scam_type": "tech_support", "caller_name": "Updated Name", "confidence": 0.99},
        ])
        assert response.status_code == 200
        data = response.json()
        assert data["added"] == 0
        assert len(data["errors"]) == 0

    db.expire_all()
    from src.core.models import ScamNumber
    updated = db.query(ScamNumber).filter_by(phone_number="+18002311500").first()
    assert updated.caller_name == "Updated Name"
    assert updated.confidence == 0.99
    db.close()


def test_scam_report_threshold_blocks_after_3_reports():
    from src.core import scam_database
    from src.core.database import init_db, SessionLocal

    init_db()
    db = SessionLocal()
    scam_database.seed_database(db)

    entry, report = scam_database.add_scam_report(db, "+15551112222", "reporter@test.com", "general", "Test")
    assert entry.is_blocked is False
    assert entry.report_count == 1

    entry, _ = scam_database.add_scam_report(db, "+15551112222", "reporter2@test.com", "general", "Test2")
    assert entry.is_blocked is False
    assert entry.report_count == 2

    entry, _ = scam_database.add_scam_report(db, "+15551112222", "reporter3@test.com", "general", "Test3")
    assert entry.is_blocked is True
    assert entry.report_count == 3

    db.close()


def test_notifier_never_sms_scammer():
    from src.core.notifier import send_call_notification
    from src.core.models import CallRecord
    from src.core.database import SessionLocal
    import asyncio

    from src.config import settings
    orig_owner = settings.OWNER_PHONE
    orig_send = settings.SEND_SMS_NOTES
    settings.OWNER_PHONE = "+15550001111"
    settings.SEND_SMS_NOTES = True

    db = SessionLocal()
    record = CallRecord(
        call_sid="CA_NOTIFY_TEST",
        from_number="+18002311500",
        to_number="+12025551234",
        status="completed",
        scam_detected=True,
        scam_confidence=0.95,
    )
    record.metadata_json = {"scam_type": "tech_support"}
    db.add(record)
    db.commit()
    db.refresh(record)

    with patch("src.core.notifier.call_manager") as mock_cm:
        mock_cm.send_sms.return_value = "SM_TEST"
        asyncio.run(send_call_notification(db, record, None))

        mock_cm.send_sms.assert_called_once()
        args = mock_cm.send_sms.call_args[0]
        assert args[0] == "+15550001111"
        assert args[0] != "+18002311500"

    db.query(CallRecord).filter_by(call_sid="CA_NOTIFY_TEST").delete()
    db.commit()
    db.close()

    settings.OWNER_PHONE = orig_owner
    settings.SEND_SMS_NOTES = orig_send


def test_notifier_skips_when_owner_phone_unset():
    from src.core.notifier import send_call_notification
    from src.core.models import CallRecord
    from src.core.database import SessionLocal
    import asyncio

    from src.config import settings
    orig_owner = settings.OWNER_PHONE
    orig_send = settings.SEND_SMS_NOTES
    settings.OWNER_PHONE = ""
    settings.SEND_SMS_NOTES = True

    db = SessionLocal()
    record = CallRecord(
        call_sid="CA_NO_OWNER",
        from_number="+18002311500",
        to_number="+12025551234",
        status="completed",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    with patch("src.core.notifier.call_manager") as mock_cm:
        result = asyncio.run(send_call_notification(db, record, None))
        assert result is None
        mock_cm.send_sms.assert_not_called()

    db.query(CallRecord).filter_by(call_sid="CA_NO_OWNER").delete()
    db.commit()
    db.close()

    settings.OWNER_PHONE = orig_owner
    settings.SEND_SMS_NOTES = orig_send


def test_report_confirmation_to_reporter():
    from src.core.notifier import send_scam_report_confirmation
    import asyncio

    from src.config import settings
    orig_send = settings.SEND_SMS_NOTES
    settings.SEND_SMS_NOTES = True

    with patch("src.core.notifier.call_manager") as mock_cm:
        mock_cm.send_sms.return_value = "SM_TEST"
        asyncio.run(send_scam_report_confirmation("+15550001111", 42, "+18002311500"))

        mock_cm.send_sms.assert_called_once()
        args = mock_cm.send_sms.call_args[0]
        assert "+15550001111" in args[0]
        assert "+18002311500" not in args[0]

    settings.SEND_SMS_NOTES = orig_send
