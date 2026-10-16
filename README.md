# ScamBot

AI-powered scam call interception, time-wasting, and evidence collection.

ScamBot answers suspected scam calls with a conversational AI persona (via Twilio
Media Streams), transcribes the audio in real time, detects scam patterns, and
records evidence (transcript, recording, confidence score) for reporting.

## Features

- Twilio voice webhook with known-scam number detection
- Real-time audio streaming + Whisper transcription
- LLM-powered personas that waste scammers' time
- Scam number database with seed data and user reports
- REST API for call records, scam numbers, and reports
- Dashboard SPA for reviewing calls and exporting transcripts
- SMS notifications to the owner after calls
- Docker + Compose deployment with Redis-backed rate limiting

## Requirements

- Python 3.9+
- ffmpeg (for audio processing)
- Twilio account + phone number
- OpenAI API key (or compatible base URL)
- Amazon Polly credentials (optional; falls back to gTTS)

## Quick start

```bash
git clone https://github.com/Mattjhagen/scam-bot.git
cd scam-bot
cp .env.example .env
# Edit .env with your Twilio, OpenAI, and AWS credentials
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Initialize the database
alembic upgrade head   # or let the app create tables on startup

uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
cp .env.example .env
# Edit .env with your credentials
docker compose up --build
```

## Environment variables

See `.env.example` for the full list. Required at minimum:
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`
- `OPENAI_API_KEY`
- `PUBLIC_HOST` (required when recording calls)
- `OWNER_PHONE` (where SMS summaries are sent — never the scammer's number)
- `API_KEY` (protects the `/api/*` endpoints)

## API

Endpoints are documented at `/docs` (disabled in production). Key routes:

- `POST /telephony/voice` — Twilio voice webhook
- `WS /telephony/media-stream` — Twilio Media Streams audio
- `POST /api/users` — register a user (API key required)
- `POST /api/scam-reports` — submit a scam report (rate-limited, public)
- `GET /api/scam-numbers` — list known scam numbers (API key required)
- `GET /api/calls` — list intercepted calls (API key required)
- `GET /api/calls/{call_sid}/export` — export a call transcript
- `GET /health` — health check

## Testing

```bash
pip install -e .[test]
pytest
```

## Production

- Set `ENV=production` and `DEBUG=false`.
- Required secrets must be set in `.env`; `validate_startup()` fails fast if missing.
- `/docs` and `/redoc` are disabled in production.
- Use a production-grade database (PostgreSQL) via `DATABASE_URL` instead of SQLite.
- Run behind a TLS-terminating reverse proxy; Twilio webhooks are signature-validated.
- Rate limiting uses Redis when available, falling back to in-memory.

## License

MIT