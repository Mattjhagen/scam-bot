import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("scambot")

_BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR_STR = str(_BASE_DIR)

load_dotenv(_BASE_DIR / ".env")

@lru_cache()
def get_settings():
    return _Settings()


class _Settings:
    def __init__(self):
        self.BASE_DIR = BASE_DIR_STR

        # Twilio
        self.TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
        self.PUBLIC_HOST = os.getenv("PUBLIC_HOST", "")

        # OpenAI
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        # AWS (for Polly TTS and S3 recording storage)
        self.AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        self.AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
        self.POLLY_VOICE_ID = os.getenv("POLLY_VOICE_ID", "Joanna")
        self.S3_RECORDING_BUCKET = os.getenv("S3_RECORDING_BUCKET", "")

        # Database
        self.DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_BASE_DIR / 'data' / 'scam_bot.db'}")

        # Redis (for background tasks / task queue)
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # TTS
        self.TTS_PROVIDER = os.getenv("TTS_PROVIDER", "kokoro")
        self.ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
        self.ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
        self.KOKORO_VOICE = os.getenv("KOKORO_VOICE", "bm_george")
        self.ENABLE_LOCAL_TTS = os.getenv("ENABLE_LOCAL_TTS", "false").lower() == "true"

        # Test mode (lab only, off by default)
        self.SCAMBOT_TEST_MODE = os.getenv("SCAMBOT_TEST_MODE", "victim")

        # Recording
        self.RECORD_CALLS = os.getenv("RECORD_CALLS", "true").lower() == "true"
        self.RECORDING_DIR = os.getenv("RECORDING_DIR", str(_BASE_DIR / "data" / "recordings"))

        # Notification
        self.SEND_SMS_NOTES = os.getenv("SEND_SMS_NOTES", "true").lower() == "true"
        self.NOTIFICATION_FROM = os.getenv("NOTIFICATION_FROM", "")
        self.OWNER_PHONE = os.getenv("OWNER_PHONE", "")

        # API auth
        self.API_KEY = os.getenv("API_KEY", "")

        # Scam detection
        self.MIN_SCAM_CONFIDENCE = float(os.getenv("MIN_SCAM_CONFIDENCE", "0.7"))
        self.SCAM_REPORT_THRESHOLD = int(os.getenv("SCAM_REPORT_THRESHOLD", "3"))

        # Persona
        self.DEFAULT_PERSONA = os.getenv("DEFAULT_PERSONA", "elderly_cardholder")

        # Recording retention (days: 0 = never delete)
        self.RECORDING_RETENTION_DAYS = int(os.getenv("RECORDING_RETENTION_DAYS", "30"))

        # Environment
        self.ENV = os.getenv("ENV", "development")
        self.DEBUG = os.getenv("DEBUG", "false").lower() == "true"


settings = get_settings()


def validate_startup():
    errors = []
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        errors.append("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
    if not settings.OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY must be set in .env")
    if not settings.PUBLIC_HOST and settings.RECORD_CALLS:
        errors.append("PUBLIC_HOST must be set when RECORD_CALLS=true")
    if not settings.OWNER_PHONE:
        logger.warning("OWNER_PHONE is not set — call notifications will be skipped")
    try:
        float(settings.MIN_SCAM_CONFIDENCE)
    except (TypeError, ValueError):
        errors.append("MIN_SCAM_CONFIDENCE must be a valid float")
    try:
        int(settings.SCAM_REPORT_THRESHOLD)
    except (TypeError, ValueError):
        errors.append("SCAM_REPORT_THRESHOLD must be a valid integer")
    try:
        int(settings.RECORDING_RETENTION_DAYS)
    except (TypeError, ValueError):
        errors.append("RECORDING_RETENTION_DAYS must be a valid integer")
    if errors:
        for error in errors:
            logger.error("[STARTUP] %s", error)
        sys.exit(1)
