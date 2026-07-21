"""
Conversation history with auto-summarisation.

Compatibility notes:
- langchain-groq 1.x: ChatGroq uses api_key= not groq_api_key=
- langchain-core 1.x: HumanMessage/AIMessage/SystemMessage unchanged
"""
from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy.orm import Session
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from core.config import get_settings
from core.constants import GROQ_MODEL, SUMMARY_THRESHOLD, SUMMARY_KEEP_RECENT
from db.models import Conversation, Message

logger = logging.getLogger(__name__)


# ─── CRUD ─────────────────────────────────────────────────────────────────────

def get_or_create_conversation(session_id: str, db: Session) -> Conversation:
    conv = db.query(Conversation).filter_by(session_id=session_id).first()
    if not conv:
        conv = Conversation(session_id=session_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def save_message(
    conversation: Conversation,
    role: str,
    content: str,
    db: Session,
    sources: Optional[list] = None,
) -> Message:
    seq = conversation.message_count + 1
    msg = Message(
        conversation_id=conversation.id,
        sequence=seq,
        role=role,
        content=content,
        sources=sources or [],
    )
    db.add(msg)
    conversation.message_count = seq
    db.commit()
    db.refresh(msg)
    return msg


def load_recent_messages(conversation: Conversation, db: Session) -> list[Message]:
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.sequence > conversation.summary_up_to_message,
        )
        .order_by(Message.sequence)
        .all()
    )


# ─── LangChain history builder ────────────────────────────────────────────────

def build_langchain_history(conversation: Conversation, db: Session) -> list:
    messages = []

    if conversation.history_summary:
        messages.append(
            SystemMessage(
                content=(
                    "Below is a summary of the earlier part of this conversation:\n\n"
                    + conversation.history_summary
                )
            )
        )

    for msg in load_recent_messages(conversation, db):
        if msg.role == "human":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    return messages


# ─── Summarisation ───────────────────────────────────────────────────────────

def _summarise_messages(messages: list[Message]) -> str:
    settings = get_settings()
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=settings.groq_api_key,    # langchain-groq 1.x: api_key= not groq_api_key=
        temperature=0.2,
        max_tokens=800,
    )
    conv_text = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)
    prompt = (
        "Summarise the following HR chatbot conversation concisely. "
        "Preserve key facts, decisions, and any policy details mentioned. "
        "Write in third-person, past tense.\n\n"
        f"{conv_text}\n\nSUMMARY:"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def maybe_summarise_history(conversation: Conversation, db: Session) -> bool:
    if conversation.message_count < SUMMARY_THRESHOLD:
        return False

    all_msgs = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.sequence > conversation.summary_up_to_message,
        )
        .order_by(Message.sequence)
        .all()
    )

    if len(all_msgs) < SUMMARY_THRESHOLD:
        return False

    to_summarise = all_msgs[:-SUMMARY_KEEP_RECENT]
    if not to_summarise:
        return False

    logger.info("Summarising %d messages for session %s", len(to_summarise), conversation.session_id)
    new_summary = _summarise_messages(to_summarise)

    conversation.history_summary = (
        conversation.history_summary + "\n\n--- Later ---\n\n" + new_summary
        if conversation.history_summary
        else new_summary
    )
    conversation.summary_up_to_message = to_summarise[-1].sequence
    db.commit()

    logger.info("History summarised up to message #%d", conversation.summary_up_to_message)
    return True
