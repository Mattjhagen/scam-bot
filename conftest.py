import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test_scam_bot.db")
os.environ.setdefault("ENV", "testing")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("SEND_SMS_NOTES", "false")
os.environ.setdefault("RECORD_CALLS", "false")

from src.core.database import init_db, SessionLocal, engine, Base
from src.core import scam_database


def pytest_configure(config):
    Base.metadata.drop_all(bind=engine)
    init_db()
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
