"""
Upload Page — Upload HR policy documents (PDF, DOCX, or TXT).
Version numbers are auto-assigned; duplicate content is detected and skipped.
"""
from __future__ import annotations
import streamlit as st
from styles import inject_css, page_header
from api_client import upload_policy

SUPPORTED_TYPES = ["pdf", "docx", "txt"]


def render():
    inject_css()
    page_header(
        "📤 Upload HR Policy",
        "Upload a policy document (PDF, DOCX, or TXT) under a policy name — "
        "versions are tracked automatically.",
    )

    with st.expander("📌 How versioning works", expanded=False):
        st.markdown("""
- Give each policy a **name** (e.g. "Leave Policy") — it doesn't need to match the filename.
- The first upload under a name becomes **v1**. Every next upload under the same
  name is auto-assigned the next version number.
- If you re-upload a file that's byte-for-byte identical to the latest version,
  it's detected as a **duplicate** and skipped — no new version, no re-processing.
- On version 2+, the system automatically computes a diff against the previous
  version, generates an AI summary, and emails HR admins.
- Supported formats: **PDF, DOCX, TXT**.
        """)

    st.markdown("<br/>", unsafe_allow_html=True)

    col_upload, col_info = st.columns([6, 4])

    with col_upload:
        st.markdown("### Policy Name")
        policy_name = st.text_input(
            "Policy name",
            placeholder="e.g. Leave Policy",
            label_visibility="collapsed",
        )

        st.markdown("### Upload File")
        uploaded_file = st.file_uploader(
            "Drop a PDF, DOCX, or TXT file here",
            type=SUPPORTED_TYPES,
            accept_multiple_files=False,
            label_visibility="collapsed",
        )

        if uploaded_file:
            st.markdown(f"**Selected:** `{uploaded_file.name}`")

        st.markdown("<br/>", unsafe_allow_html=True)

        upload_disabled = not (policy_name and policy_name.strip() and uploaded_file)
        if st.button("🚀 Upload", type="primary", disabled=upload_disabled):
            _do_upload(uploaded_file, policy_name.strip())

        if not policy_name or not policy_name.strip():
            st.caption("Enter a policy name to enable upload.")

    with col_info:
        st.markdown("### What happens on upload?")
        st.markdown("""
<div style="background:#1A1F2E; border:1px solid #2A3045; border-radius:10px; padding:18px;">

**Step 1 — Parse**
Document is parsed (PDF page-by-page, DOCX/TXT as one logical page). Tables are extracted separately for precise retrieval.

**Step 2 — Duplicate Check**
The file's content is hashed and compared to the latest version. Identical content is skipped.

**Step 3 — Chunk & Embed**
Text is split into overlapping chunks, embedded locally with a free HuggingFace model, and stored in ChromaDB.

**Step 4 — Diff & Email**
If this is v2+, a diff is computed against the previous version, an AI summary is generated, and HR admins are emailed.

</div>
        """, unsafe_allow_html=True)


def _do_upload(uploaded_file, policy_name: str):
    with st.spinner(f"Uploading {uploaded_file.name}…"):
        try:
            data = upload_policy(uploaded_file.read(), uploaded_file.name, policy_name)
        except Exception as exc:
            st.error(f"❌ Upload failed — {exc}")
            return

    st.markdown("---")
    st.markdown("### Upload Result")

    if data.get("duplicate"):
        st.warning(f"⏭️ {data['message']}")
        return

    diff_msg = ""
    if data.get("diff_triggered"):
        diff_msg = (
            "\n\n🔄 **Version change detected!** Diff analysis is running in the background. "
            "An email notification will be sent shortly. Check the **Policy Changes** tab for the summary."
        )

    st.success(
        f"✅ **{data['filename']}** uploaded successfully\n\n"
        f"- Policy: **{data['base_name'].replace('_',' ').title()}** v{data['version']}\n"
        f"- Pages: {data['page_count']}\n"
        f"- Chunks indexed: {data['chunk_count']}"
        + diff_msg
    )
