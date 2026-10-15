from functools import lru_cache
from typing import Optional

from openai import AsyncOpenAI, OpenAI

from ..config import settings


PERSONAS = {
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
}

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
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.95,
        max_tokens=200,
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
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.95,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


def summarize_transcript(transcript: str, scam_type: str = None) -> str:
    prompt = (
        f"Summarize this scam call transcript for the user in 3-5 bullet points. "
        f"Highlight the scammer's tactics and any personal information they tried to extract. "
        f"{'The scam type detected was: ' + scam_type if scam_type else ''}\n\n"
        f"Transcript:\n{transcript}\n\nSummary:"
    )
    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()
