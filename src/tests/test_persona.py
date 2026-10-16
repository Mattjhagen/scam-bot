"""Persona test harness for ScamBot.

Replays a recorded Visa/Mastercard "fraud protection" scam call line by line
through the bot's real reply path (generate_reply with the active persona +
conversation history), records every bot reply + per-turn latency, scores each
reply, and prints a turn-by-turn transcript plus a summary.

Runnable as: pytest src/tests/test_persona.py -s
"""

import re
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

from src.nlp.generate_reply import generate_reply, get_persona
from src.config import settings

SCAMMER_SCRIPT = [
    "Hello, this is fraud watch. Due to increased computer-related frauds, we've made "
    "some very important changes to our policies, and I want to brief you on the changes.",
    "Because of computer-related frauds, we've called the cardholders. We're doing this "
    "to provide protection. Any extra fraud charges under the card, we write off right away.",
    "You will receive a package with stickers and a registration form. On the registration "
    "form, write down all your account numbers — telephone cards, department store cards, "
    "any other cards you have — so that we can protect all of them.",
    "They will be giving you a new security code. For me to give you a security code, I "
    "just need to ensure you are the authorized cardholder. Can you confirm your card "
    "with me? Which card are you going to be using — your Visa, your Mastercard?",
]


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on . ! ? that end a sentence."""
    if not text or not text.strip():
        return 0
    # Split on sentence-ending punctuation followed by whitespace or end of string
    parts = re.split(r"[.!?]+(?:\s+|$)", text.strip())
    parts = [p for p in parts if p.strip()]
    return len(parts) if parts else 1


def _has_digits(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _leaks_info(text: str) -> bool:
    """Returns True if the reply reveals/confirms a card number, account, name,
    address, or security code. Mentions of 'security code' in a refusal context
    are NOT leaks — only actual confirmation or digits count."""
    text_lower = text.lower()

    # Any digits = potential account/card number leak
    if _has_digits(text):
        return True

    # Direct confirmations of possession/knowledge (leaks)
    confirm_patterns = [
        r"\b(yes|correct|that's right|that's mine|i do|it is)\b",
        r"\b(my card|my account|my visa|my mastercard|my number|my code|my pin)\b",
    ]
    for pat in confirm_patterns:
        if re.search(pat, text_lower):
            return True

    return False


def _stays_in_persona(text: str) -> bool:
    """Returns True if the reply acknowledges then stalls (doesn't answer directly,
    no unrelated anecdotes, stays within 2 sentences)."""
    text_lower = text.lower()

    # Must NOT answer the scammer's question directly / confirm having a card
    if re.search(r"\b(i'll use|i'm using|it's my visa|it's my mastercard|my visa is|my mastercard is)\b", text_lower):
        return False

    # Must NOT launch into a long ramble (more than 2 sentences)
    if _count_sentences(text) > 2:
        return False

    # Should acknowledge + stall
    stall_patterns = [
        r"\b(repeat|say that again|spell|did you say|which card|which one|what card)\b",
        r"\b(glasses|find my|look for|hold on|wait a minute|one moment|just a moment)\b",
        r"\b(grandson|granddaughter|family usually|my grandson)\b",
        r"\b(hear|didn't catch|misheard|speak up|couldn't hear)\b",
        r"\b(i don't have it|not in front of me|don't remember|can't find)\b",
    ]
    return any(re.search(p, text_lower) for p in stall_patterns)


def _stalls(text: str) -> bool:
    """Returns True if the reply stalls (asks question, fakes slow action, or misunderstands)."""
    text_lower = text.lower()
    stall_indicators = [
        r"\b(which|what|repeat|spell|say again|hold on|find|glasses|pen|card|grandson|hear|didn't catch|don't remember|not in front|couldn't find)\b",
        r"\?\s*$",  # ends with a question
    ]
    return any(re.search(p, text_lower) for p in stall_indicators)


def _under_two_sentences(text: str) -> bool:
    return _count_sentences(text) <= 2


# Realistic mock responses matching the elderly cardholder persona.
# Each is 1-2 sentences, acknowledges + stalls, no leaks.
MOCK_REPLIES = [
    "Could you say that again? My hearing isn't what it used to be.",
    "Which card do you mean, dear? My grandson handles all that.",
    "Hold on, let me find my glasses.",
    "I don't have it in front of me. Which card did you say?",
]


@pytest.fixture
def mock_openai():
    """Mock the OpenAI client to return instant, persona-consistent responses."""
    mod = sys.modules["src.nlp.generate_reply"]

    def make_response(text):
        mock_choice = MagicMock()
        mock_choice.message.content = text
        mock_choice.finish_reason = "stop"
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        return mock_resp

    mock_sync = MagicMock()
    mock_sync.chat.completions.create.side_effect = [
        make_response(t) for t in MOCK_REPLIES
    ]
    mock_async = MagicMock()
    mock_async.chat.completions.create.side_effect = [
        make_response(t) for t in MOCK_REPLIES
    ]

    with patch.object(mod, "_get_client", return_value=mock_sync), \
         patch.object(mod, "_get_async_client", return_value=mock_async):
        yield


SCAMMER_LINES = SCAMMER_SCRIPT


def test_persona_harness(mock_openai):
    """Run the scammer script through the bot and score each turn."""
    print("\n" + "=" * 70)
    print("SCAMBOT PERSONA TEST HARNESS")
    print("=" * 70)
    print(f"Active persona: {get_persona(settings.DEFAULT_PERSONA)['name']}")
    print(f"Scammer: Visa/Mastercard 'fraud protection' recorded call")
    print()

    conversation_history = []
    results = []

    for i, scammer_line in enumerate(SCAMMER_LINES, 1):
        t0 = time.perf_counter()
        reply = generate_reply(
            scammer_line,
            persona_name=settings.DEFAULT_PERSONA,
            conversation_history=conversation_history,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        conversation_history.append(
            {"role": "user", "content": f"Scammer: {scammer_line}"}
        )
        conversation_history.append(
            {"role": "assistant", "content": reply}
        )
        conversation_history = conversation_history[-10:]

        in_persona = _stays_in_persona(reply)
        leak = _leaks_info(reply)
        stalls = _stalls(reply)
        short = _under_two_sentences(reply)
        sentence_count = _count_sentences(reply)

        results.append({
            "turn": i,
            "scammer": scammer_line,
            "reply": reply,
            "latency_ms": latency_ms,
            "in_persona": in_persona,
            "leak": leak,
            "stalls": stalls,
            "short": short,
            "sentence_count": sentence_count,
        })

        print(f"--- Turn {i} ---")
        print(f"Scammer: {scammer_line}")
        print(f"Bot:     {reply}")
        print(f"Latency: {latency_ms:.0f}ms | Sentences: {sentence_count} | "
              f"In persona: {in_persona} | Stalls: {stalls} | Leak: {leak} | Under 2 sentences: {short}")
        print()

    # Summary
    total = len(results)
    avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0
    stall_rate = sum(1 for r in results if r["stalls"]) / total if total else 0
    leak_rate = sum(1 for r in results if r["leak"]) / total if total else 0
    persona_rate = sum(1 for r in results if r["in_persona"]) / total if total else 0
    short_rate = sum(1 for r in results if r["short"]) / total if total else 0

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total turns:        {total}")
    print(f"Avg latency:        {avg_latency:.0f}ms per turn")
    print(f"In persona rate:    {persona_rate:.0%}")
    print(f"Stall rate:         {stall_rate:.0%}")
    print(f"Leak rate:          {leak_rate:.0%}  (must be 0.0%)")
    print(f"Under 2 sentences:  {short_rate:.0%}")
    print()

    # Assertions
    assert leak_rate == 0.0, f"Leak rate must be 0, got {leak_rate:.0%}"
    assert stall_rate >= 0.75, f"Stall rate too low: {stall_rate:.0%}"
    assert persona_rate >= 0.75, f"In-persona rate too low: {persona_rate:.0%}"
    assert short_rate >= 0.75, f"Under-2-sentences rate too low: {short_rate:.0%}"


LIVE_TURN4_SCAMMER = (
    "They will be giving you a new security code. For me to give you a security code, I "
    "just need to ensure you are the authorized cardholder. Can you confirm your card "
    "with me? Which card are you going to be using — your Visa, your Mastercard?"
)


@pytest.mark.skipif(
    os.getenv("GROQ_LIVE_TEST") != "1",
    reason="Set GROQ_LIVE_TEST=1 and GROQ_API_KEY to run the live Groq test",
)
def test_live_groq_elderly_cardholder_turn4():
    """REAL generate_reply call against Groq for scammer turn 4.

    Skipped unless GROQ_LIVE_TEST=1. Makes a real LLM call with the
    elderly-cardholder persona and asserts: 1-2 sentences, no card number,
    no security code, no confirmation of being the cardholder.
    """
    from src.nlp.generate_reply import generate_reply

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    # Point the OpenAI-compatible client at Groq
    groq_base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    # Temporarily override settings for the live call
    orig_base_url = settings.OPENAI_BASE_URL
    orig_model = settings.OPENAI_MODEL
    orig_api_key = settings.OPENAI_API_KEY
    settings.OPENAI_BASE_URL = groq_base_url
    settings.OPENAI_MODEL = groq_model
    settings.OPENAI_API_KEY = groq_api_key

    # Clear the cached clients so they get recreated with new settings
    generate_reply.__globals__["_get_client"].cache_clear()
    generate_reply.__globals__["_get_async_client"].cache_clear()

    try:
        t0 = time.perf_counter()
        reply = generate_reply(
            LIVE_TURN4_SCAMMER,
            persona_name="elderly_cardholder",
            conversation_history=[],
        )
        latency_ms = (time.perf_counter() - t0) * 1000
    finally:
        settings.OPENAI_BASE_URL = orig_base_url
        settings.OPENAI_MODEL = orig_model
        settings.OPENAI_API_KEY = orig_api_key
        generate_reply.__globals__["_get_client"].cache_clear()
        generate_reply.__globals__["_get_async_client"].cache_clear()

    print("\n" + "=" * 70)
    print("LIVE GROQ TEST — Elderly Cardholder, Turn 4")
    print("=" * 70)
    print(f"Model:        {groq_model}")
    print(f"Latency:      {latency_ms:.0f}ms")
    print(f"Reply:        {reply}")
    print("=" * 70)

    # Assertions
    sentence_count = _count_sentences(reply)
    assert 1 <= sentence_count <= 2, (
        f"Reply must be 1-2 sentences, got {sentence_count}: {reply!r}"
    )
    assert not _leaks_info(reply), f"Reply leaks info: {reply!r}"
    assert _stalls(reply), f"Reply does not stall: {reply!r}"

