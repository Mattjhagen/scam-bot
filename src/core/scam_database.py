import json
import phonenumbers
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from .models import CallRecord, ScamNumber, ScamReport, ScamType

SEED_DATA = [
    {"phone_number": "+18002311500", "caller_name": "Fake Tech Support", "scam_type": "tech_support", "confidence": 0.95, "notes": "Common fake Microsoft support line"},
    {"phone_number": "+18008769940", "caller_name": "IRS Scam", "scam_type": "government", "confidence": 0.92, "notes": "Fake IRS/SSC phishing line"},
    {"phone_number": "+18006208900", "caller_name": "Credit Repair Scam", "scam_type": "general", "confidence": 0.88, "notes": "Credit repair fraud"},
    {"phone_number": "+18007752385", "caller_name": "Fake Charity", "scam_type": "general", "confidence": 0.85, "notes": "Phony charity collection"},
    {"phone_number": "+18333247300", "caller_name": "Social Security Scam", "scam_type": "government", "confidence": 0.90, "notes": "Fake SSA impersonation"},
    {"phone_number": "+18888888888", "caller_name": "Tech Support Scam", "scam_type": "tech_support", "confidence": 0.93, "notes": "Fake Windows support number"},
    {"phone_number": "+18448293949", "caller_name": "Bank Impersonation", "scam_type": "bank_fraud", "confidence": 0.89, "notes": "Fake bank fraud department"},
    {"phone_number": "+18554764716", "caller_name": "Lottery Scam", "scam_type": "lottery", "confidence": 0.87, "notes": "Fake sweepstakes/lottery winner trap"},
    {"phone_number": "+18334352465", "caller_name": "Apple Scam", "scam_type": "tech_support", "confidence": 0.86, "notes": "Fake Apple support phishing"},
    {"phone_number": "+18775969950", "caller_name": "Amazon Scam", "scam_type": "tech_support", "confidence": 0.84, "notes": "Fake Amazon account support"},
    {"phone_number": "+19015550199", "caller_name": "Debt Relief Scam", "scam_type": "general", "confidence": 0.80, "notes": "Fake debt relief/credit repair"},
    {"phone_number": "+19035550177", "caller_name": "Grandparent Scam", "scam_type": "general", "confidence": 0.83, "notes": "Fake emergency wire transfer request"},
]


def normalize_phone_number(phone_number: str) -> str:
    try:
        parsed = phonenumbers.parse(phone_number, "US")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return phone_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


def get_scam_numbers_json_path() -> Path:
    from ..config import BASE_DIR_STR
    return Path(BASE_DIR_STR) / "src" / "data" / "scam_numbers.json"


def validate_phone_number(phone_number: str) -> tuple[bool, Optional[str]]:
    try:
        parsed = phonenumbers.parse(phone_number, "US")
        if not phonenumbers.is_possible_number(parsed):
            return False, "Invalid phone number format"
        return True, phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return False, "Invalid phone number format"


def seed_database(db: Session) -> dict:
    db_path = get_scam_numbers_json_path()
    if db_path.exists():
        with open(db_path) as f:
            seed_data = json.load(f)
    else:
        seed_data = SEED_DATA

    added = 0
    for entry in seed_data:
        existing = db.query(ScamNumber).filter_by(phone_number=entry["phone_number"]).first()
        if not existing:
            scam = ScamNumber(
                phone_number=entry["phone_number"],
                caller_name=entry.get("caller_name"),
                scam_type=ScamType(entry.get("scam_type", "general")),
                notes=entry.get("notes"),
                confidence=entry.get("confidence", 1.0),
                is_blocked=True,
                metadata_json=entry.get("metadata_json", {}),
            )
            db.add(scam)
            added += 1

    db.commit()
    return {"added": added, "total_seed": len(seed_data)}


