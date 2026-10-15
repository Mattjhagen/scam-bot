import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .core.database import init_db
from .core import scam_database
from .core.database import SessionLocal
from .api.routes import router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENV == "production":
        from .config import validate_startup
        validate_startup()
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
    version="1.0.0",
    lifespan=lifespan,
)

allowed_origins = ["https://localhost:8000"]
if settings.PUBLIC_HOST:
    allowed_origins.append(f"https://{settings.PUBLIC_HOST}")
    allowed_origins.append(f"http://{settings.PUBLIC_HOST}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "GET /health",
            "voice_webhook": "/telephony/voice",
            "media_stream": "/telephony/media-stream",
            "dashboard": "/dashboard/",
            "api_docs": "/docs",
            "register_user": "POST /api/users",
            "submit_report": "POST /api/scam-reports",
            "list_scams": "GET /api/scam-numbers",
            "list_calls": "GET /api/calls",
            "call_detail": "GET /api/calls/{call_sid}",
            "export_transcript": "GET /api/calls/{call_sid}/export",
            "bulk_import": "POST /api/scam-numbers/bulk-import",
            "scam_types": "GET /api/scam-types",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
