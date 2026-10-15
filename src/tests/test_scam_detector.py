import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock

from src.core.database import Base, SessionLocal, engine, init_db
from src.core.models import ScamNumber, ScamReport, CallRecord, User
from src.core import scam_database
from src.core.schemas import ScamNumberCreate, ScamReportCreate, UserCreate


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    db = SessionLocal()
    scam_database.seed_database(db)
    yield db
    db.close()


def test_seed_database(_setup_db):
    db = _setup_db
    count = db.query(ScamNumber).count()
    assert count >= 10


def test_check_number_in_db_known(_setup_db):
    db = _setup_db
    result = scam_database.check_number_in_db(db, "+18002311500")
    assert result is not None
    assert result.caller_name == "Fake Tech Support"


def test_check_number_in_db_unknown(_setup_db):
    db = _setup_db
    result = scam_database.check_number_in_db(db, "+15555555555")
    assert result is None


def test_detect_scam_from_text_tech_support():
    text = "Your computer has a virus. Microsoft says your license has expired."
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is True
    assert scam_type.value == "tech_support"


def test_detect_scam_from_text_lottery():
    text = "Congratulations! You have won the lottery! Claim your prize now!"
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is True
    assert scam_type.value == "lottery"


def test_detect_scam_from_text_government():
    text = "This is the IRS. You owe money and will be arrested if you don't pay now."
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is True
    assert scam_type.value == "government"


def test_detect_scam_from_text_legitimate():
    text = "Hi, just calling to confirm our meeting tomorrow at 3pm."
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is False
    assert confidence < 0.7


def test_detect_scam_known_number(_setup_db):
    db = _setup_db
    is_scam, confidence, scam_type, db_match = scam_database.detect_scam(db, "+18002311500", "")
    assert is_scam is True
    assert db_match is not None


def test_detect_scam_unknown_number_with_text(_setup_db):
    db = _setup_db
    text = "Your social security number has been suspended due to suspicious activity."
    is_scam, confidence, scam_type, db_match = scam_database.detect_scam(db, "+15555555555", text)
    assert is_scam is True
    assert confidence > 0.7
    assert scam_type.value == "government"


def test_add_scam_report(_setup_db):
    db = _setup_db
    before = db.query(ScamReport).count()
    entry = scam_database.add_scam_report(
        db, "+15551234567", "user@example.com", "bank_fraud", "Tried to get my credit card info"
    )
    after = db.query(ScamReport).count()
    assert after == before + 1
    assert entry.phone_number == "+15551234567"
    assert entry.is_blocked is True


def test_add_scam_report_updates_existing(_setup_db):
    db = _setup_db
    entry = scam_database.add_scam_report(db, "+18002311500", "user@example.com", "tech_support", "Extra note")
    assert entry.report_count > 0


def test_create_call_record(_setup_db):
    db = _setup_db
    record = scam_database.create_or_update_call_record(db, "CA_TEST123", "+15551234567", "+12025551234")
    assert record.call_sid == "CA_TEST123"
    assert record.from_number == "+15551234567"


def test_update_call_record(_setup_db):
    db = _setup_db
    scam_database.create_or_update_call_record(db, "CA_UPDATE1", "+15551234567")
    updated = scam_database.update_call_record(
        db, "CA_UPDATE1",
        transcript="Hello there",
        status="completed",
        scam_detected=True,
        scam_confidence=0.95
    )
    assert updated.transcript == "Hello there"
    assert updated.scam_detected is True


def test_create_call_record_idempotent(_setup_db):
    db = _setup_db
    r1 = scam_database.create_or_update_call_record(db, "CA_SAME", "+15551234567")
    r2 = scam_database.create_or_update_call_record(db, "CA_SAME", "+15551234567")
    assert r1.id == r2.id


def test_detect_scam_from_text_bank_fraud():
    text = "This is your bank. Your account has been compromised. Please verify your PIN."
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is True
    assert scam_type.value == "bank_fraud"


def test_detect_scam_from_text_investment():
    text = "Invest in Bitcoin now for guaranteed returns. Limited opportunity!"
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text(text)
    assert is_scam is True
    assert scam_type.value == "investment"


def test_detect_scam_from_empty_text():
    is_scam, confidence, scam_type = scam_database.detect_scam_from_text("")
    assert is_scam is False
    assert confidence == 0.0
