"""Pure helpers for the Streamlit product layer."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable


ACCEPTED_STATUSES = {"retrieval_quality_accepted"}
INLINE_CITATION_PATTERN = re.compile(r"(?:\[证据\s*\d+\]|【证据\s*\d+】)")
TOP_LEVEL_SECTION_PATTERN = re.compile(
    r"^(第[一二三四五六七八九十]+节)\s+([^\n]{2,32})$", re.MULTILINE
)
TOC_LINE_PATTERN = re.compile(
    r"^\s*(.{2,48}?)\s*(?:\.{3,}|…{2,}|．{3,})\s*(\d+)\s*$"
)


def answer_for_display(answer: object) -> str:
    """Hide inline citation markers while preserving the stored RAG answer."""
    cleaned = INLINE_CITATION_PATTERN.sub("", str(answer))
    return re.sub(r"[ \t]+([，。；：！？])", r"\1", cleaned).strip()


def guide_intent(question: str) -> str | None:
    compact = re.sub(r"[\s，。！？?、]", "", question)
    if any(
        term in compact
        for term in ("你能回答什么", "你能回答我什么", "能问什么", "怎么提问", "如何提问")
    ):
        return "capabilities"
    if (
        "目录概览" in compact
        or (
            any(document_term in compact for document_term in ("财报", "年报", "报告"))
            and any(structure_term in compact for structure_term in ("结构", "目录"))
        )
    ):
        return "structure"
    return None


def capability_answer(company: str, year: int) -> str:
    return (
        f"我可以基于《{company}{year}年年度报告》回答以下问题：\n\n"
        "• 财务指标：资产、负债、收入、利润和现金流\n"
        "• 经营信息：主营业务、研发、客户和境外业务\n"
        "• 报告事项：分红方案、审计意见和风险因素\n"
        "• 证据追溯：展示年报原文、PDF物理页码和来源链接\n\n"
        "你可以点击下方已验证示例，也可以直接输入问题。我不提供股价预测、估值或投资建议。"
    )


def report_structure(parsed_path: Path, limit: int = 12) -> list[tuple[str, int]]:
    """Extract top-level annual-report sections and their first physical pages."""
    try:
        records = [
            json.loads(line)
            for line in parsed_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        return []
    except json.JSONDecodeError:
        return []

    sections: list[tuple[str, int]] = []
    seen: set[str] = set()
    for page in records:
        chapter = str(page.get("chapter", "")).strip()
        match = TOP_LEVEL_SECTION_PATTERN.match(chapter)
        if not match:
            continue
        title = f"{match.group(1)} {match.group(2).strip()}"
        if title not in seen:
            seen.add(title)
            sections.append((title, int(page["pdf_page"])))
    if len(sections) >= 6:
        return sections[:limit]

    # Some SSE/red-chip reports do not use numbered top-level chapter metadata.
    # Recover their actual table of contents and map printed pages to PDF pages.
    printed_to_pdf = {
        int(page["printed_page"]): int(page["pdf_page"])
        for page in records
        if page.get("printed_page") is not None
    }
    toc_sections: list[tuple[str, int]] = []
    seen.clear()
    for page in records[:10]:
        for line in str(page.get("text", "")).splitlines():
            match = TOC_LINE_PATTERN.match(line)
            if not match:
                continue
            title = re.sub(r"\s+", " ", match.group(1)).strip(" ·")
            if title in seen or title in {"目录", "目 录"}:
                continue
            printed_page = int(match.group(2))
            seen.add(title)
            toc_sections.append(
                (title, printed_to_pdf.get(printed_page, printed_page + 1))
            )
            if len(toc_sections) >= limit:
                return toc_sections
    return toc_sections or sections[:limit]


def structure_answer(company: str, year: int, sections: list[tuple[str, int]]) -> str:
    if not sections:
        return f"暂时无法读取《{company}{year}年年度报告》的章节结构。"
    lines = [f"《{company}{year}年年度报告》主要由以下章节构成：", ""]
    lines.extend(f"{index}. {title}（PDF第{page}页起）" for index, (title, page) in enumerate(sections, 1))
    lines.extend(
        [
            "",
            "阅读建议：经营表现优先查看“管理层讨论与分析”；具体财务数字及会计口径优先查看“财务报告”和报表附注。",
        ]
    )
    return "\n".join(lines)

def available_documents(
    manifest_path: Path,
) -> dict[str, dict[int, dict[str, str]]]:
    """Return only documents whose retrieval quality has been accepted."""
    documents: dict[str, dict[int, dict[str, str]]] = {}
    with manifest_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("parse_status") not in ACCEPTED_STATUSES:
                continue
            company = row["company_short_name"].strip()
            year = int(row["report_year"])
            documents.setdefault(company, {})[year] = {
                "document_id": row["document_id"].strip(),
                "company": company,
                "stock_code": row["stock_code"].strip(),
                "source_url": row.get("source_url", "").strip(),
            }
    return documents


def verified_demo_questions(
    reports_dir: Path,
    document_id: str,
    limit: int = 4,
) -> list[str]:
    """Load only questions accepted by the report's manual RAG review."""
    if limit <= 0:
        return []
    review_path = reports_dir / f"{document_id}_deepseek_rag_manual_review.json"
    evaluation_path = reports_dir / f"{document_id}_deepseek_rag_evaluation.json"
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    cases = evaluation.get("cases", evaluation.get("results", []))
    accepted_ids = set(review.get("fully_correct_question_ids", []))
    if not accepted_ids:
        accepted_ids = {
            item.get("question_id")
            for item in review.get("cases", [])
            if item.get("verdict") == "correct"
        }
    if not accepted_ids:
        summary = review.get("summary", {})
        reviewed_count = summary.get("reviewed_questions", summary.get("question_count"))
        fully_correct = summary.get("fully_correct")
        no_failures = all(
            int(summary.get(key, 0)) == 0
            for key in ("incorrect", "refused", "api_or_pipeline_errors")
        )
        if reviewed_count and fully_correct == reviewed_count and no_failures:
            accepted_ids = {
                item.get("question_id")
                for item in cases
                if item.get("status") == "answered"
            }
    if not accepted_ids:
        return []
    accepted = [
        str(item.get("question", "")).strip()
        for item in cases
        if item.get("question_id") in accepted_ids
        and item.get("status") == "answered"
        and str(item.get("question", "")).strip()
    ]
    if len(accepted) <= limit:
        return accepted

    # Spread cards across the frozen set instead of showing four adjacent rows.
    positions = [round(index * (len(accepted) - 1) / (limit - 1)) for index in range(limit)]
    return [accepted[position] for position in positions]


def citation_page_label(pages: Iterable[object]) -> str:
    normalized = sorted({int(page) for page in pages})
    if not normalized:
        return "PDF页码未知"
    if len(normalized) == 1:
        return f"PDF第{normalized[0]}页"
    return f"PDF第{normalized[0]}–{normalized[-1]}页"


def result_message(result: dict[str, object]) -> str:
    status = result.get("status")
    reason = result.get("refusal_reason")
    if status == "evidence_only":
        return "已找到相关年报内容。当前未生成摘要回答，你可以直接查看以下原文。"
    if status == "error":
        return str(result.get("error_message") or "暂时无法完成查询，请稍后再试。")
    if status != "refused":
        return ""
    if reason == "investment_advice_out_of_scope":
        return "这个问题涉及投资建议或价格预测，我暂时不能回答。你可以询问经营情况、财务指标或风险因素。"
    return "我没有在当前年度报告中找到足够可靠的信息。你可以换一种问法，或重新选择公司和年度。"


def friendly_error(exc: Exception) -> str:
    del exc
    return "暂时无法完成查询，请稍后再试。"
