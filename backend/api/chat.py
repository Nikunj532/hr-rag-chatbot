"""
/api/chat  – Conversational RAG endpoint
/api/conversations – History management
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.models import Conversation, Message, get_session
from services.history_service import (
    get_or_create_conversation,
    save_message,
    build_langchain_history,
    maybe_summarise_history,
)
from workflows.rag_workflow import run_rag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[dict] = []
    query_type: str = "general_rag"
    message_count: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_session)):
    """
    Main chat endpoint.
    1. Load / create conversation from DB
    2. Build LangChain history (summary + recent messages)
    3. Run LangGraph RAG workflow
    4. Save messages to DB
    5. Trigger summarisation if threshold reached
    """
    conversation = get_or_create_conversation(req.session_id, db)

    # Build history for the LLM
    chat_history = build_langchain_history(conversation, db)

    # Run RAG
    result = run_rag(
        user_query=req.message,
        session_id=req.session_id,
        chat_history=chat_history,
    )

    # Persist human message
    save_message(conversation, "human", req.message, db)

    # Persist assistant message
    save_message(
        conversation, "assistant", result["answer"], db,
        sources=result.get("sources", []),
    )

    # Maybe summarise old history
    try:
        maybe_summarise_history(conversation, db)
    except Exception as exc:
        logger.warning("Summarisation failed (non-fatal): %s", exc)

    return ChatResponse(
        session_id=req.session_id,
        answer=result["answer"],
        sources=result.get("sources", []),
        query_type=result.get("query_type", "general_rag"),
        message_count=conversation.message_count,
    )


@router.get("/conversations/{session_id}/history")
def get_history(session_id: str, limit: int = 50, db: Session = Depends(get_session)):
    """Return recent messages for a session."""
    conv = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.sequence.desc())
        .limit(limit)
        .all()
    )
    messages = list(reversed(messages))

    return {
        "session_id": session_id,
        "message_count": conv.message_count,
        "has_summary": bool(conv.history_summary),
        "history_summary": conv.history_summary,
        "messages": [
            {
                "sequence": m.sequence,
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.delete("/conversations/{session_id}")
def delete_conversation(session_id: str, db: Session = Depends(get_session)):
    """Clear a conversation (for testing / reset)."""
    conv = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"message": "Conversation deleted"}


@router.get("/conversations/{session_id}/summary")
def get_summary(session_id: str, db: Session = Depends(get_session)):
    """Return the stored conversation summary (if any)."""
    conv = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "session_id": session_id,
        "history_summary": conv.history_summary,
        "summary_up_to_message": conv.summary_up_to_message,
        "total_messages": conv.message_count,
    }
