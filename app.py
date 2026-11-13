#!/usr/bin/env python3
"""
app.py — Streamlit UI for the Nuer spell checker.

Launch:  streamlit run app.py
"""

import sys
import unicodedata
import streamlit as st
from pathlib import Path

# Ensure the checker module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from checker import SpellChecker, nfc_lower
from github_commit import commit_word


# ---------------------------------------------------------------------------
# Page config & CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Nuer Spell Checker",
    page_icon="📝",
    layout="wide",
)

st.markdown("""
<style>
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Dark-mode hero banner ── */
.hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #e8e8e8;
    padding: 2rem 2.5rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 32px rgba(0,0,0,.35);
}
.hero h1 {
    font-size: 2rem;
    font-weight: 700;
    margin: 0;
    background: linear-gradient(90deg, #e2e2e2, #a78bfa, #38bdf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.hero p {
    margin: .4rem 0 0;
    font-size: .95rem;
    color: #94a3b8;
}

/* ── Flagged-word chip ── */
.flagged {
    background: rgba(239,68,68,.15);
    color: #fca5a5;
    border: 1px solid rgba(239,68,68,.35);
    border-radius: 4px;
    padding: 1px 4px;
    font-weight: 600;
}
.known {
    color: #e2e8f0;
}

/* ── Results container ── */
.result-box {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    line-height: 1.9;
    font-size: 1.05rem;
    margin-bottom: 1rem;
    white-space: pre-wrap;
    word-wrap: break-word;
}

/* ── Sidebar stats cards ── */
.stat-card {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin-bottom: .75rem;
    text-align: center;
}
.stat-card .num {
    font-size: 1.75rem;
    font-weight: 700;
    background: linear-gradient(90deg, #a78bfa, #38bdf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.stat-card .label {
    font-size: .82rem;
    color: #94a3b8;
    margin-top: .15rem;
}

/* ── Suggestion buttons ── */
div.stButton > button {
    border-radius: 8px;
    font-size: .85rem;
    padding: .25rem .75rem;
}

/* ── Hide Streamlit default footer ── */
footer {display: none;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Init checker (cached across reruns)
# ---------------------------------------------------------------------------

@st.cache_resource
def load_checker():
    base = Path(__file__).resolve().parent
    lexicon_path = base / "lexicon.tsv"
    user_path = base / "user_additions.tsv"
    return SpellChecker(lexicon_path, user_additions_path=user_path)


def reload_checker():
    """Force a checker reload."""
    load_checker.clear()
    return load_checker()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "checker" not in st.session_state:
    st.session_state.checker = load_checker()
if "results" not in st.session_state:
    st.session_state.results = []
if "raw_text" not in st.session_state:
    st.session_state.raw_text = ""
if "ignored" not in st.session_state:
    st.session_state.ignored = set()
if "replaced" not in st.session_state:
    st.session_state.replaced = {}  # {(start,end): replacement}

sc = st.session_state.checker


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown('<div class="stat-card"><div class="num">{:,}</div>'
                '<div class="label">Lexicon words</div></div>'
                .format(len(sc.lexicon)), unsafe_allow_html=True)

    flagged_count = sum(1 for r in st.session_state.results if not r["is_known"])
    st.markdown('<div class="stat-card"><div class="num">{}</div>'
                '<div class="label">Flagged words</div></div>'
                .format(flagged_count), unsafe_allow_html=True)

    ignore_caps = st.toggle("Ignore capitalised words", value=False,
                            help="Treat capitalised words mid-sentence as known (proper nouns).")

    st.markdown("---")
    st.markdown("##### About")
    st.markdown(
        "Dictionary-lookup spell checker for **Nuer** (Thok Naath). "
        "Suggestions use Damerau-Levenshtein distance on character units "
        "so combined letters like **ɛ̈  ɔ̈  i̱** are handled correctly."
    )


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.markdown("""
<div class="hero">
    <h1>📝 Nuer Spell Checker</h1>
    <p>Paste Nuer text below, click <strong>Check Spelling</strong>, and review flagged words.</p>
</div>
""", unsafe_allow_html=True)

col_input, col_spacer, col_output = st.columns([5, 0.3, 5])

with col_input:
    st.markdown("#### ✏️  Input Text")
    text_input = st.text_area(
        "Paste Nuer text here:",
        height=260,
        placeholder="Kɛ mi̱ ɣöö ci̱ naath cuɛ jɛ kä…",
        label_visibility="collapsed",
    )

    check_btn = st.button("🔍  Check Spelling", type="primary", use_container_width=True)

if check_btn and text_input.strip():
    st.session_state.raw_text = text_input
    st.session_state.results = sc.check_text(text_input, ignore_capitalised=ignore_caps)
    st.session_state.replaced = {}
    st.rerun()

# ---------------------------------------------------------------------------
# Render highlighted output
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    """HTML-escape text while preserving spaces and newlines."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>"))


