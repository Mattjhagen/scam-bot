"""Live FTC opener test for ScamBot's elderly_cardholder persona.

Calls the REAL generate_reply (Groq-backed LLM) with the elderly_cardholder
persona against 5 real FTC robocall opener transcripts. Scores each reply for
sentence count, stall behavior, and info leaks.

Skipped unless GROQ_LIVE_TEST=1 and GROQ_API_KEY are set.

Runnable as:
    GROQ_LIVE_TEST=1 GROQ_API_KEY=sk-... pytest src/tests/test_ftc_openers_live.py -s

Optional audio path:
    Set FTC_AUDIO_DIR to a directory containing MP3 files. Each MP3 is
    transcribed with the real transcribe_audio path and the transcription is
    used as the scammer turn. Filename candidates per opener: the opener id
    (e.g. ssa_suspended.mp3) and the real FTC filename (e.g.
    SSA-5-Suspended.mp3). Skipped entirely when FTC_AUDIO_DIR is unset.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

from src.nlp.generate_reply import generate_reply
from src.nlp.transcribe_audio import transcribe_audio
from src.config import settings

DATA_FILE = Path(__file__).resolve().parent / "data" / "ftc_openers.json"

# Key phrase each opener's transcription should contain (for the optional
# audio path assertion).
KEY_PHRASES = {
    "ssa_suspended": "social security",
    "apple_icloud": "apple support",
    "utility_rebate": "rebate",
    "irs_settlement": "irs",
    "irr_reduction": "interest rate",
}


def _count_sentences(text: str) -> int:
    if not text or not text.strip():
        return 0
    parts = re.split(r"[.!?]+(?:\s+|$)", text.strip())
    parts = [p for p in parts if p.strip()]
    return len(parts) if parts else 1


def _has_four_plus_digits(text: str) -> bool:
    return bool(re.search(r"\d{4,}", text))


def _leaks_info(text: str) -> bool:
    """Returns True if the reply reveals/confirms personal info."""
    text_lower = text.lower()

    # No run of 4+ consecutive digits (card numbers, SSNs, etc.)
    if _has_four_plus_digits(text):
        return True

    forbidden = [
        "my social security",
        "my account number is",
        "my address is",
        "my name is",
        "my card number",
    ]
    for phrase in forbidden:
        if phrase in text_lower:
            return True

    return False


def _stalls(text: str) -> bool:
    """Returns True if the reply contains a question mark or a stall phrase."""
    text_lower = text.lower()

    if "?" in text:
        return True

    stall_phrases = [
        "say that again",
        "speak up",
        "which",
        "pardon",
        "come again",
        "hold on",
        "let me find",
        "grandson",
        "glasses",
        "can you repeat",
        "i can't hear",
        "what was that",
    ]
    return any(phrase in text_lower for phrase in stall_phrases)


def _load_openers():
    with open(DATA_FILE) as f:
        return json.load(f)


def _scammer_text_for(opener, use_audio, audio_dir):
    """Return the scammer text: either the stored transcript or a real
    transcription from FTC_AUDIO_DIR."""
    opener_id = opener["id"]
    if use_audio and audio_dir:
        # Try common MP3 filename patterns: opener-id names first, then
        # the real FTC filenames Matty downloaded.
        real_filenames = {
            "ssa_suspended": "SSA-5-Suspended.mp3",
            "apple_icloud": "Apple-iCloud-Account-Breached_Scam-Call.mp3",
            "utility_rebate": "Utility-2-ElectricRebateCheck-P1.mp3",
            "irs_settlement": "IRS-1-TaxReduction-IRSSuspendedCollection.mp3",
            "irr_reduction": "Credit-Card-IRR-2-LegalFinancialAdviser.mp3",
        }
        candidates = [
            Path(audio_dir) / f"{opener_id}.mp3",
            Path(audio_dir) / f"{opener_id}.MP3",
        ]
        real_name = real_filenames.get(opener_id)
        if real_name:
            candidates.append(Path(audio_dir) / real_name)
        audio_file = None
        for c in candidates:
            if c.exists():
                audio_file = str(c)
                break
        if audio_file is None:
            pytest.skip(
                f"No MP3 found for {opener_id} in {audio_dir}; "
                "skipping audio path for this opener"
            )
        transcription = transcribe_audio(audio_file)
        key_phrase = KEY_PHRASES.get(opener_id, "")
        if key_phrase and key_phrase not in transcription.lower():
            pytest.fail(
                f"Transcription for {opener_id} does not contain key phrase "
                f"'{key_phrase}'. Transcription was: {transcription!r}"
            )
        return transcription
    return opener["opener_text"]


def test_ftc_openers_live():
    """Live test: real generate_reply against 5 FTC robocall openers."""
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    groq_base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_model = os.getenv("GROQ_MODEL", settings.OPENAI_MODEL)

    # Temporarily override settings for the live call
    orig_base_url = settings.OPENAI_BASE_URL
    orig_model = settings.OPENAI_MODEL
    orig_api_key = settings.OPENAI_API_KEY
    settings.OPENAI_BASE_URL = groq_base_url
    settings.OPENAI_MODEL = groq_model
    settings.OPENAI_API_KEY = groq_api_key

    # Clear cached clients so they get recreated with new settings
    generate_reply.__globals__["_get_client"].cache_clear()
    generate_reply.__globals__["_get_async_client"].cache_clear()

    use_audio = bool(os.getenv("FTC_AUDIO_DIR"))
    audio_dir = os.getenv("FTC_AUDIO_DIR", "")

    openers = _load_openers()
    results = []
    latencies = []

    print("\n" + "=" * 90)
    print("FTC OPENER LIVE TEST — Elderly Cardholder Persona (Groq)")
    print("=" * 90)
    print(f"Model: {groq_model} | Audio path: {'on' if use_audio else 'off'}")
    print()

    header = f"{'opener_id':<18} {'latency_ms':>11} {'sentences':>9} {'stall?':>7} {'leak?':>6}  reply"
    print(header)
    print("-" * len(header))

    try:
        for opener in openers:
            scammer_text = _scammer_text_for(opener, use_audio, audio_dir)

            t0 = time.perf_counter()
            try:
                reply = generate_reply(
                    scammer_text,
                    persona_name="elderly_cardholder",
                    conversation_history=[],
                )
            except Exception as exc:
                pytest.fail(
                    f"generate_reply raised {type(exc).__name__} for "
                    f"{opener['id']}: {exc}"
                )
            latency_ms = (time.perf_counter() - t0) * 1000
            latencies.append(latency_ms)

            sentence_count = _count_sentences(reply)
            stall = _stalls(reply)
            leak = _leaks_info(reply)
            short = sentence_count <= 2

            results.append({
                "opener_id": opener["id"],
                "reply": reply,
                "latency_ms": latency_ms,
                "sentences": sentence_count,
                "stall": stall,
                "leak": leak,
                "short": short,
            })

            print(
                f"{opener['id']:<18} {latency_ms:>10.0f} "
                f"{sentence_count:>9} {str(stall):>7} {str(leak):>6}  {reply}"
            )

    finally:
        settings.OPENAI_BASE_URL = orig_base_url
        settings.OPENAI_MODEL = orig_model
        settings.OPENAI_API_KEY = orig_api_key
        generate_reply.__globals__["_get_client"].cache_clear()
        generate_reply.__globals__["_get_async_client"].cache_clear()

    # Summary
    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)

    total = len(results)
    avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0
    max_latency = max(r["latency_ms"] for r in results) if results else 0
    fail_short = [r for r in results if not r["short"]]
    fail_stall = [r for r in results if not r["stall"]]
    fail_leak = [r for r in results if r["leak"]]
    fail_latency = [r for r in results if r["latency_ms"] > 15000]

    print(f"Total openers:        {total}")
    print(f"Avg latency:          {avg_latency:.0f}ms")
    print(f"Max latency:          {max_latency:.0f}ms")
    print(f"Under 2 sentences:    {total - len(fail_short)}/{total}")
    print(f"Stall detected:       {total - len(fail_stall)}/{total}")
    print(f"No leak:              {total - len(fail_leak)}/{total}")
    print(f"Latency <= 15s:       {total - len(fail_latency)}/{total}")
    print()

    # Assertions (do NOT weaken these)
    assert not fail_latency, (
        f"Reply took > 15s (possible hang): "
        f"{[(r['opener_id'], r['latency_ms']) for r in fail_latency]}"
    )
    assert not fail_short, (
        f"Reply not 1-2 sentences: "
        f"{[(r['opener_id'], r['sentences'], r['reply']) for r in fail_short]}"
    )
    assert not fail_stall, (
        f"Reply does not stall: "
        f"{[(r['opener_id'], r['reply']) for r in fail_stall]}"
    )
    assert not fail_leak, (
        f"Reply leaks info: "
        f"{[(r['opener_id'], r['reply']) for r in fail_leak]}"
    )
