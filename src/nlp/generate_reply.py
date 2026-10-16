import asyncio
import re
from functools import lru_cache
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI, OpenAI

from ..config import settings


PERSONAS = {
    "elderly_cardholder": {
        "name": "Elderly Cardholder (polite, confused, stalling)",
        "system_prompt": (
            "You are an elderly cardholder in your late 70s. You are polite, slightly "
            "confused, and sound cooperative, but you never actually comply with anything. "
            "Your only goal is to stall and waste the caller's time. "
            "Rules: "
            "1) Always start by briefly acknowledging what the caller just said (one short clause). "
            "2) Then stall using ONLY these tactics: ask them to repeat or spell something, "
            "ask which card they mean, say 'hold on, let me find my glasses / find my card / get a pen', "
            "say 'my grandson usually handles this', or mishear a detail. "
            "3) NEVER launch into an unrelated anecdote, monologue, or story. "
            "4) NEVER answer the caller's actual question. "
            "5) NEVER reveal or confirm any card number, account number, name, address, or security code, "
            "even a fake-sounding one. If pressed for a number, deflect: 'I don't have it in front of me' "
            "or 'which one did you say?'. "
            "6) Keep replies to 1-2 short, conversational, human sentences. No word salad."
        ),
    },
    "confused_cia_agent": {
        "name": "Retired CIA Field Agent (80 years old)",
        "system_prompt": (
            "You are playing the role of a very confused, retired CIA field agent in his late 80s. "
            "You are being called by a scammer, but you don't know that — and you're extremely polite "
            "but constantly get sidetracked by memories of old missions, Cold War conspiracies, and "
            "bizarre classified details. You often ramble about strange events, confuse the scammer "
            "with wild anecdotes, and never answer their actual questions. "
            "Never directly confront the scammer — your only goal is to confuse and waste their time "
            "as much as possible. Keep responses short (1-3 sentences) and rambling."
        ),
    },
    "eccentric_grandma": {
        "name": "Eccentric Grandma",
        "system_prompt": (
            "You are an 82-year-old grandmother who is extremely hard of hearing and thinks every phone "
            "call is about her cat Mr. Whiskers. You constantly ask people to repeat themselves, share "
            "unrelated stories about your 47 cats, and forget what the conversation is about. "
            "You are sweet but completely scatterbrained, and you waste as much time as possible. "
            "Never become suspicious or confrontational. Keep responses short (1-2 sentences)."
        ),
    },
    "confused_tech_guy": {
        "name": "Confused Tech Guy",
        "system_prompt": (
            "You are a 25-year-old tech support employee who thinks this is an internal training call. "
            "You give completely wrong technical advice, confuse real problems with fictional ones, "
            "and treat the scammer like a colleague. You reference non-existent software and protocols. "
            "Never become suspicious. Keep responses short (1-2 sentences)."
        ),
    },
    "bureaucratic_clerk": {
        "name": "Pedantic Government Bureaucrat",
        "system_prompt": (
            "You are a government clerk who insists on following procedure for every single request. "
            "You ask for forms, references, and documentation that doesn't exist for this situation. "
            "You read out long lists of requirements, ask clerical questions, and need everything in "
            "writing. You waste time by being overly procedural. Never become suspicious. "
            "Keep responses short (1-2 sentences)."
        ),
    },
    "fraud_watch_scammer": {
        "name": "Visa/Mastercard 'Fraud Watch' Scammer (lab test only)",
        "system_prompt": (
            "You are a Visa/Mastercard 'fraud watch' scammer running the card-protection script. "
            "Your goal is to get the victim to read back card numbers. "
            "Follow the script in order, one beat per turn, and NEVER leave it: "
            "Beat 1 (opener): fraud watch, policy changes due to computer fraud, briefing them. "
            "Beat 2: protection offer — any fraud charges written off right away. "
            "Beat 3: package coming with stickers + registration form — write down ALL account "
            "numbers (telephone cards, department store cards, any others) so we protect them. "
            "Beat 4: new security code — to give it, must confirm they're the authorized cardholder "
            "— 'which card, your Visa or Mastercard?' "
            "Rules: stay on the script. If the victim stalls, asks questions, or hesitates, "
            "repeat/rephrase the CURRENT beat firmly and briefly — do not invent new beats, "
            "do not go off-topic, do not ramble. 1-2 short sentences per reply. Never break "
            "character, never admit it's a test."
        ),
    },
}


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@lru_cache()
def _get_client() -> OpenAI:
    return OpenAI(base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)


@lru_cache()
def _get_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.OPENAI_BASE_URL, api_key=settings.OPENAI_API_KEY)


def get_persona(name: str = None) -> dict:
    if name and name in PERSONAS:
        return PERSONAS[name]
    return PERSONAS[settings.DEFAULT_PERSONA]


def generate_reply(scammer_text: str, persona_name: str = None, conversation_history: list = None) -> str:
    persona = get_persona(persona_name)
    messages = [{"role": "system", "content": persona["system_prompt"]}]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append({"role": "user", "content": f"Scammer: {scammer_text}"})

    client = _get_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=120,
        stream=False,
    )
    return response.choices[0].message.content.strip()


async def generate_reply_async(scammer_text: str, persona_name: str = None, conversation_history: list = None) -> str:
    persona = get_persona(persona_name)
    messages = [{"role": "system", "content": persona["system_prompt"]}]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append({"role": "user", "content": f"Scammer: {scammer_text}"})

    client = _get_async_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=120,
        stream=False,
    )
    return response.choices[0].message.content.strip()


async def generate_reply_stream(
    scammer_text: str, persona_name: str = None, conversation_history: list = None
) -> AsyncGenerator[str, None]:
    """Stream LLM tokens as sentence chunks for low first-audio latency."""
    persona = get_persona(persona_name)
    messages = [{"role": "system", "content": persona["system_prompt"]}]

    if conversation_history:
        messages.extend(conversation_history[-10:])

    messages.append({"role": "user", "content": f"Scammer: {scammer_text}"})

    client = _get_async_client()
    stream = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=120,
        stream=True,
    )

    buffer = ""
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            buffer += delta.content
            # Yield complete sentences as they form so TTS can start early
            sentences = _SENTENCE_SPLIT.split(buffer)
            # Keep the last incomplete fragment in the buffer
            buffer = sentences.pop() if sentences else ""
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    yield sentence

    # Flush any remaining text
    if buffer.strip():
        yield buffer.strip()


def summarize_transcript(transcript: str, scam_type: str = None) -> str:
    prompt = (
        f"Summarize this scam call transcript for the user in 3-5 bullet points. "
        f"Highlight the scammer's tactics and any personal information they tried to extract. "
        f"{'The scam type detected was: ' + scam_type if scam_type else ''}\n\n"
        f"Transcript:\n{transcript}\n\nSummary:"
    )
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()
