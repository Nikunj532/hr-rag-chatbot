"""
Policies Page — Browse all ingested HR policy documents, with delete support.
"""
from __future__ import annotations
import streamlit as st
from styles import inject_css, page_header
from api_client import list_policies, delete_policy, delete_policy_version


def render():
    inject_css()
    page_header(
        "📋 Ingested Policies",
        "All HR policy documents indexed in the vector store.",
    )

    if st.button("🔄 Refresh", key="refresh_policies"):
        st.cache_data.clear()
        st.rerun()

    try:
        policies = list_policies()
    except Exception as exc:
        st.error(f"Could not load policies: {exc}")
        return

    if not policies:
        st.info(
            "No policies uploaded yet. Go to **Upload Policy** to add your first HR policy document.",
            icon="📭",
        )
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    unique_policies = list({p["base_name"] for p in policies})
    total_pages  = sum(p["page_count"] for p in policies)
    total_chunks = sum(p["chunk_count"] for p in policies)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Unique Policies", len(unique_policies))
    m2.metric("Total Versions", len(policies))
    m3.metric("Total Pages", total_pages)
    m4.metric("Indexed Chunks", total_chunks)

    st.markdown("<br/>", unsafe_allow_html=True)

    # ── Group by base_name ────────────────────────────────────────────────────
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for p in policies:
        grouped[p["base_name"]].append(p)

    for base_name, versions in sorted(grouped.items()):
        policy_title = base_name.replace("_", " ").title()
        latest       = max(versions, key=lambda x: x["version"])

        with st.expander(
            f"📄 {policy_title}  ·  {len(versions)} version(s)  ·  "
            f"Latest: v{latest['version']}  ·  {latest['page_count']} pages",
            expanded=False,
        ):
            for v in sorted(versions, key=lambda x: x["version"]):
                is_latest = v["version"] == latest["version"]
                badge = (
                    '<span class="version-badge">Latest</span>'
                    if is_latest
                    else f'<span class="pill pill-orange">v{v["version"]}</span>'
                )

                row_left, row_right = st.columns([5, 1])
                with row_left:
                    st.markdown(
                        f"""
<div style="background:#1A1F2E; border:1px solid #2A3045; border-radius:8px;
            padding:14px 18px; margin-bottom:10px;">
  <div style="display:flex; justify-content:space-between; align-items:center;">
    <div>
      <span class="policy-badge">{policy_title}</span> {badge}
      <span style="color:#8892A4; font-size:0.82rem; margin-left:10px;">
        {v['filename']} · <code style="color:#4F8EF7;">{v.get('file_type','pdf').upper()}</code>
      </span>
    </div>
    <div style="color:#8892A4; font-size:0.8rem;">
      Uploaded: {v['uploaded_at'][:10]}
    </div>
  </div>
  <div style="margin-top:10px; display:flex; gap:24px; color:#8892A4; font-size:0.85rem;">
    <span>📄 {v['page_count']} pages</span>
    <span>🔢 {v['chunk_count']} chunks</span>
    <span>🆔 <code style="color:#4F8EF7; font-size:0.78rem;">{v['id'][:8]}…</code></span>
  </div>
</div>""",
                        unsafe_allow_html=True,
                    )
                with row_right:
                    _delete_version_button(base_name, v["version"])

            st.markdown("<br/>", unsafe_allow_html=True)
            _delete_policy_button(base_name, policy_title)


def _delete_version_button(base_name: str, version: int):
    confirm_key = f"confirm_del_{base_name}_v{version}"
    if st.session_state.get(confirm_key):
        if st.button("⚠️ Confirm", key=f"confirm_btn_{base_name}_v{version}", type="primary"):
            _run_delete_version(base_name, version)
        if st.button("Cancel", key=f"cancel_btn_{base_name}_v{version}"):
            st.session_state[confirm_key] = False
            st.rerun()
    else:
        if st.button("🗑️ Delete", key=f"del_btn_{base_name}_v{version}"):
            st.session_state[confirm_key] = True
            st.rerun()


def _run_delete_version(base_name: str, version: int):
    try:
        result = delete_policy_version(base_name, version)
        st.success(result.get("message", "Deleted."))
        st.cache_data.clear()
        st.rerun()
    except Exception as exc:
        st.error(f"Delete failed — {exc}")


def _delete_policy_button(base_name: str, policy_title: str):
    confirm_key = f"confirm_del_all_{base_name}"
    if st.session_state.get(confirm_key):
        st.warning(f"This deletes **all versions** of {policy_title}, including diff history. This can't be undone.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button(f"⚠️ Confirm delete all of {policy_title}", key=f"confirm_all_{base_name}", type="primary"):
                _run_delete_policy(base_name)
        with c2:
            if st.button("Cancel", key=f"cancel_all_{base_name}"):
                st.session_state[confirm_key] = False
                st.rerun()
    else:
        if st.button(f"🗑️ Delete entire policy ({policy_title})", key=f"del_all_{base_name}"):
            st.session_state[confirm_key] = True
            st.rerun()


def _run_delete_policy(base_name: str):
    try:
        result = delete_policy(base_name)
        st.success(result.get("message", "Deleted."))
        st.cache_data.clear()
        st.rerun()
    except Exception as exc:
        st.error(f"Delete failed — {exc}")
