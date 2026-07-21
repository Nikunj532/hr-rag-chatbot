"""
Custom CSS injected into every Streamlit page.
Call inject_css() at the top of each page.
"""
import streamlit as st

CUSTOM_CSS = """
<style>
/* ── Import Fonts ─────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Root Variables ───────────────────────────────────────────── */
:root {
  --bg-primary:    #0E1117;
  --bg-card:       #1A1F2E;
  --bg-card-hover: #212840;
  --accent:        #4F8EF7;
  --accent-dim:    #2D5FC4;
  --success:       #2ECC71;
  --warning:       #F39C12;
  --danger:        #E74C3C;
  --text-primary:  #E8EAF0;
  --text-muted:    #8892A4;
  --border:        #2A3045;
  --radius:        10px;
  --shadow:        0 4px 20px rgba(0,0,0,0.4);
}

/* ── Global ───────────────────────────────────────────────────── */
html, body {
    font-family: 'Inter', sans-serif !important;
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

.stApp {
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

/* ── Hide default streamlit chrome ──────────────────────────── */
#MainMenu, footer { visibility: hidden; }

/* ── Sidebar ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: var(--bg-card) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] .stMarkdown h1,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3 {
    color: var(--text-primary) !important;
}

/* ── Hide auto-generated page nav links ─────────────────────── */
[data-testid="stSidebarNavLinkContainer"] {
    display: none !important;
}

/* ── Sidebar Radio ──────────────────────────────────────────── */
[data-testid="stSidebar"] .stRadio {
    background: transparent !important;
}
[data-testid="stSidebar"] .stRadio > div > label > span {
    color: var(--text-primary) !important;
    font-weight: 500 !important;
    font-size: 0.95rem !important;
}
[data-testid="stSidebar"] .stRadio > div > label {
    padding: 10px 12px !important;
    border-radius: 6px !important;
    transition: background 0.2s !important;
}
[data-testid="stSidebar"] .stRadio > div > label:hover {
    background: rgba(79,142,247,0.1) !important;
}
[data-testid="stSidebar"] .stRadio input[type="radio"]:checked ~ span {
    color: var(--accent) !important;
    font-weight: 600 !important;
}

/* ── Sidebar Labels Text ────────────────────────────────────── */
[data-testid="stSidebar"] .stRadio label {
    color: var(--text-primary) !important;
}
[data-testid="stSidebar"] .stRadio p, 
[data-testid="stSidebar"] .stRadio span {
    color: var(--text-primary) !important;
    font-size: 0.95rem !important;
}

/* ── Page header card ────────────────────────────────────────── */
.page-header {
    background: linear-gradient(135deg, #1A2744 0%, #0E1117 100%);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: var(--radius);
    padding: 20px 28px;
    margin-bottom: 24px;
}
.page-header h1 { margin: 0; font-size: 1.6rem; font-weight: 700; color: var(--text-primary); }
.page-header p  { margin: 6px 0 0; color: var(--text-muted); font-size: 0.9rem; }

/* ── Stat card ───────────────────────────────────────────────── */
.stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 22px;
    text-align: center;
    transition: background 0.2s;
}
.stat-card:hover { background: var(--bg-card-hover); }
.stat-card .stat-value { font-size: 2rem; font-weight: 700; color: var(--accent); }
.stat-card .stat-label { font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }

/* ── Policy badge ────────────────────────────────────────────── */
.policy-badge {
    display: inline-block;
    background: rgba(79,142,247,0.15);
    border: 1px solid var(--accent);
    color: var(--accent);
    border-radius: 20px;
    padding: 2px 12px;
    font-size: 0.78rem;
    font-weight: 600;
}
.version-badge {
    display: inline-block;
    background: rgba(46,204,113,0.15);
    border: 1px solid var(--success);
    color: var(--success);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 0.78rem;
    font-weight: 600;
    margin-left: 6px;
}

/* ── Chat messages ───────────────────────────────────────────── */
.chat-container {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 8px 0;
}

.chat-message {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    animation: fadeSlideIn 0.25s ease-out;
}

@keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0);   }
}

.chat-message.human  { flex-direction: row-reverse; }

.chat-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    flex-shrink: 0;
    font-weight: 600;
}
.chat-message.human  .chat-avatar { background: var(--accent-dim); }
.chat-message.assistant .chat-avatar { background: #2D3748; }

.chat-bubble {
    max-width: 78%;
    padding: 12px 16px;
    border-radius: 14px;
    font-size: 0.93rem;
    line-height: 1.65;
}
.chat-message.human  .chat-bubble {
    background: var(--accent-dim);
    border-bottom-right-radius: 4px;
    color: #fff;
}
.chat-message.assistant .chat-bubble {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-bottom-left-radius: 4px;
}

/* Source chips */
.source-chips { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.source-chip {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    background: rgba(79,142,247,0.1);
    border: 1px solid rgba(79,142,247,0.3);
    color: var(--accent);
    border-radius: 4px;
    padding: 2px 8px;
}

/* ── Diff card ───────────────────────────────────────────────── */
.diff-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-left: 4px solid var(--warning);
    border-radius: var(--radius);
    padding: 20px 24px;
    margin-bottom: 16px;
}
.diff-card h3 { color: var(--warning); margin-top: 0; }

/* ── Upload dropzone look ────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border: 2px dashed var(--border) !important;
    border-radius: var(--radius) !important;
    background: var(--bg-card) !important;
    transition: border-color 0.2s;
}
[data-testid="stFileUploader"]:hover {
    border-color: var(--accent) !important;
}

/* ── Buttons ─────────────────────────────────────────────────── */
.stButton > button {
    background: var(--accent) !important;
    border: none !important;
    color: #fff !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.5rem 1.4rem !important;
    transition: background 0.2s, transform 0.1s !important;
}
.stButton > button:hover {
    background: var(--accent-dim) !important;
    transform: translateY(-1px) !important;
}

/* ── Input ────────────────────────────────────────────────────── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px rgba(79,142,247,0.2) !important;
}

/* ── Metrics ─────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px !important;
}

/* ── Expander ────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}

/* ── Status pills ─────────────────────────────────────────────── */
.pill {
    display: inline-block;
    border-radius: 20px;
    padding: 2px 12px;
    font-size: 0.78rem;
    font-weight: 600;
}
.pill-green  { background: rgba(46,204,113,0.15); color: #2ECC71; border: 1px solid #2ECC71; }
.pill-blue   { background: rgba(79,142,247,0.15); color: #4F8EF7; border: 1px solid #4F8EF7; }
.pill-orange { background: rgba(243,156,18,0.15); color: #F39C12; border: 1px solid #F39C12; }
.pill-red    { background: rgba(231,76,60,0.15);  color: #E74C3C; border: 1px solid #E74C3C; }

/* ── Divider ─────────────────────────────────────────────────── */
hr { border-color: var(--border) !important; }

/* ── Scrollbar ───────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = ""):
    st.markdown(
        f"""<div class="page-header">
              <h1>{title}</h1>
              {'<p>' + subtitle + '</p>' if subtitle else ''}
            </div>""",
        unsafe_allow_html=True,
    )


def _compress_page_ranges(pages: list[int]) -> str:
    """[1,2,3,5,7,8] -> '1-3, 5, 7-8'"""
    if not pages:
        return ""
    pages = sorted(set(pages))
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = p
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(ranges)


def render_sources(sources: list[dict]):
    """One compact chip per policy+version referenced, with a page range —
    not one chip per page, so this stays readable even for long documents."""
    if not sources:
        return

    grouped: dict[tuple, list[int]] = {}
    for s in sources:
        policy_name = s.get("policy_name") or s.get("source", "").split("#")[0]
        version = s.get("version")
        page = s.get("page_number")
        if not policy_name:
            continue
        key = (policy_name, version)
        grouped.setdefault(key, [])
        if page is not None:
            grouped[key].append(page)

    if not grouped:
        return

    chips = []
    for (policy_name, version), pages in sorted(grouped.items()):
        version_label = f" v{version}" if version else ""
        page_label = f" · p{_compress_page_ranges(pages)}" if pages else ""
        chips.append(f'<span class="source-chip">📄 {policy_name}{version_label}{page_label}</span>')

    st.markdown(f'<div class="source-chips">{"".join(chips)}</div>', unsafe_allow_html=True)