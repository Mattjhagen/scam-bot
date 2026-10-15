# ScamBot — AI-Powered Scam Call Interception

An autonomous system that intercepts incoming scam calls using an AI voice to waste scammer time, records calls for evidence, detects and blocks known scam numbers, and sends summaries to users.

## Architecture

```
Incoming call → Twilio IVR → Scam number check → Real-time Whisper transcription → GPT persona engages scammer → Full call recorded → Transcript + recording sent to user via SMS
```

### Project Structure

```
src/
├── main.py                    # FastAPI entry point (app + lifespan)
├── config.py                  # Settings loaded from environment
├── api/
│   └── routes.py              # Twilio webhooks + REST API endpoints
├── core/
│   ├── models.py              # SQLAlchemy models (Base, ScamNumber, CallRecord, User...)
│   ├── database.py            # Engine, session, init_db
│   ├── schemas.py             # Pydantic request/response models
│   ├── scam_database.py       # Scam number DB, phone normalization, keyword detection
│   ├── tts_engine.py          # Text-to-speech (Polly + gTTS with caching)
│   └── notifier.py            # SMS notifications with AI-summarized transcripts
├── nlp/
│   ├── transcribe_audio.py    # faster-whisper speech-to-text
│   └── generate_reply.py      # GPT reply generation with 4 personas
├── telephony/
│   ├── call_manager.py        # Twilio call/SMS/recording management
│   └── media_stream.py        # WebSocket real-time audio streaming + processing
├── data/
│   └── scam_numbers.json      # Seed known scam numbers (12 entries)
├── static/
│   └── index.html             # Web dashboard
└── tests/                     # 40 tests across 3 test files
```

## Features

- **Scam database** — 12 pre-seeded known scam numbers, with user reporting and bulk import
- **Phone number validation** — Uses `phonenumbers` library for normalization and validation
- **Two-layer scam detection** — Phone number lookup + keyword-based content analysis (7 scam types)
- **Real-time media streaming** — Twilio Media Streams WebSocket receives audio, transcribes with Whisper, generates GPT responses
- **AI voice personas** — 4 configurable personas waste scammer time:
  - Confused CIA Agent (default): rambling 80-year-old ex-agent
  - Eccentric Grandma: hard of hearing, talks about her cats
  - Confused Tech Guy: gives wrong tech advice
  - Bureaucratic Clerk: demands forms and procedures
- **Full call recording** — All calls recorded for evidence
- **Automatic transcription** — Whisper converts speech to text in real-time
- **User notifications** — AI-summarized transcript + recording URL sent via SMS
- **Web dashboard** — View call records, transcripts, scam numbers, submit reports
- **Export tools** — Download call transcripts as text for evidence submission
- **Alembic migrations** — Database schema versioning
- **Docker support** — Dockerfile + docker-compose for deployment

## Setup

```bash
cp .env.example .env
# Edit .env with your Twilio, OpenAI, and AWS credentials
docker compose up --build
```

Or run locally:

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn src.main:app --reload --port 8000
```

## Twilio Configuration

1. Buy a phone number on Twilio
2. Set **Voice & Fax** webhook → `https://your-domain.com/telephony/voice`
3. Enable **Media Streams** → `wss://your-domain.com/telephony/media-stream`
4. Enable **Call Recording** with callback → `https://your-domain.com/telephony/recording-status`
5. Set your domain in `PUBLIC_HOST` env var

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/telephony/voice` | Twilio voice webhook (TwiML response) |
| `GET` | `/telephony/media-stream` | WebSocket for real-time audio |
| `POST` | `/telephony/recording-status` | Recording callback |
| `POST` | `/telephony/call-status` | Call status callback |
| `GET` | `/health` | Health check |
| `GET` | `/api/scam-types` | List scam types |
| `GET` | `/api/scam-numbers` | List known scam numbers (`?search=`, `?skip=`, `?limit=`) |
| `POST` | `/api/scam-numbers/bulk-import` | Bulk import scam numbers |
| `GET` | `/api/scam-numbers/{id}` | Get scam number detail |
| `POST` | `/api/scam-reports` | Report a scam number |
| `GET` | `/api/calls` | List call records |
| `GET` | `/api/calls/{call_sid}` | Get call details |
| `GET` | `/api/calls/{call_sid}/export` | Export transcript as text |
| `POST` | `/api/users` | Register a user |

## Web Dashboard

Available at `/dashboard/` — a full single-page application for viewing call records, transcripts, searching scam numbers, and submitting reports.

## Testing

```bash
pytest src/tests/ -v
```

## License

MIT