results = st.session_state.results

with col_output:
    st.markdown("#### 🔎  Results")
    if results:
        raw = st.session_state.raw_text
        html_parts: list[str] = []
        last = 0
        for r in sorted(results, key=lambda x: x["start"]):
            s, e = r["start"], r["end"]
            # Text before this token
            if s > last:
                between = raw[last:s]
                html_parts.append(_esc(between))
            # The token itself
            display = st.session_state.replaced.get((s, e), raw[s:e])
            if r["is_known"] or r["normalized"] in st.session_state.ignored:
                html_parts.append(f'<span class="known">{_esc(display)}</span>')
            else:
                html_parts.append(f'<span class="flagged">{_esc(display)}</span>')
            last = e
        # Remaining text
        if last < len(raw):
            html_parts.append(_esc(raw[last:]))

        st.markdown(f'<div class="result-box">{"".join(html_parts)}</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="result-box" style="color:#64748b;">Results will appear here after checking.</div>',
            unsafe_allow_html=True,
        )




# ---------------------------------------------------------------------------
# Flagged-word table with actions
# ---------------------------------------------------------------------------

if results:
    flagged = [r for r in results
               if not r["is_known"] and r["normalized"] not in st.session_state.ignored]

    if flagged:
        st.markdown("---")
        st.markdown("### ⚠️  Flagged Words")

        for idx, r in enumerate(flagged):
            tok = r["normalized"]
            suggestions = sc.suggest(tok, n=5)

            with st.container():
                cols = st.columns([2, 5, 1.5, 1.5])
                with cols[0]:
                    st.markdown(f"**`{r['original']}`**")
                with cols[1]:
                    if suggestions:
                        sugg_cols = st.columns(len(suggestions))
                        for si, sugg in enumerate(suggestions):
                            with sugg_cols[si]:
                                if st.button(f"↩ {sugg}", key=f"repl_{idx}_{si}",
                                             use_container_width=True):
                                    st.session_state.replaced[(r["start"], r["end"])] = sugg
                                    st.rerun()
                    else:
                        st.caption("No suggestions")
                with cols[2]:
                    if st.button("➕ Add", key=f"add_{idx}", use_container_width=True):
                        sc.add_word(tok)
                        r["is_known"] = True
                        # Commit to GitHub if secrets are configured
                        try:
                            gh = st.secrets["github"]
                            commit_word(
                                word=tok,
                                freq=1,
                                token=gh["token"],
                                repo=gh["repo"],
                                branch=gh.get("branch", "main"),
                            )
                            st.toast(f"✅ '{tok}' committed to GitHub", icon="✅")
                        except KeyError:
                            # No GitHub secrets configured — local-only add
                            st.toast(f"'{tok}' added (local only — GitHub secrets not set)", icon="⚠️")
                        except Exception as e:
                            st.toast(f"Added locally but GitHub commit failed: {e}", icon="❌")
                        st.rerun()
                with cols[3]:
                    if st.button("🚫 Ignore", key=f"ign_{idx}", use_container_width=True):
                        sc.ignore_word(tok)
                        st.session_state.ignored.add(tok)
                        st.rerun()
    elif st.session_state.raw_text:
        st.success("✅  No spelling issues found!")
