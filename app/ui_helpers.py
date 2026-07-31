"""Pure helpers for the Streamlit product layer."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


ACCEPTED_STATUSES = {"retrieval_quality_accepted"}

DEFAULT_QUESTIONS: dict[object, list[str]] = {
    "default": [
        "营业收入是多少？",
        "研发投入情况如何？",
        "境外业务表现如何？",
        "利润分配预案是什么？",
    ],
    ("比亚迪", 2025): [
        "营业收入是多少？",
        "研发投入金额及占比是多少？",
        "境外地区收入是多少？",
        "利润分配预案是什么？",
    ],
    ("比亚迪", 2024): [
        "营业收入同比增长多少？",
        "研发投入金额是多少？",
        "经营现金流情况如何？",
        "利润分配预案是什么？",
    ],
    ("比亚迪", 2023): [
        "营业收入是多少？",
        "研发投入情况如何？",
        "新能源汽车销量是多少？",
        "境外业务表现如何？",
    ],
    ("宁德时代", 2024): [
        "营业收入是多少？",
        "研发投入金额是多少？",
        "动力电池系统收入是多少？",
        "公司披露了哪些主要风险？",
    ],
}


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
