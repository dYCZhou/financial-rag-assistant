"""Pure helpers for the Streamlit product layer."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable


ACCEPTED_STATUSES = {"retrieval_quality_accepted"}
INLINE_CITATION_PATTERN = re.compile(r"(?:\[证据\s*\d+\]|【证据\s*\d+】)")


def answer_for_display(answer: object) -> str:
    """Hide inline citation markers while preserving the stored RAG answer."""
    cleaned = INLINE_CITATION_PATTERN.sub("", str(answer))
    return re.sub(r"[ \t]+([，。；：！？])", r"\1", cleaned).strip()

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
