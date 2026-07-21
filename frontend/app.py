"""
HR Policy RAG Chatbot — Main Streamlit Entry Point
Handles sidebar navigation and routes to sub-pages.
"""
import os
import sys

# Ensure frontend dir is in path
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from api_client import health_check
from styles import inject_css

st.set_page_config(
    page_title="PolicyBot RAG Copilot",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 16px 0 24px;">
      <div style="font-size:2.4rem;">🏢</div>
      <div style="font-size:1.1rem; font-weight:700; color:#E8EAF0; margin-top:6px;">PolicyBot RAG Copilot </div>
    </div>
    """, unsafe_allow_html=True)

    #HR-policy-copilot-RAG-system

    # Backend health indicator
    healthy = health_check()
    status_html = (
        '<div style="text-align:center;"><span class="pill pill-green">● API Connected</span></div>'
        if healthy
        else '<div style="text-align:center;"><span class="pill pill-red">● API Offline</span></div>'
    )
    st.markdown(status_html, unsafe_allow_html=True)
    st.markdown("<hr/>", unsafe_allow_html=True)

    nav = st.radio(
        "Navigation",
        options=["💬 Chat", "📤 Upload Policy", "📋 Policies", "🔍 Policy Changes"],
        label_visibility="collapsed",
    )

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#8892A4; font-size:0.76rem; line-height:1.6;">'
        '📄 Upload PDF, DOCX, or TXT<br>'
        'under a policy name.<br>'
        'Versions auto-increment;<br>'
        'diffs &amp; email alerts on v2+.'
        '</div>',
        unsafe_allow_html=True,
    )

# ─── Page routing ─────────────────────────────────────────────────────────────

if not healthy:
    st.error(
        "⚠️ Cannot connect to the backend API at `http://localhost:8000`. "
        "Please start the FastAPI server with:\n\n"
        "```bash\ncd backend && uvicorn main:app --reload --port 8000\n```"
    )

if nav == "💬 Chat":
    from pages.chat_page import render
    render()
elif nav == "📤 Upload Policy":
    from pages.upload_page import render
    render()
elif nav == "📋 Policies":
    from pages.policies_page import render
    render()
elif nav == "🔍 Policy Changes":
    from pages.diffs_page import render
    render()