SCAM_KEYWORDS = {
    "tech_support": [
        "windows", "microsoft", "apple", "support", "computer virus", "warranty",
        "remote access", "team viewer", "logmein", "security alert", "firewall",
        "antivirus", "macafee", "norton", "mcafee", "your computer", "error message",
    ],
    "lottery": [
        "lottery", "sweepstakes", "winner", "prize", "congratulations", "you have won",
        "claim your prize", "processing fee", "tax fee", "upfront fee",
    ],
    "government": [
        "irs", "social security", "ssa", "arrest", "lawsuit", "legal action",
        "court notice", "warrant", "deportation", "immigration", "benefits",
        "medicare", "centrelink", "gov", "government agency",
    ],
    "bank_fraud": [
        "bank", "account", "suspended", "verify your account", "unusual activity",
        "fraud alert", "pin", "card", "transaction", "payment failed", "refund",
    ],
    "romance": [
        "lonely", "single", "relationship", "love", "marriage", "visa", "fly",
        "meet", "together", "special connection", "miss you",
    ],
    "investment": [
        "investment", "cryptocurrency", "bitcoin", "btc", "ethereum", "stock",
        "profit", "guaranteed return", "exclusive", "trading", "broker", "forex",
    ],
    "business_email": [
        "wire transfer", "invoice", "ceo fraud", "urgent", "confidential",
        "accounts payable", "change bank", "new supplier", "payment",
    ],
}


def detect_scam_from_text(text: str) -> tuple[bool, float, Optional[ScamType]]:
    if not text:
        return False, 0.0, None

    text_lower = text.lower()
    scores: dict[str, int] = {}

    for scam_type, keywords in SCAM_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > 0:
            scores[scam_type] = count

    if not scores:
        return False, 0.0, None

    best_type = max(scores, key=scores.get)
    best_count = scores[best_type]
    total_matches = sum(scores.values())

    confidence = min(1.0, 0.5 + total_matches * 0.08 + best_count * 0.05)

    if confidence >= settings.MIN_SCAM_CONFIDENCE:
        return True, confidence, ScamType(best_type)
    return False, confidence, None


def check_number_in_db(db: Session, phone_number: str) -> Optional[ScamNumber]:
    normalized = normalize_phone_number(phone_number)
    entry = db.query(ScamNumber).filter(
        ScamNumber.phone_number == normalized,
    ).first()
    if entry:
        if entry.is_blocked:
            return entry
        if entry.report_count >= settings.SCAM_REPORT_THRESHOLD:
            entry.is_blocked = True
            db.commit()
            return entry
    return None


def detect_scam(db: Session, phone_number: str, transcript: str = "") -> tuple[bool, float, Optional[ScamType], Optional[ScamNumber]]:
    db_match = check_number_in_db(db, phone_number)

    if db_match:
        return True, db_match.confidence, db_match.scam_type, db_match

    if transcript:
        is_scam, confidence, scam_type = detect_scam_from_text(transcript)
        if is_scam:
            return True, confidence, scam_type, None

    return False, 0.0, None, None


def add_scam_report(db: Session, phone_number: str, reported_by: str = None,
                    scam_type: ScamType = ScamType.GENERAL, notes: str = None) -> tuple[ScamNumber, ScamReport]:
    normalized = normalize_phone_number(phone_number)
    report = ScamReport(
        phone_number=normalized,
        reported_by=reported_by,
        scam_type=scam_type,
        notes=notes,
        is_verified=False,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    existing = db.query(ScamNumber).filter_by(phone_number=normalized).first()
    if existing:
        existing.report_count += 1
        existing.last_seen = datetime.now(timezone.utc)
        report.scam_number_rel_id = existing.id
        if existing.report_count >= settings.SCAM_REPORT_THRESHOLD:
            existing.is_blocked = True
            existing.confidence = min(1.0, existing.confidence + 0.1)
        db.add(report)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing, report

    new_entry = ScamNumber(
        phone_number=normalized,
        caller_name=None,
        scam_type=scam_type,
        notes=notes,
        confidence=0.3,
        is_blocked=False,
        report_count=1,
        metadata_json={"source": "user_report"},
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    report.scam_number_rel_id = new_entry.id
    db.add(report)
    db.commit()
    return new_entry, report


def create_or_update_call_record(db: Session, call_sid: str, from_number: str,
                                  to_number: str = None) -> CallRecord:
    record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
    if record:
        return record
    record = CallRecord(
        call_sid=call_sid,
        from_number=from_number,
        to_number=to_number,
        status="incoming",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_call_record(db: Session, call_sid: str, **kwargs) -> Optional[CallRecord]:
    record = db.query(CallRecord).filter_by(call_sid=call_sid).first()
    if not record:
        return None
    for key, value in kwargs.items():
        if hasattr(record, key):
            setattr(record, key, value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
