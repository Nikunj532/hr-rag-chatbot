"""
Thin HTTP client that calls the FastAPI backend.
All Streamlit pages import from here — keeps networking in one place.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TIMEOUT = 120  # seconds — generous for first Groq call


def _url(path: str) -> str:
    return f"{BACKEND_URL}{path}"


# ─── Upload ──────────────────────────────────────────────────────────────────

_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def upload_policy(file_bytes: bytes, filename: str, policy_name: str) -> dict:
    ext = Path(filename).suffix.lower()
    mime = _MIME_TYPES.get(ext, "application/octet-stream")
    resp = requests.post(
        _url("/api/upload"),
        files={"file": (filename, file_bytes, mime)},
        data={"policy_name": policy_name},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Policies ────────────────────────────────────────────────────────────────

def list_policies() -> list[dict]:
    resp = requests.get(_url("/api/policies"), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def delete_policy_version(base_name: str, version: int) -> dict:
    resp = requests.delete(
        _url(f"/api/policies/{base_name}/versions/{version}"), timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()


def delete_policy(base_name: str) -> dict:
    resp = requests.delete(_url(f"/api/policies/{base_name}"), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ─── Diffs ───────────────────────────────────────────────────────────────────

def list_diffs() -> list[dict]:
    resp = requests.get(_url("/api/diffs"), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_latest_diff(base_name: str) -> Optional[dict]:
    resp = requests.get(_url(f"/api/diffs/{base_name}/latest"), timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


# ─── Chat ────────────────────────────────────────────────────────────────────

def send_chat_message(session_id: str, message: str) -> dict:
    resp = requests.post(
        _url("/api/chat"),
        json={"session_id": session_id, "message": message},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_conversation_history(session_id: str, limit: int = 50) -> dict:
    resp = requests.get(
        _url(f"/api/conversations/{session_id}/history"),
        params={"limit": limit},
        timeout=TIMEOUT,
    )
    if resp.status_code == 404:
        return {"messages": [], "message_count": 0, "has_summary": False}
    resp.raise_for_status()
    return resp.json()


def delete_conversation(session_id: str) -> dict:
    resp = requests.delete(
        _url(f"/api/conversations/{session_id}"),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def health_check() -> bool:
    try:
        resp = requests.get(_url("/health"), timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
