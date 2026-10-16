from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

from ..config import settings

_model: Optional[WhisperModel] = None

def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

def transcribe_audio(file_path: str) -> str:
    model = _get_model()
    if not Path(file_path).exists():
        return ""
    segments, _ = model.transcribe(file_path, beam_size=1, best_of=1)
    return " ".join(seg.text for seg in segments).strip()

async def transcribe_audio_async(file_path: str) -> str:
    return transcribe_audio(file_path)
