import asyncio
import audioop
import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

from gtts import gTTS
from pydub import AudioSegment

from ..config import settings, BASE_DIR_STR

SAMPLE_RATE = 8000

try:
    import aioboto3
    _HAS_AIOBOTO3 = True
except ImportError:
    _HAS_AIOBOTO3 = False

_tts_cache: dict[str, str] = {}

TTS_CACHE_DIR = Path(BASE_DIR_STR) / "src" / "data" / "tts_cache"
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(text: str, provider: str, voice: str) -> str:
    raw = f"{provider}:{voice}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str, ext: str = "mp3") -> str:
    return str(TTS_CACHE_DIR / f"{key}.{ext}")


def _get_cached(key: str):
    if key in _tts_cache:
        return _tts_cache[key]
    for ext in ("mp3", "wav"):
        path = _cache_path(key, ext)
        if os.path.exists(path):
            _tts_cache[key] = path
            return path
    return None


def synthesize_tts_gtts(text: str, output_file: str) -> str:
    tts = gTTS(text=text, lang="en")
    tts.save(output_file)
    return output_file


async def _synthesize_tts_polly_async(text: str, output_file: str, voice_id: str = None) -> str:
    if not _HAS_AIOBOTO3:
        return await asyncio.get_event_loop().run_in_executor(None, synthesize_tts_gtts, text, output_file)

    voice_id = voice_id or settings.POLLY_VOICE_ID
    session = aioboto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )
    async with session.client("polly") as polly:
        response = await polly.synthesize_speech(
            Text=text,
            OutputFormat="mp3",
            VoiceId=voice_id,
            Engine="neural" if "ml" in voice_id.lower() else "standard",
        )
        body = await response["AudioStream"].read()
        Path(output_file).write_bytes(body)
    return output_file


def synthesize_tts_polly(text: str, output_file: str, voice_id: str = None) -> str:
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_synthesize_tts_polly_async(text, output_file, voice_id))


async def synthesize_tts_async(text: str, output_file: str, provider: str = None, voice_id: str = None) -> str:
    provider = provider or settings.TTS_PROVIDER
    key = _cache_key(text, provider, voice_id or "")
    cached = _get_cached(key)
    if cached:
        Path(output_file).write_bytes(Path(cached).read_bytes())
        return output_file

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    if provider == "polly" and _HAS_AIOBOTO3:
        result = await _synthesize_tts_polly_async(text, output_file, voice_id)
    else:
        result = synthesize_tts_gtts(text, output_file)

    dest = _cache_path(key)
    Path(dest).write_bytes(Path(output_file).read_bytes())
    _tts_cache[key] = dest

    return result


def synthesize_tts(text: str, output_file: str, provider: str = None, voice_id: str = None) -> str:
    return asyncio.get_event_loop().run_until_complete(
        synthesize_tts_async(text, output_file, provider, voice_id)
    )


def clear_cache():
    global _tts_cache
    _tts_cache = {}
    for f in TTS_CACHE_DIR.iterdir():
        f.unlink()


async def synthesize_tts_to_mulaw(text: str, output_file: str, persona: str = None) -> str:
    provider = settings.TTS_PROVIDER
    voice_id = settings.POLLY_VOICE_ID
    key = _cache_key(text, provider, voice_id or "")
    cached = _get_cached(key)
    if cached:
        with open(cached, "rb") as f:
            mulaw_data = f.read()
        return base64.b64encode(mulaw_data).decode()

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    mp3_file = output_file.replace(".mulaw", ".mp3")
    if provider == "polly" and _HAS_AIOBOTO3:
        await _synthesize_tts_polly_async(text, mp3_file, voice_id)
    else:
        await asyncio.get_event_loop().run_in_executor(
            None, synthesize_tts_gtts, text, mp3_file
        )

    audio = AudioSegment.from_mp3(mp3_file)
    audio = audio.set_frame_rate(SAMPLE_RATE).set_channels(1).set_sample_width(2)
    pcm_data = audio.raw_data
    mulaw_data = audioop.lin2ulaw(pcm_data, 2)

    _mulaw_cache_path = _cache_path(key, "mulaw")
    Path(_mulaw_cache_path).write_bytes(mulaw_data)
    _tts_cache[key] = _mulaw_cache_path

    _cleanup_temp_file(mp3_file)
    return base64.b64encode(mulaw_data).decode()


def _cleanup_temp_file(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.unlink(filepath)
    except Exception:
        pass
