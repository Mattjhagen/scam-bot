import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .core.database import init_db
from .core import scam_database
from .core.database import SessionLocal
from .api.routes import router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        result = scam_database.seed_database(db)
        print(f"[STARTUP] Seed: {result}")
    finally:
        db.close()
    yield

app = FastAPI(
    title="ScamBot",
    description="AI-powered scam call interception and evidence collection",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/dashboard", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")

app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "ScamBot",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "voice_webhook": "/telephony/voice",
            "media_stream": "/telephony/media-stream",
            "api_docs": "/docs",
            "register_user": "POST /api/users",
            "submit_report": "POST /api/scam-reports",
            "list_scams": "GET /api/scam-numbers",
            "list_calls": "GET /api/calls",
            "call_detail": "GET /api/calls/{call_sid}",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
