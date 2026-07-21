from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Boolean,
    ForeignKey, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class PolicyDocument(Base):
    """Tracks every uploaded policy document (PDF, DOCX, or TXT)."""
    __tablename__ = "policy_documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    base_name = Column(String(255), nullable=False, index=True)   # e.g. "leave_policy"
    version = Column(Integer, nullable=False)                      # e.g. 1, 2, 3 (auto-incremented)
    filename = Column(String(255), nullable=False)                 # original uploaded filename
    file_type = Column(String(10), nullable=False, default="pdf")  # "pdf" | "docx" | "txt"
    page_count = Column(Integer, nullable=False)
    char_count = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False)
    file_bytes = Column(String, nullable=True)                     # Base64-encoded raw file, for diffs
    content_hash = Column(String(64), nullable=True, index=True)   # SHA-256 of raw bytes, for duplicate detection
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    metadata_json = Column(JSON, default=dict)                     # extra info

    diffs_as_new = relationship(
        "PolicyDiff", foreign_keys="PolicyDiff.new_doc_id", back_populates="new_doc"
    )
    diffs_as_old = relationship(
        "PolicyDiff", foreign_keys="PolicyDiff.old_doc_id", back_populates="old_doc"
    )


class PolicyDiff(Base):
    """Stores computed diff between two versions of the same policy."""
    __tablename__ = "policy_diffs"

    id = Column(String, primary_key=True, default=generate_uuid)
    base_name = Column(String(255), nullable=False, index=True)
    old_version = Column(Integer, nullable=False)
    new_version = Column(Integer, nullable=False)
    old_doc_id = Column(String, ForeignKey("policy_documents.id"), nullable=False)
    new_doc_id = Column(String, ForeignKey("policy_documents.id"), nullable=False)

    # Diff summary in human-readable markdown
    diff_summary = Column(Text, nullable=False)
    # Raw structured diff for programmatic use
    diff_detail = Column(JSON, default=dict)

    page_count_old = Column(Integer)
    page_count_new = Column(Integer)
    email_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    old_doc = relationship(
        "PolicyDocument", foreign_keys=[old_doc_id], back_populates="diffs_as_old"
    )
    new_doc = relationship(
        "PolicyDocument", foreign_keys=[new_doc_id], back_populates="diffs_as_new"
    )


class Conversation(Base):
    """One conversation session per user/session."""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String(255), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    message_count = Column(Integer, default=0)

    # Compressed summary of older messages (after threshold)
    history_summary = Column(Text, nullable=True)
    summary_up_to_message = Column(Integer, default=0)

    messages = relationship(
        "Message", back_populates="conversation",
        order_by="Message.sequence", cascade="all, delete-orphan"
    )


class Message(Base):
    """Individual chat message."""
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    sequence = Column(Integer, nullable=False)           # ordering within conversation
    role = Column(String(20), nullable=False)            # "human" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    sources = Column(JSON, default=list)                 # retrieved doc references

    conversation = relationship("Conversation", back_populates="messages")


# ─── Engine / Session Factory ───────────────────────────────────────────────

_engine = None
_SessionLocal = None


def init_db(dsn: str):
    global _engine, _SessionLocal
    _engine = create_engine(dsn, pool_pre_ping=True, pool_size=10, max_overflow=20)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_session():
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() before get_session()")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
