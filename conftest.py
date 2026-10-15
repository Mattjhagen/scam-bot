import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_scam_bot.db")
os.environ.setdefault("ENV", "testing")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SEND_SMS_NOTES", "false")
os.environ.setdefault("RECORD_CALLS", "false")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_twilio_token")


def _ensure_test_dirs():
    data_dir = Path(os.environ["DATABASE_URL"].replace("sqlite:///", ""))
    data_dir.parent.mkdir(parents=True, exist_ok=True)


_ensure_test_dirs()

from src.core.database import init_db, SessionLocal, engine, Base
from src.core import scam_database


def pytest_configure(config):
    init_db()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        scam_database.seed_database(db)
    finally:
        db.close()


def pytest_runtest_teardown(item, nextitem):
    from src.core.models import User, CallRecord, ScamReport, ScamNumber, Notification, UserNote
    db = SessionLocal()
    try:
        db.query(UserNote).delete()
        db.query(Notification).delete()
        db.query(CallRecord).delete()
        db.query(ScamReport).delete()
        db.query(User).delete()
        db.query(ScamNumber).delete()
        db.commit()
        scam_database.seed_database(db)
        db.commit()
    finally:
        db.close()
