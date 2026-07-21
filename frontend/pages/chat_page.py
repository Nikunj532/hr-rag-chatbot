"""
Chat Page — Conversational RAG interface with history display.
"""
from __future__ import annotations

import uuid

import streamlit as st
from api_client import (delete_conversation, get_conversation_history,
                        send_chat_message)
from styles import inject_css, page_header, render_sources

# ── Icons ─────────────────────────────────────────────────────────────────────
HUMAN_AVATAR    = "👤"
BOT_AVATAR      = "🤖"
QUERY_TYPE_ICON = {
    "policy_change": "🔄",
    "general_rag":   "📋",
    "greeting":      "👋",
}


def _init_session():
    """Initialise Streamlit session state for chat."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []          # list of {role, content, sources, query_type}
    if "message_count" not in st.session_state:
        st.session_state.message_count = 0
    if "history_loaded" not in st.session_state:
        st.session_state.history_loaded = False


def _load_history_from_backend():
    """Load existing messages from backend on first render."""
    if st.session_state.history_loaded:
        return
    try:
        data = get_conversation_history(st.session_state.session_id, limit=60)
        for m in data.get("messages", []):
            st.session_state.messages.append({
                "role": m["role"],
                "content": m["content"],
                "sources": m.get("sources", []),
                "query_type": "general_rag",
            })
        st.session_state.message_count = data.get("message_count", 0)
    except Exception:
        pass
    st.session_state.history_loaded = True


def _render_message(msg: dict):
    """Render a single chat bubble."""
    role        = msg["role"]
    content     = msg["content"]
    sources     = msg.get("sources", [])
    query_type  = msg.get("query_type", "general_rag")
    is_human    = role == "human"

    avatar = HUMAN_AVATAR if is_human else BOT_AVATAR
    cls    = "human" if is_human else "assistant"

    # Bubble
    st.markdown(
        f"""<div class="chat-message {cls}">
              <div class="chat-avatar">{avatar}</div>
              <div class="chat-bubble">{content}</div>
            </div>""",
        unsafe_allow_html=True,
    )

    # Sources (assistant only)
    if not is_human and sources:
        with st.container():
            col1, _ = st.columns([10, 1])
            with col1:
                render_sources(sources)


def _render_welcome():
    col_left, col_right = st.columns([10, 2])
    
    with col_left:
        st.markdown("""
        <div style="text-align:center; padding: 48px 24px;">
          <div style="font-size: 3.5rem; margin-bottom: 16px;">🏢</div>
          <h2 style="color: #E8EAF0; font-weight: 700; margin-bottom: 8px;">
            Welcome to HR Policy RAG Copilot
          </h2>
          <p style="color: #8892A4; max-width: 520px; margin: 0 auto 24px; line-height: 1.7;">
            Ask me anything about your company's HR policies — leaves, working hours,
            health benefits, office guidelines, and more. I'll always cite the source.
          </p>
          <div style="display:flex; gap:10px; justify-content:center; flex-wrap:wrap;">
            <span class="pill pill-blue">🏖️ Leave entitlements</span>
            <span class="pill pill-blue">⏰ Working hours</span>
            <span class="pill pill-blue">🏥 Health benefits</span>
            <span class="pill pill-blue">🔄 Policy changes</span>
          </div>
          <p style="color: #8892A4; font-size:0.82rem; margin-top: 28px;">
            💡 Try: <em>"How many annual leave days am I entitled to?"</em><br/>
            or: <em>"What changed in the latest leave policy?"</em>
          </p>
        </div>
        """, unsafe_allow_html=True)
    
    # with col_right:
    #     st.markdown("<div style='height: 140px;'></div>", unsafe_allow_html=True)
    #     if st.button("🗑️ Clear Chat History", use_container_width=True):
    #         try:
    #             delete_conversation(st.session_state.session_id)
    #         except Exception:
    #             pass
    #         st.session_state.messages      = []
    #         st.session_state.message_count = 0
    #         st.session_state.history_loaded = True
    #         st.rerun()





def render():
    inject_css()
    _init_session()

    st.markdown("<hr/>", unsafe_allow_html=True)

    # ── Load history once ────────────────────────────────────────────────────
    _load_history_from_backend()

    # ── Welcome screen (shown when no messages) ────────────────────────────
    if not st.session_state.messages:
        _render_welcome()

    # ── Message history ───────────────────────────────────────────────────────
    if st.session_state.messages:
        st.markdown('<div class="chat-container">', unsafe_allow_html=True)
        for msg in st.session_state.messages:
            _render_message(msg)
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Summary notice ─────────────────────────────────────────────────────────
    if st.session_state.message_count >= 200:
        st.info(
            "ℹ️ Conversation history is being automatically compressed to keep responses fast. "
            "All important context is preserved in a summary.",
            icon="🧠",
        )

    # ── Chat input ───────────────────────────────────────────────────────────
    st.markdown("<br/>", unsafe_allow_html=True)

    # Handle suggestion click
    pending = st.session_state.pop("_pending_query", None)

    user_input = st.chat_input(
        "Ask about HR policies…",
        key="chat_input",
    )

    query = pending or user_input

    if query:
        # Add human message immediately
        st.session_state.messages.append({
            "role": "human",
            "content": query,
            "sources": [],
            "query_type": "",
        })
        st.session_state.message_count += 1

        # Show spinner while waiting
        with st.spinner("HRBot is thinking…"):
            try:
                response = send_chat_message(st.session_state.session_id, query)
                answer      = response["answer"]
                sources     = response.get("sources", [])
                query_type  = response.get("query_type", "general_rag")
                msg_count   = response.get("message_count", st.session_state.message_count)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                    "query_type": query_type,
                })
                st.session_state.message_count = msg_count

            except Exception as exc:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"❌ Error communicating with the backend: `{exc}`",
                    "sources": [],
                    "query_type": "error",
                })

        st.rerun()
