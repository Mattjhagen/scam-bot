import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
BASE_DIR_STR = str(_BASE_DIR)

load_dotenv(_BASE_DIR / ".env")

@lru_cache()
def get_settings():
    return _Settings()

class _Settings:
    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    PUBLIC_HOST: str = os.getenv("PUBLIC_HOST", "")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # AWS (for Polly TTS and S3 recording storage)
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    POLLY_VOICE_ID: str = os.getenv("POLLY_VOICE_ID", "Joanna")
    S3_RECORDING_BUCKET: str = os.getenv("S3_RECORDING_BUCKET", "")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{_BASE_DIR / 'data' / 'scam_bot.db'}")

    # Redis (for background tasks / task queue)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # TTS
    TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "polly")  # "polly", "gtts", "whisper-tts"
    ENABLE_LOCAL_TTS: bool = os.getenv("ENABLE_LOCAL_TTS", "false").lower() == "true"

    # Recording
    RECORD_CALLS: bool = os.getenv("RECORD_CALLS", "true").lower() == "true"
    RECORDING_DIR: str = os.getenv("RECORDING_DIR", str(_BASE_DIR / "data" / "recordings"))

    # Notification
    SEND_SMS_NOTES: bool = os.getenv("SEND_SMS_NOTES", "true").lower() == "true"
    NOTIFICATION_FROM: str = os.getenv("NOTIFICATION_FROM", "")

    # Scam detection
    MIN_SCAM_CONFIDENCE: float = float(os.getenv("MIN_SCAM_CONFIDENCE", "0.7"))

    # Persona
    DEFAULT_PERSONA: str = os.getenv("DEFAULT_PERSONA", "confused_cia_agent")

    # Environment
    ENV: str = os.getenv("ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

settings = get_settings()
