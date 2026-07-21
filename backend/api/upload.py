"""
/api/upload  – Upload HR policy documents (PDF, DOCX, or TXT)
/api/policies – List ingested policies
/api/diffs   – List policy diffs
/api/diffs/{base_name}/meaningful – Meaningful changes only

Versioning model:
- The caller supplies a `policy_name` (free text, e.g. "Leave Policy").
  It's normalized to a base_name (e.g. "leave_policy") for grouping.
- Version numbers are NOT parsed from the filename — they're auto-assigned:
  first upload for a base_name is v1, each subsequent upload is latest+1.
- Before assigning a new version, the raw file's SHA-256 hash is compared
  against the most recent existing version's hash. If they match, the
  upload is treated as a duplicate (no new version, no diff, no re-ingest) —
  this is the "same doc re-uploaded" guard.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from pathlib import Path

from core.constants import ALLOWED_EXTENSIONS, POLICY_NAME_CLEAN_PATTERN
from db.models import PolicyDiff, PolicyDocument, get_session
from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form,
                     HTTPException, UploadFile)
from services.change_analysis import analyze_changes
from services.diff_service import (StructuredDiff, build_diff_prompt,
                                   compute_diff)
from services.document_parser import parse_document
from services.email_service import send_policy_change_email
from services.vector_store import (delete_policy_all_versions,
                                   delete_policy_version, ingest_document)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])


# ─── Helpers ───────────────────────────────────────────────────────────────

def _normalize_base_name(policy_name: str) -> str:
    """'Leave Policy', 'leave-policy', 'Leave  Policy!!' -> 'leave_policy'."""
    cleaned = policy_name.strip().lower().replace(" ", "_").replace("-", "_")
    cleaned = POLICY_NAME_CLEAN_PATTERN.sub("", cleaned)
    cleaned = _collapse_underscores(cleaned)
    return cleaned.strip("_")


def _collapse_underscores(s: str) -> str:
    return re.sub(r"_+", "_", s)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─── Upload endpoint ──────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_policy(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    policy_name: str = Form(...),
    db: Session = Depends(get_session),
):
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    base_name = _normalize_base_name(policy_name)
    if not base_name:
        raise HTTPException(status_code=400, detail="Policy name cannot be empty.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    content_hash = _hash_bytes(file_bytes)

    # Find the latest existing version for this policy, if any
    latest_doc = (
        db.query(PolicyDocument)
        .filter(PolicyDocument.base_name == base_name)
        .order_by(PolicyDocument.version.desc())
        .first()
    )

    # ── Duplicate content check ────────────────────────────────────────────
    if latest_doc and latest_doc.content_hash == content_hash:
        return {
            "message": (
                f"This file is identical to the already-uploaded "
                f"{base_name.replace('_', ' ').title()} v{latest_doc.version} — "
                "no new version created."
            ),
            "duplicate": True,
            "filename": filename,
            "base_name": base_name,
            "version": latest_doc.version,
            "page_count": latest_doc.page_count,
            "chunk_count": latest_doc.chunk_count,
            "diff_triggered": False,
        }

    version = (latest_doc.version + 1) if latest_doc else 1

    # Parse the document (dispatches by extension: pdf/docx/txt)
    try:
        parsed = parse_document(file_bytes, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    file_bytes_b64 = base64.b64encode(file_bytes).decode("utf-8")

    # Save to DB
    doc = PolicyDocument(
        base_name=base_name,
        version=version,
        filename=filename,
        file_type=ext.lstrip("."),
        page_count=parsed.page_count,
        char_count=parsed.char_count,
        chunk_count=0,  # updated after ingestion
        file_bytes=file_bytes_b64,
        content_hash=content_hash,
        metadata_json={"version": version, "base_name": base_name},
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Ingest into ChromaDB
    chunk_count = ingest_document(parsed, base_name, version, doc.id)
    doc.chunk_count = chunk_count
    db.commit()

    triggered_diff = False
    if latest_doc and version > 1:
        logger.info(
            "New version detected: %s v%s → v%s. Scheduling diff.",
            base_name, latest_doc.version, version,
        )
        from db.models import _SessionLocal
        background_tasks.add_task(
            _background_diff_with_file,
            base_name=base_name,
            old_version=latest_doc.version,
            new_version=version,
            old_doc_id=latest_doc.id,
            new_doc_id=doc.id,
            db_session_factory=_SessionLocal,
        )
        triggered_diff = True

    return {
        "message": "Policy uploaded successfully",
        "duplicate": False,
        "filename": filename,
        "base_name": base_name,
        "version": version,
        "page_count": parsed.page_count,
        "chunk_count": chunk_count,
        "diff_triggered": triggered_diff,
    }


def _background_diff_with_file(
    old_doc_id: str,
    new_doc_id: str,
    base_name: str,
    old_version: int,
    new_version: int,
    db_session_factory,
):
    """
    Background diff using stored raw file bytes (works for PDF, DOCX, or TXT).
    1. Fetch PolicyDocument records from DB
    2. Decode base64 file bytes
    3. Parse both documents (format-aware, preserving tables where applicable)
    4. Compute structured diff
    5. Generate summary via Groq
    6. Save to PolicyDiff and send email
    """
    from core.config import get_settings
    from core.constants import GROQ_MODEL
    from langchain_core.messages import HumanMessage
    from langchain_groq import ChatGroq

    settings = get_settings()
    db = db_session_factory()

    try:
        old_doc = db.query(PolicyDocument).filter(PolicyDocument.id == old_doc_id).first()
        new_doc = db.query(PolicyDocument).filter(PolicyDocument.id == new_doc_id).first()

        if not old_doc or not old_doc.file_bytes:
            logger.error("Old document %s not found or has no file_bytes", old_doc_id)
            return
        if not new_doc or not new_doc.file_bytes:
            logger.error("New document %s not found or has no file_bytes", new_doc_id)
            return

        try:
            old_bytes = base64.b64decode(old_doc.file_bytes)
            new_bytes = base64.b64decode(new_doc.file_bytes)
        except Exception as exc:
            logger.error("Failed to decode file bytes: %s", exc)
            return

        old_parsed = parse_document(old_bytes, old_doc.filename)
        new_parsed = parse_document(new_bytes, new_doc.filename)

        diff = compute_diff(old_parsed, new_parsed, base_name, old_version, new_version)

        if not diff.has_changes:
            logger.info("No changes detected for %s v%s→v%s", base_name, old_version, new_version)
            return

        llm = ChatGroq(
            model=GROQ_MODEL,
            api_key=settings.groq_api_key,
            temperature=0.2,
            max_tokens=1200,
        )
        prompt = build_diff_prompt(diff)
        try:
            resp = llm.invoke([HumanMessage(content=prompt)])
            diff_summary = resp.content.strip()
        except Exception as exc:
            logger.error("LLM diff summary failed: %s", exc)
            diff_summary = "Policy changes detected — please review the new version manually."

        policy_diff = PolicyDiff(
            base_name=base_name,
            old_version=old_version,
            new_version=new_version,
            old_doc_id=old_doc_id,
            new_doc_id=new_doc_id,
            diff_summary=diff_summary,
            diff_detail=diff.to_dict(),
            page_count_old=diff.old_page_count,
            page_count_new=diff.new_page_count,
        )
        db.add(policy_diff)
        db.commit()
        diff_id = policy_diff.id

        email_ok = send_policy_change_email(base_name, old_version, new_version, diff_summary)
        if email_ok:
            policy_diff.email_sent = True
            db.commit()

        logger.info("Diff computed successfully (id=%s), email_sent=%s", diff_id, email_ok)
    except Exception as exc:
        logger.error("Background diff task failed: %s", exc)
    finally:
        db.close()


# ─── Delete ────────────────────────────────────────────────────────────────

@router.delete("/policies/{base_name}/versions/{version}")
def delete_policy_version_endpoint(
    base_name: str, version: int, db: Session = Depends(get_session)
):
    doc = (
        db.query(PolicyDocument)
        .filter(PolicyDocument.base_name == base_name, PolicyDocument.version == version)
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"No version {version} found for policy '{base_name}'.",
        )

    # Remove any diffs that reference this version (either side)
    related_diffs = (
        db.query(PolicyDiff)
        .filter(
            (PolicyDiff.old_doc_id == doc.id) | (PolicyDiff.new_doc_id == doc.id)
        )
        .all()
    )
    for d in related_diffs:
        db.delete(d)

    chunks_deleted = delete_policy_version(base_name, version)
    db.delete(doc)
    db.commit()

    return {
        "message": f"Deleted {base_name.replace('_', ' ').title()} v{version}.",
        "base_name": base_name,
        "version": version,
        "chunks_deleted": chunks_deleted,
        "diffs_deleted": len(related_diffs),
    }


@router.delete("/policies/{base_name}")
def delete_policy_endpoint(base_name: str, db: Session = Depends(get_session)):
    docs = db.query(PolicyDocument).filter(PolicyDocument.base_name == base_name).all()
    if not docs:
        raise HTTPException(status_code=404, detail=f"No policy named '{base_name}' found.")

    diffs = db.query(PolicyDiff).filter(PolicyDiff.base_name == base_name).all()
    for d in diffs:
        db.delete(d)

    chunks_deleted = delete_policy_all_versions(base_name)

    versions_deleted = len(docs)
    for doc in docs:
        db.delete(doc)
    db.commit()

    return {
        "message": (
            f"Deleted {base_name.replace('_', ' ').title()} entirely "
            f"({versions_deleted} version(s))."
        ),
        "base_name": base_name,
        "versions_deleted": versions_deleted,
        "chunks_deleted": chunks_deleted,
        "diffs_deleted": len(diffs),
    }


# ─── List policies ────────────────────────────────────────────────────────────

@router.get("/policies")
def list_policies(db: Session = Depends(get_session)):
    docs = db.query(PolicyDocument).order_by(
        PolicyDocument.base_name, PolicyDocument.version
    ).all()
    return [
        {
            "id": d.id,
            "base_name": d.base_name,
            "policy_name": d.base_name.replace("_", " ").title(),
            "version": d.version,
            "filename": d.filename,
            "file_type": d.file_type,
            "page_count": d.page_count,
            "chunk_count": d.chunk_count,
            "uploaded_at": d.uploaded_at.isoformat(),
        }
        for d in docs
    ]


# ─── List diffs ───────────────────────────────────────────────────────────────

@router.get("/diffs")
def list_diffs(db: Session = Depends(get_session)):
    diffs = db.query(PolicyDiff).order_by(PolicyDiff.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "base_name": d.base_name,
            "policy_name": d.base_name.replace("_", " ").title(),
            "old_version": d.old_version,
            "new_version": d.new_version,
            "diff_summary": d.diff_summary,
            "page_count_old": d.page_count_old,
            "page_count_new": d.page_count_new,
            "email_sent": d.email_sent,
            "created_at": d.created_at.isoformat(),
        }
        for d in diffs
    ]


@router.get("/diffs/{base_name}/latest")
def get_latest_diff(base_name: str, db: Session = Depends(get_session)):
    diff = (
        db.query(PolicyDiff)
        .filter(PolicyDiff.base_name == base_name)
        .order_by(PolicyDiff.created_at.desc())
        .first()
    )
    if not diff:
        raise HTTPException(status_code=404, detail="No diff found for this policy")
    return {
        "base_name": diff.base_name,
        "policy_name": diff.base_name.replace("_", " ").title(),
        "old_version": diff.old_version,
        "new_version": diff.new_version,
        "diff_summary": diff.diff_summary,
        "page_count_old": diff.page_count_old,
        "page_count_new": diff.page_count_new,
        "email_sent": diff.email_sent,
        "created_at": diff.created_at.isoformat(),
    }


@router.get("/diffs/{base_name}/meaningful")
def get_meaningful_changes(base_name: str, db: Session = Depends(get_session)):
    """
    Get MEANINGFUL policy changes for a given policy base name.
    Filters out formatting noise, returns only changes that impact employees/HR.
    Used by UI and RAG for showing what actually changed in a policy.
    """
    diff = (
        db.query(PolicyDiff)
        .filter(PolicyDiff.base_name == base_name)
        .order_by(PolicyDiff.created_at.desc())
        .first()
    )
    if not diff:
        raise HTTPException(status_code=404, detail="No diff found for this policy")

    try:
        diff_data = diff.diff_detail if isinstance(diff.diff_detail, dict) else json.loads(diff.diff_detail)
        structured_diff = StructuredDiff(**diff_data)
    except Exception as e:
        logger.error(f"Failed to parse stored diff for {base_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse stored diff")

    analysis = analyze_changes(structured_diff)

    return {
        "base_name": diff.base_name,
        "policy_name": diff.base_name.replace("_", " ").title(),
        "old_version": diff.old_version,
        "new_version": diff.new_version,
        "has_meaningful_changes": analysis.has_changes(),
        "summary": analysis.get_summary_for_chat(),
        "detailed_summary": analysis.get_detailed_summary(),
        "impact_data": analysis.get_impact_for_ui(),
        "created_at": diff.created_at.isoformat(),
    }
