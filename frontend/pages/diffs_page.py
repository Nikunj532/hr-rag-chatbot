"""
Policy Changes (Diffs) Page — Browse AI-generated change summaries between policy versions.
"""
from __future__ import annotations
import streamlit as st
from styles import inject_css, page_header
from api_client import list_diffs


def render():
    inject_css()
    page_header(
        "🔍 Policy Change Log",
        "AI-generated summaries of all detected changes between policy versions.",
    )

    if st.button("🔄 Refresh", key="refresh_diffs"):
        st.rerun()

    try:
        diffs = list_diffs()
    except Exception as exc:
        st.error(f"Could not load diffs: {exc}")
        return

    if not diffs:
        st.info(
            "No policy changes detected yet. Upload a v2+ policy PDF to trigger diff detection.",
            icon="🔍",
        )
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_diffs   = len(diffs)
    emails_sent   = sum(1 for d in diffs if d["email_sent"])
    policies_changed = len({d["base_name"] for d in diffs})

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Version Changes", total_diffs)
    m2.metric("Policies Affected", policies_changed)
    m3.metric("Email Notifications Sent", emails_sent)

    st.markdown("<br/>", unsafe_allow_html=True)

    # ── Filter ────────────────────────────────────────────────────────────────
    policy_names = sorted({d["base_name"] for d in diffs})
    filter_policy = st.selectbox(
        "Filter by policy:",
        options=["All"] + [n.replace("_", " ").title() for n in policy_names],
        key="diff_filter",
    )

    # ── Diff cards ────────────────────────────────────────────────────────────
    for diff in diffs:
        if filter_policy != "All":
            if diff["base_name"].replace("_", " ").title() != filter_policy:
                continue

        policy_title  = diff["policy_name"]
        old_v         = diff["old_version"]
        new_v         = diff["new_version"]
        email_pill    = (
            '<span class="pill pill-green">📧 Email Sent</span>'
            if diff["email_sent"]
            else '<span class="pill pill-orange">📭 Email Pending</span>'
        )

        page_delta = ""
        if diff["page_count_old"] and diff["page_count_new"]:
            delta = diff["page_count_new"] - diff["page_count_old"]
            if delta > 0:
                page_delta = f'<span class="pill pill-green">+{delta} pages</span>'
            elif delta < 0:
                page_delta = f'<span class="pill pill-red">{delta} pages</span>'
            else:
                page_delta = '<span class="pill pill-blue">Same page count</span>'

        header_html = f"""
<div style="background:#1A1F2E; border:1px solid #2A3045; border-left:4px solid #F39C12;
            border-radius:10px; padding:16px 20px; margin-bottom:6px;">
  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
    <div>
      <span class="policy-badge">{policy_title}</span>
      <span style="color:#E8EAF0; font-weight:600; margin: 0 8px;">
        v{old_v} → v{new_v}
      </span>
      {page_delta}
      &nbsp;{email_pill}
    </div>
    <div style="color:#8892A4; font-size:0.8rem;">{diff['created_at'][:16].replace('T', ' ')}</div>
  </div>
</div>"""

        st.markdown(header_html, unsafe_allow_html=True)

        with st.expander("📄 View Change Summary", expanded=False):
            # Page count comparison
            if diff["page_count_old"] and diff["page_count_new"]:
                c1, c2 = st.columns(2)
                c1.metric(
                    f"v{old_v} Page Count",
                    diff["page_count_old"],
                )
                c2.metric(
                    f"v{new_v} Page Count",
                    diff["page_count_new"],
                    delta=diff["page_count_new"] - diff["page_count_old"],
                )
                st.markdown("<br/>", unsafe_allow_html=True)

            # AI-generated summary
            st.markdown("#### 🤖 AI-Generated Change Summary")
            st.markdown(
                f'<div class="diff-card">{diff["diff_summary"]}</div>',
                unsafe_allow_html=True,
            )

            # Chatbot tip
            st.markdown(
                f"""
<div style="background:#0E1117; border:1px solid #2A3045; border-radius:8px;
            padding:12px 16px; margin-top:10px; color:#8892A4; font-size:0.85rem;">
  💬 <strong>Ask the chatbot:</strong>
  <em>"What changed in the {policy_title}?"</em>
  or <em>"Summarise the {policy_title} v{old_v} to v{new_v} changes"</em>
</div>""",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)
