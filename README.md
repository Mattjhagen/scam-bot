# ScamBot — AI-Powered Scam Call Interception

An autonomous system that intercepts incoming scam calls using an AI voice to waste scammer time, records calls for evidence, detects and blocks known scam numbers, and sends summaries to users.

## How It Works

```
Incoming call → Twilio webhook → Scam number check + real-time transcription → AI persona engages scammer → Full call recorded → Transcript + recording sent to user via SMS
```

### Architecture

```
src/
├── main.py                    # FastAPI app entrypoint
├── config.py                  # Settings / env loading
├── api/
│   └── routes.py              # Twilio webhook + REST API endpoints
├── core/
│   ├── models.py              # SQLAlchemy models (ScamNumber, CallRecord, etc.)
│   ├── database.py            # DB session, engine, init
│   ├── schemas.py             # Pydantic request/response models
│   ├── scam_database.py       # Scam number DB + content-based detection
│   ├── tts_engine.py          # Text-to-speech (Polly + gTTS + caching)
│   └── notifier.py            # SMS notifications with transcript summaries
├── nlp/
│   ├── transcribe_audio.py    # Whisper/faster-whisper transcription
│   ├── generate_reply.py      # OpenAI GPT reply generation with personas
│   └── __init__.py
├── telephony/
│   ├── call_manager.py        # Twilio call/SMS/recording management
│   └── media_stream.py        # WebSocket media stream (real-time transcription)
├── data/
│   └── scam_numbers.json      # Seed known scam numbers
└── tests/                     # pytest suite
```

## Features

- **Scam number directory** — SQLite database with 12 pre-seeded known scam numbers, plus user-reported entries
- **Real-time scam detection** — Phone number lookup + keyword-based content analysis
- **AI voice personas** — Confuses and wastes scammer time (CIA grandpa, eccentric grandma, confused tech guy, bureaucratic clerk)
- **Full call recording** — All audio captured for evidence (banks, authorities)
- **Automatic transcription** — Whisper/faster-whisper converts speech to text
- **User notifications** — SMS summary with AI-generated recap sent after each call
- **User reporting** — Anyone can submit scam numbers via API
- **REST API** — Query scam numbers, call records, register users

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Twilio, OpenAI, and AWS credentials
uvicorn src.main:app --reload
```

## Twilio Configuration

1. Buy a phone number on Twilio
2. Set the **Voice & Fax** webhook URL to `https://your-domain.com/telephony/voice`
3. Enable **Call Recording** and **Media Streams** in your Twilio console
4. Set the media stream WebSocket URL to `wss://your-domain.com/telephony/media-stream`

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Yes | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Yes | Your Twilio phone number |
| `PUBLIC_HOST` | Yes | Your public domain (no protocol) |
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT replies |
| `AWS_ACCESS_KEY_ID` | No | AWS credentials for Polly TTS |
| `DATABASE_URL` | No | SQLite path (default: `sqlite:///./data/scam_bot.db`) |

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/telephony/voice` | Twilio voice webhook |
| `GET` | `/telephony/media-stream` | WebSocket for media streaming |
| `POST` | `/api/users` | Register a user |
| `POST` | `/api/scam-reports` | Submit a scam number report |
| `GET` | `/api/scam-numbers` | List known scam numbers |
| `GET` | `/api/calls` | List call records |
| `GET` | `/api/calls/{call_sid}` | Get call details |

## Testing

```bash
pytest src/tests/ -v
```

## License

MIT
