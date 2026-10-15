from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc)


class ScamType(str, PyEnum):
    TECH_SUPPORT = "tech_support"
    LOTTERY = "lottery"
    BANK_FRAUD = "bank_fraud"
    ROMANCE = "romance"
    GOVERNMENT = "government"
    BUSINESS_EMAIL = "business_email"
    INVESTMENT = "investment"
    GENERAL = "general"


class CallStatus(str, PyEnum):
    INCOMING = "incoming"
    HANDLED = "handled"
    COMPLETED = "completed"
    FAILED = "failed"


class NotificationStatus(str, PyEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ScamNumber(Base):
    __tablename__ = "scam_numbers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(30), unique=True, index=True, nullable=False)
    scam_type = Column(Enum(ScamType), default=ScamType.GENERAL)
    caller_name = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    confidence = Column(Float, default=1.0)
    is_blocked = Column(Boolean, default=True)
    first_seen = Column(DateTime, default=_utcnow)
    last_seen = Column(DateTime, default=_utcnow)
    report_count = Column(Integer, default=0)
    metadata_json = Column(MutableDict.as_mutable(JSON), default=dict)

    reports = relationship("ScamReport", back_populates="scam_number_rel", cascade="all, delete-orphan")
    call_records = relationship("CallRecord", back_populates="scam_number_rel", cascade="all, delete-orphan")


class ScamReport(Base):
    __tablename__ = "scam_reports"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(30), index=True, nullable=False)
    reported_by = Column(String(200), nullable=True)
    scam_type = Column(Enum(ScamType), default=ScamType.GENERAL)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    is_verified = Column(Boolean, default=False)

    scam_number_rel_id = Column(Integer, ForeignKey("scam_numbers.id"), nullable=True)
    scam_number_rel = relationship("ScamNumber", back_populates="reports")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(30), unique=True, index=True, nullable=False)
    email = Column(String(200), nullable=True)
    name = Column(String(200), nullable=True)
    notification_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class CallRecord(Base):
    __tablename__ = "call_records"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String(100), unique=True, index=True, nullable=False)
    from_number = Column(String(30), index=True, nullable=False)
    to_number = Column(String(30), nullable=True)
    status = Column(Enum(CallStatus), default=CallStatus.INCOMING)
    started_at = Column(DateTime, default=_utcnow)
    ended_at = Column(DateTime, nullable=True)
    recording_url = Column(String(500), nullable=True)
    recording_sid = Column(String(100), nullable=True)
    transcript = Column(Text, nullable=True)
    scam_detected = Column(Boolean, default=False)
    scam_confidence = Column(Float, default=0.0)
    metadata_json = Column(MutableDict.as_mutable(JSON), default=dict)

    scam_number_rel = relationship("ScamNumber", back_populates="call_records")
    scam_number_rel_id = Column(Integer, ForeignKey("scam_numbers.id"), nullable=True)

    user_notes = relationship("UserNote", back_populates="call_record", cascade="all, delete-orphan")


class UserNote(Base):
    __tablename__ = "user_notes"

    id = Column(Integer, primary_key=True, index=True)
    call_record_id = Column(Integer, ForeignKey("call_records.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    call_record = relationship("CallRecord", back_populates="user_notes")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    call_record_id = Column(Integer, ForeignKey("call_records.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    phone_number = Column(String(30), nullable=True)
    channel = Column(String(20), default="sms")
    status = Column(Enum(NotificationStatus), default=NotificationStatus.PENDING)
    content = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
