"""
FastAPI application entry point.
Initialises DB, registers routers, adds CORS middleware.

NOTE: @app.on_event("startup") is deprecated in FastAPI 0.93+.
      Using lifespan context manager instead.
"""
from __future__ import annotations
import logging
import sys
import os
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from db.models import init_db
from api.upload import router as upload_router
from api.chat import router as chat_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    settings = get_settings()
    logger.info("Initialising PostgreSQL …")
    init_db(settings.postgres_dsn)
    logger.info("Database ready.")

    logger.info("Warming up ChromaDB …")
    try:
        from services.vector_store import get_all_policy_names
        names = get_all_policy_names()
        logger.info("ChromaDB ready. Policies found: %s", names or "(none yet)")
    except Exception as exc:
        logger.warning("ChromaDB warm-up failed (non-fatal): %s", exc)

    yield

    # ── Shutdown (nothing needed) ─────────────────────────────────────────────

app = FastAPI(
    title="HR Policy RAG Chatbot API",
    description="Upload HR policies, detect version changes, chat with LangGraph RAG",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
