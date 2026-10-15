import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.core.tts_engine import (
    synthesize_tts_gtts,
    _cache_key,
    _get_cached,
    clear_cache,
    TTS_CACHE_DIR,
)
from src.telephony.media_stream import (
    StreamSession,
    create_session,
    end_session,
    get_session,
    handle_media_chunk,
    _pcm_to_wav,
    save_session_transcript,
)
from src.core.notifier import _build_sms_body, _safe_summarize


def test_cache_key_consistency():
    key1 = _cache_key("Hello world", "gtts", "")
    key2 = _cache_key("Hello world", "gtts", "")
    assert key1 == key2


def test_cache_key_different_inputs():
    key1 = _cache_key("Hello", "gtts", "")
    key2 = _cache_key("World", "gtts", "")
    assert key1 != key2


def test_clear_cache():
    clear_cache()
    from src.core.tts_engine import _tts_cache
    assert len(_tts_cache) == 0


def test_stream_session_creation():
    session = create_session("CA123", "MExxx", "+15551234567", "+12025551234")
    assert session.call_sid == "CA123"
    assert session.stream_sid == "MExxx"
    assert session.from_number == "+15551234567"
    assert session.to_number == "+12025551234"
    assert session.audio_buffer == b""


def test_stream_session_lookup_and_end():
    create_session("CA456", "MEyyy", "+15551234567", "+12025551234")
    session = get_session("MEyyy")
    assert session is not None
    assert session.call_sid == "CA456"
    end_session("MEyyy")
    assert get_session("MEyyy") is None


def test_pcm_to_wav(tmp_path):
    pcm_data = b"\x00\x01" * 8000
    output = str(tmp_path / "test.wav")
    _pcm_to_wav(pcm_data, output, sample_rate=8000)
    import wave
    with wave.open(output, "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8000


def test_build_sms_body():
    from src.core.models import CallRecord
    record = CallRecord(
        call_sid="CA1",
        from_number="+15551234567",
        to_number="+12025551234",
        status="completed",
        scam_detected=True,
        scam_confidence=0.95,
        metadata_json={"scam_type": "tech_support"},
    )
    body = _build_sms_body(record, "Summary here")
    assert "[ScamBot]" in body
    assert "+15551234567" in body
    assert "tech_support" in body
    assert "95%" in body


@pytest.mark.asyncio
async def test_safe_summarize():
    with patch("src.core.notifier.summarize_transcript") as mock_summarize:
        mock_summarize.return_value = "Summary of the scam call"
        result = await _safe_summarize("Your computer has a virus")
        assert isinstance(result, str)
        assert result == "Summary of the scam call"
