"""Streamlit product interface for evidence-grounded annual-report Q&A."""

from __future__ import annotations

import html
import sys
import time
from dataclasses import asdict
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui_helpers import (  # noqa: E402
    answer_for_display,
    available_documents,
    citation_page_label,
    friendly_error,
    result_message,
    verified_demo_questions,
)
from src.generation.rag import RagPipeline  # noqa: E402


st.set_page_config(
    page_title="财报智研",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_CSS = """
<style>
    :root {
        --ink: #242429;
        --muted: #85858f;
        --line: #eeeeF2;
        --soft: #f7f7f9;
        --accent: #5e6cf2;
        --accent-soft: #f0f2ff;
    }
    #MainMenu, footer, header {visibility: hidden;}
    [data-testid="stAppViewContainer"] {
        background: #fff;
        color: var(--ink);
    }
    [data-testid="stAppViewContainer"] p,
    [data-testid="stAppViewContainer"] label,
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3,
    [data-testid="stAppViewContainer"] span {
        color: inherit;
    }
    [data-testid="stSidebar"] {
        background: #f6f6f8;
        color: var(--ink);
        border-right: 1px solid #eeeeF2;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding: 1.3rem 1rem;
    }
    .block-container {
        max-width: 880px;
        padding: 1.2rem 2.2rem 7rem;
    }
    .brand {
        display: flex;
        align-items: center;
        gap: .65rem;
        padding: .35rem .45rem 1.4rem;
        font-size: 1.06rem;
        font-weight: 700;
        letter-spacing: -.01em;
    }
    .brand-mark {
        width: 30px;
        height: 30px;
        display: inline-grid;
        place-items: center;
        border-radius: 10px;
        color: white;
        background: linear-gradient(145deg, #7480ff, #5664e8);
        box-shadow: 0 5px 14px rgba(86, 100, 232, .2);
    }
    .sidebar-label {
        color: #9999a3;
        font-size: .75rem;
        margin: 1.35rem .5rem .45rem;
    }
    .history-item {
        padding: .62rem .7rem;
        border-radius: 10px;
        color: #55555e;
        font-size: .88rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .context-bar {
        text-align: center;
        font-size: .88rem;
        color: #777780;
        margin: .25rem 0 1.5rem;
    }
    .hero {
        text-align: center;
        padding: 11vh 0 1.3rem;
    }
    .hero-mark {
        width: 48px;
        height: 48px;
        display: inline-grid;
        place-items: center;
        border-radius: 16px;
        color: white;
        font-size: 1.15rem;
        margin-bottom: 1.1rem;
        background: linear-gradient(145deg, #7884ff, #5664e8);
        box-shadow: 0 10px 28px rgba(86, 100, 232, .23);
    }
    .hero h1 {
        font-size: 1.8rem;
        line-height: 1.35;
        margin: 0 0 .55rem;
        letter-spacing: -.03em;
    }
    .hero p {
        color: var(--muted);
        margin: 0;
        font-size: .94rem;
    }
    .user-row {
        display: flex;
        justify-content: flex-end;
        margin: 1rem 0 1.8rem;
    }
    .user-bubble {
        max-width: 72%;
        padding: .8rem 1.05rem;
        border-radius: 16px 16px 4px 16px;
        background: #f2f3f7;
        line-height: 1.65;
    }
    .assistant-name {
        display: flex;
        align-items: center;
        gap: .5rem;
        font-size: .84rem;
        font-weight: 650;
        margin-bottom: .8rem;
    }
    .mini-mark {
        width: 25px;
        height: 25px;
        display: inline-grid;
        place-items: center;
        color: white;
        border-radius: 8px;
        background: #6371ed;
        font-size: .7rem;
    }
    .answer-copy {
        font-size: .98rem;
        line-height: 1.85;
        margin-bottom: 1rem;
    }
    .answer-note {
        color: #9999a2;
        font-size: .77rem;
        margin-top: 1.15rem;
    }
    .status-note {
        background: var(--accent-soft);
        color: #525db8;
        border-radius: 12px;
        padding: .75rem .9rem;
        font-size: .88rem;
        margin-bottom: 1rem;
    }
    div[data-testid="stExpander"] {
        border: 1px solid var(--line);
        border-radius: 13px;
        box-shadow: none;
        margin-bottom: .55rem;
        overflow: hidden;
    }
    div[data-testid="stExpander"] details summary {
        padding: .75rem .9rem;
        font-size: .88rem;
        color: var(--ink);
    }
    div[data-testid="stButton"] button {
        border-radius: 12px;
        border: 1px solid var(--line);
        background: #fff;
        color: var(--ink);
        min-height: 2.65rem;
        box-shadow: none;
    }
    div[data-testid="stButton"] button p,
    div[data-testid="stPopover"] button p,
    div[data-testid="stLinkButton"] a p {
        color: inherit;
    }
    div[data-testid="stButton"] button:hover {
        border-color: #cfd3ff;
        color: #505ddd;
        background: #fafaff;
    }
    div[data-testid="stSelectbox"] > div > div {
        border-radius: 12px;
        border-color: var(--line);
        background: #fafafd;
        color: var(--ink);
    }
    div[data-testid="stSelectbox"] input,
    div[data-testid="stSelectbox"] [data-baseweb="select"] * {
        color: var(--ink);
    }
    [data-testid="stChatInput"] {
        max-width: 820px;
        margin: auto;
    }
    [data-testid="stChatInput"] > div {
        border-radius: 19px;
        border: 1px solid #e6e6eb;
        box-shadow: 0 8px 30px rgba(22, 25, 45, .08);
        background: white;
    }
    [data-testid="stChatInput"] textarea {
        color: var(--ink);
        caret-color: var(--ink);
        -webkit-text-fill-color: var(--ink);
    }
    [data-testid="stChatInput"] textarea::placeholder {
        color: #8b8b95;
        -webkit-text-fill-color: #8b8b95;
        opacity: 1;
    }
    .boundary {
        text-align: center;
        color: #a0a0a8;
        font-size: .72rem;
        margin-top: .55rem;
    }
    @media (max-width: 760px) {
        .block-container {padding: .8rem 1rem 6rem;}
        .hero {padding-top: 6vh;}
        .user-bubble {max-width: 88%;}
    }
</style>
"""


@st.cache_resource(show_spinner=False)
def get_pipeline() -> RagPipeline:
    return RagPipeline()


def initialize_state() -> None:
    defaults = {
        "current_result": None,
        "current_question": "",
        "elapsed_seconds": None,
        "recent_questions": [],
        "pending_question": None,
        "active_document_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_conversation() -> None:
    st.session_state.current_result = None
    st.session_state.current_question = ""
    st.session_state.elapsed_seconds = None
    st.session_state.pending_question = None


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="brand-mark">◉</span>财报智研</div>',
            unsafe_allow_html=True,
        )
        if st.button("＋  新对话", use_container_width=True):
            clear_conversation()
            st.rerun()

        recent = st.session_state.recent_questions
        if recent:
            st.markdown('<div class="sidebar-label">最近</div>', unsafe_allow_html=True)
            for item in recent[:6]:
                st.markdown(
                    f'<div class="history-item">{html.escape(item)}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown('<div style="height:48vh"></div>', unsafe_allow_html=True)
        with st.popover("关于"):
            st.markdown(
                "基于上市公司年度报告原文回答问题，并提供可追溯引用。"
                "\n\n当前仅开放已完成检索质量验收的报告。"
            )


def select_document(
    documents: dict[str, dict[int, dict[str, str]]],
) -> tuple[str, int, dict[str, str]]:
    companies = list(documents)
    left, right, spacer = st.columns([1.45, 1.15, 3.4])
    with left:
        company = st.selectbox(
            "公司",
            companies,
            label_visibility="collapsed",
            format_func=lambda value: f"{value} ▾",
        )
    years = sorted(documents[company], reverse=True)
    with right:
        year = st.selectbox(
            "年度",
            years,
            label_visibility="collapsed",
            format_func=lambda value: f"{value}年 ▾",
        )
    del spacer
    return company, year, documents[company][year]


def render_welcome(company: str, year: int, document_id: str) -> None:
    st.markdown(
        """
        <div class="hero">
            <div class="hero-mark">◉</div>
            <h1>财报问题，直接问</h1>
            <p>回答均基于已收录的年度报告原文</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    questions = verified_demo_questions(ROOT / "reports", document_id)
    if questions:
        st.caption("已验证示例 · 均通过该报告冻结题集人工验收")
    else:
        st.caption("当前报告暂无已验证示例，请在下方输入问题。")
        return
    cols = st.columns(2)
    for index, question in enumerate(questions[:4]):
        with cols[index % 2]:
            if st.button(question, key=f"suggest-{company}-{year}-{index}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()


def render_result(question: str, result: dict[str, object]) -> None:
    st.markdown(
        f'<div class="user-row"><div class="user-bubble">{html.escape(question)}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="assistant-name"><span class="mini-mark">◉</span>财报智研</div>',
        unsafe_allow_html=True,
    )

    message = result_message(result)
    if message:
        st.markdown(
            f'<div class="status-note">{html.escape(message)}</div>',
            unsafe_allow_html=True,
        )

    answer = answer_for_display(result.get("answer", ""))
    if result.get("status") == "evidence_only":
        answer = ""
    if answer:
        st.markdown(f'<div class="answer-copy">{html.escape(answer)}</div>', unsafe_allow_html=True)

    citations = result.get("citations", [])
    if isinstance(citations, list):
        for citation in citations:
            citation_id = citation.get("citation_id", "")
            label = (
                f"[{citation_id}] 年度报告 · "
                f"{citation_page_label(citation.get('pdf_pages', []))}"
            )
            with st.expander(label):
                chapter = str(citation.get("chapter", "")).strip()
                if chapter and chapter != "unknown":
                    st.caption(chapter)
                st.write(str(citation.get("quote", "")))
                source_url = str(citation.get("source_url", "")).strip()
                if source_url:
                    st.link_button("查看原始年度报告 ↗", source_url)

    if result.get("status") == "answered":
        st.markdown(
            '<div class="answer-note">内容由AI基于年报原文整理，请核对引用。</div>',
            unsafe_allow_html=True,
        )


def submit_question(question: str, document: dict[str, str], year: int) -> None:
    clean_question = question.strip()
    if not clean_question:
        return
    started = time.perf_counter()
    try:
        answer = get_pipeline().answer(
            clean_question,
            stock_code=document["stock_code"],
            report_year=year,
        )
        st.session_state.current_result = answer.to_dict()
    except Exception as exc:  # The UI must never expose backend internals.
        st.session_state.current_result = {
            "status": "error",
            "answer": "",
            "citations": [],
            "error_message": friendly_error(exc),
        }
    st.session_state.elapsed_seconds = time.perf_counter() - started
    st.session_state.current_question = clean_question
    recent = [
        clean_question,
        *[item for item in st.session_state.recent_questions if item != clean_question],
    ]
    st.session_state.recent_questions = recent[:6]


def main() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)
    initialize_state()
    render_sidebar()

    documents = available_documents(
        ROOT / "data" / "manifests" / "annual_reports_manifest.csv"
    )
    if not documents:
        st.info("暂时没有可查询的年度报告。")
        return

    company, year, document = select_document(documents)
    if (
        st.session_state.active_document_id is not None
        and st.session_state.active_document_id != document["document_id"]
    ):
        clear_conversation()
    st.session_state.active_document_id = document["document_id"]
    st.markdown(
        f'<div class="context-bar">{html.escape(company)} · {year}年报</div>',
        unsafe_allow_html=True,
    )

    pending = st.session_state.pending_question
    if pending:
        st.session_state.pending_question = None
        with st.spinner("正在检索年报并核对证据……"):
            submit_question(str(pending), document, year)

    result = st.session_state.current_result
    if result:
        render_result(st.session_state.current_question, result)
    else:
        render_welcome(company, year, document["document_id"])

    question = st.chat_input("问问这份年报……")
    if question:
        with st.spinner("正在检索年报并核对证据……"):
            submit_question(question, document, year)
        st.rerun()

    st.markdown(
        '<div class="boundary">仅提供年报信息整理，不构成投资建议</div>',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
