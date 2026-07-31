"""Evaluate real RAG answers against frozen references and evidence pages."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path

from src.evaluation.evaluate_retrieval import (
    DEFAULT_QUESTIONS,
    load_questions,
    parse_evidence_pages,
)
from src.generation.rag import RagAnswer, RagPipeline
from src.parsing.parse_report import ROOT


DEFAULT_REPORT = ROOT / "reports" / "002594_2025_deepseek_rag_evaluation.json"
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def normalized_numbers(text: str) -> list[str]:
    normalized: list[str] = []
    for match in _NUMBER.findall(text):
        percent = match.endswith("%")
        value = match.rstrip("%").replace(",", "")
        try:
            canonical = format(Decimal(value).normalize(), "f")
        except InvalidOperation:
            canonical = value
        normalized.append(f"{canonical}%" if percent else canonical)
    return normalized


def _normalized_text(text: str) -> str:
    return re.sub(r"[\s,，。；;：:（）()「」“”\"']", "", text).lower()


def evaluate_case(row: dict[str, str], result: RagAnswer, elapsed: float) -> dict[str, object]:
    reference_numbers = normalized_numbers(row["reference_answer"])
    answer_numbers = set(normalized_numbers(result.answer))
    number_recall = (
        sum(number in answer_numbers for number in reference_numbers)
        / len(reference_numbers)
        if reference_numbers
        else None
    )
    gold_pages = parse_evidence_pages(row["evidence_pages"])
    returned_pages = {
        page for citation in result.citations for page in citation.pdf_pages
    }
    citation_page_hit = bool(gold_pages & returned_pages)
    reference_text_match = (
        _normalized_text(row["reference_answer"]) in _normalized_text(result.answer)
        if not reference_numbers
        else None
    )
    answer_accuracy_proxy = (
        result.status == "answered"
        and citation_page_hit
        and (
            number_recall == 1.0
            if reference_numbers
            else bool(reference_text_match)
        )
    )
    return {
        "question_id": row["question_id"],
        "question": row["question"],
        "question_type": row.get("question_type", ""),
        "difficulty": row.get("difficulty", ""),
        "reference_answer": row["reference_answer"],
        "gold_evidence_pages": sorted(gold_pages),
        "status": result.status,
        "answer": result.answer,
        "refusal_reason": result.refusal_reason,
        "citation_ids": [citation.citation_id for citation in result.citations],
        "citation_chunk_ids": [citation.chunk_id for citation in result.citations],
        "citation_pages": sorted(returned_pages),
        "citation_page_hit": citation_page_hit,
        "reference_numbers": reference_numbers,
        "answer_numbers": sorted(answer_numbers),
        "reference_number_recall": (
            round(number_recall, 4) if number_recall is not None else None
        ),
        "reference_text_match": reference_text_match,
        "answer_accuracy_proxy": answer_accuracy_proxy,
        "elapsed_seconds": round(elapsed, 3),
        "error": None,
    }


def summarize(cases: list[dict[str, object]]) -> dict[str, object]:
    completed = [case for case in cases if case["error"] is None]
    latencies = [float(case["elapsed_seconds"]) for case in completed]
    numeric_cases = [
        case for case in completed if case["reference_number_recall"] is not None
    ]
    return {
        "requested_questions": len(cases),
        "completed_questions": len(completed),
        "answered_questions": sum(case["status"] == "answered" for case in completed),
        "refused_questions": sum(case["status"] == "refused" for case in completed),
        "api_or_pipeline_errors": sum(case["error"] is not None for case in cases),
        "citation_page_hit_rate": round(
            sum(bool(case["citation_page_hit"]) for case in completed)
            / max(len(completed), 1),
            4,
        ),
        "full_reference_number_recall_rate": round(
            sum(float(case["reference_number_recall"]) == 1.0 for case in numeric_cases)
            / max(len(numeric_cases), 1),
            4,
        ),
        "answer_accuracy_proxy": round(
            sum(bool(case["answer_accuracy_proxy"]) for case in completed)
            / max(len(completed), 1),
            4,
        ),
        "average_latency_seconds": (
            round(statistics.mean(latencies), 3) if latencies else None
        ),
        "median_latency_seconds": (
            round(statistics.median(latencies), 3) if latencies else None
        ),
        "max_latency_seconds": round(max(latencies), 3) if latencies else None,
        "failed_question_ids": [
            case["question_id"]
            for case in cases
            if case["error"] is not None or not case["answer_accuracy_proxy"]
        ],
    }


def _write_checkpoint(
    path: Path,
    *,
    questions_path: Path,
    cases: list[dict[str, object]],
) -> dict[str, object]:
    questions = load_questions(questions_path)
    document_ids = {
        f"{row['target_stock_code']}_{row['target_year']}" for row in questions
    }
    document_id = (
        next(iter(document_ids)) if len(document_ids) == 1 else "multi_document"
    )
    report: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "evaluation_set": str(questions_path),
        "question_count": len(cases),
        "metrics_are_proxy": True,
        "metric_notes": [
            "答案正确率代理要求状态为answered、标准证据页被引用，且参考答案中的全部数字出现在答案中",
            "无数字参考答案要求规范化后的参考答案全文出现在模型答案中",
            "该代理指标不能替代人工事实一致性和逐句引用完整性评审",
        ],
        "summary": summarize(cases),
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def evaluate(
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    report_path: Path = DEFAULT_REPORT,
    resume: bool = True,
    retry_question_ids: set[str] | None = None,
) -> dict[str, object]:
    questions = load_questions(questions_path)
    pipeline = RagPipeline()
    previous: dict[str, dict[str, object]] = {}
    if resume and report_path.exists():
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        previous = {
            str(case["question_id"]): case
            for case in saved.get("cases", [])
            if case.get("error") is None
            and str(case["question_id"]) not in (retry_question_ids or set())
        }
    cases: list[dict[str, object]] = []
    for index, row in enumerate(questions, start=1):
        if row["question_id"] in previous:
            case = previous[row["question_id"]]
            cases.append(case)
            print(
                f"[{index}/{len(questions)}] {row['question_id']}: "
                "使用已有成功结果",
                flush=True,
            )
            continue
        started = time.perf_counter()
        try:
            result = pipeline.answer(
                row["question"],
                stock_code=row["target_stock_code"],
                report_year=int(row["target_year"]),
            )
            case = evaluate_case(row, result, time.perf_counter() - started)
        except Exception as exc:
            case = {
                "question_id": row["question_id"],
                "question": row["question"],
                "status": "error",
                "answer": "",
                "answer_accuracy_proxy": False,
                "citation_page_hit": False,
                "reference_number_recall": None,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
        cases.append(case)
        _write_checkpoint(
            report_path,
            questions_path=questions_path,
            cases=cases,
        )
        print(
            f"[{index}/{len(questions)}] {row['question_id']}: "
            f"{case['status']}, proxy={case['answer_accuracy_proxy']}, "
            f"{case['elapsed_seconds']}s",
            flush=True,
        )
    return _write_checkpoint(
        report_path,
        questions_path=questions_path,
        cases=cases,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="真实评估DeepSeek RAG答案与引用")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="忽略已有检查点并重新调用全部问题",
    )
    parser.add_argument(
        "--retry-id",
        action="append",
        default=[],
        help="即使已有成功检查点也重新调用指定question_id，可重复传入",
    )
    args = parser.parse_args()
    try:
        report = evaluate(
            questions_path=args.questions.resolve(),
            report_path=args.report.resolve(),
            resume=not args.no_resume,
            retry_question_ids=set(args.retry_id),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"RAG评估失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告：{args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
