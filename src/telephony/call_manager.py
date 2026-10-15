import os
from pathlib import Path
from typing import Optional

from ..config import settings

try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None


class CallManager:
    def __init__(self):
        self._client: Optional[object] = None
        self._initialized = False

    def _ensure_client(self):
        if not self._initialized:
            if TwilioClient and settings.TWILIO_ACCOUNT_SID:
                self._client = TwilioClient(
                    settings.TWILIO_ACCOUNT_SID,
                    settings.TWILIO_AUTH_TOKEN,
                )
            self._initialized = True

    def get_twilio_client(self):
        self._ensure_client()
        return self._client

    def initiate_call(self, to_number: str, from_number: str = None,
                      url: str = None, status_callback: str = None) -> Optional[str]:
        client = self.get_twilio_client()
        if not client:
            return None

        from_number = from_number or settings.TWILIO_PHONE_NUMBER
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            url=url,
            status_callback=status_callback,
            status_callback_event=["completed", "ringing"],
            record=settings.RECORD_CALLS,
            recording_status_callback=status_callback,
        )
        return call.sid

    def send_sms(self, to_number: str, body: str, from_number: str = None) -> Optional[str]:
        client = self.get_twilio_client()
        if not client:
            return None

        from_number = from_number or settings.NOTIFICATION_FROM or settings.TWILIO_PHONE_NUMBER
        message = client.messages.create(
            to=to_number,
            from_=from_number,
            body=body,
        )
        return message.sid

    def get_recording(self, recording_sid: str) -> Optional[dict]:
        client = self.get_twilio_client()
        if not client:
            return None
        try:
            rec = client.recordings.get(recording_sid)
            return {
                "sid": rec.sid,
                "url": f"{rec.uri.replace('.json', '')}?audio=true" if rec.uri else None,
                "call_sid": rec.call_sid,
                "date_created": rec.date_created.isoformat() if rec.date_created else None,
            }
        except Exception:
            return None

    def download_recording(self, recording_sid: str, output_path: str = None) -> Optional[str]:
        client = self.get_twilio_client()
        if not client:
            return None
        try:
            rec = client.recordings.get(recording_sid)
            uri = rec.uri
            if not uri:
                return None
            api_url = uri.replace(".json", "")
            response = client.request("GET", api_url)
            output_path = output_path or os.path.join(
                settings.RECORDING_DIR, f"{recording_sid}.wav"
            )
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(response.content)
            return output_path
        except Exception:
            return None


call_manager = CallManager()
