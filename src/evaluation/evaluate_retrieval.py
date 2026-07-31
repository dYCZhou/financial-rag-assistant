"""Evaluate retrieval strategies against manually labelled evidence pages."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.parsing.parse_report import ROOT
from src.retrieval.search import search

DEFAULT_QUESTIONS = ROOT / "data" / "evaluation" / "evaluation_questions_template.csv"
DEFAULT_REPORT = ROOT / "reports" / "002594_2025_retrieval_evaluation.json"


def parse_evidence_pages(value: str) -> set[int]:
    pages: set[int] = set()
    for token in value.split("|"):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"证据页范围倒置：{token}")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))
    if not pages:
        raise ValueError("证据页不能为空")
    return pages


def load_questions(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"缺少评估题集：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        questions = list(csv.DictReader(handle))
    required = {
        "question_id",
        "question",
        "target_stock_code",
        "target_year",
        "evidence_pages",
    }
    if not questions:
        raise ValueError("评估题集为空")
    if not required.issubset(questions[0]):
        raise ValueError(f"评估题集缺少字段：{sorted(required - set(questions[0]))}")
    ids = [row["question_id"] for row in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("question_id不唯一")
    for row in questions:
        parse_evidence_pages(row["evidence_pages"])
    return questions


def first_relevant_rank(hits: list[dict[str, object]], evidence_pages: set[int]) -> int | None:
    for hit in hits:
        returned_pages = {int(page) for page in hit["pdf_pages"]}
        if returned_pages & evidence_pages:
            return int(hit["rank"])
    return None


def evaluate_strategy(
    questions: list[dict[str, str]],
    *,
    strategy: str,
    db_dir: Path,
    top_k: int = 5,
    embedding_model: str = "character",
    model_path: str | Path = "BAAI/bge-small-zh-v1.5",
) -> dict[str, object]:
    if top_k < 5:
        raise ValueError("正式小测top_k不得低于5")
    cases: list[dict[str, object]] = []
    for row in questions:
        evidence_pages = parse_evidence_pages(row["evidence_pages"])
        hits = search(
            row["question"],
            strategy=strategy,
            db_dir=db_dir,
            top_k=top_k,
            stock_code=row["target_stock_code"],
            report_year=int(row["target_year"]),
            embedding_model=embedding_model,
            model_path=model_path,
        )
        rank = first_relevant_rank(hits, evidence_pages)
        cases.append({
            "question_id": row["question_id"],
            "question": row["question"],
            "question_type": row.get("question_type", ""),
            "difficulty": row.get("difficulty", ""),
            "evidence_pages": sorted(evidence_pages),
            "first_relevant_rank": rank,
            "hit_at_3": rank is not None and rank <= 3,
            "hit_at_5": rank is not None and rank <= 5,
            "reciprocal_rank": round(1.0 / rank, 6) if rank else 0.0,
            "returned": [
                {
                    "rank": hit["rank"],
                    "chunk_id": hit["chunk_id"],
                    "pdf_pages": hit["pdf_pages"],
                    "score": hit["score"],
                }
                for hit in hits
            ],
        })
    total = len(cases)
    return {
        "strategy": strategy,
        "question_count": total,
        "recall_at_3": round(sum(case["hit_at_3"] for case in cases) / total, 4),
        "recall_at_5": round(sum(case["hit_at_5"] for case in cases) / total, 4),
        "mrr_at_5": round(sum(case["reciprocal_rank"] for case in cases) / total, 4),
        "missed_question_ids_at_5": [
            case["question_id"] for case in cases if not case["hit_at_5"]
        ],
        "cases": cases,
    }


def evaluate(
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    db_dir: Path,
    report_path: Path = DEFAULT_REPORT,
    embedding_model: str = "character",
    model_path: str | Path = "BAAI/bge-small-zh-v1.5",
) -> dict[str, object]:
    questions = load_questions(questions_path)
    strategy_results = [
        evaluate_strategy(
            questions,
            strategy=strategy,
            db_dir=db_dir,
            embedding_model=embedding_model,
            model_path=model_path,
        )
        for strategy in ("baseline", "structured")
    ]
    report: dict[str, object] = {
        "document_id": "002594_2025",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set": str(questions_path),
        "gold_label_type": "manual_pdf_physical_page",
        "hit_rule": "任一返回Chunk的pdf_pages与标准证据页有交集",
        "acceptance_threshold": {"recall_at_5": 0.8},
        "embedding_model": embedding_model,
        "results": strategy_results,
        "quality_accepted": any(
            result["recall_at_5"] >= 0.8 for result in strategy_results
        ),
        "limitations": [
            "当前只评估比亚迪2025年单份年报",
            "指标评估检索证据页命中，不评估最终答案正确性",
            (
                "字符n-gram是索引管线基线，不是正式中文语义Embedding"
                if embedding_model == "character"
                else "当前只验证单一中文语义Embedding模型"
            ),
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="评估基线与优化切分的Top-K检索效果")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--db-dir", type=Path, default=ROOT / "chroma_db")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--embedding-model", choices=["character", "bge"], default="character"
    )
    parser.add_argument("--model-path", default="BAAI/bge-small-zh-v1.5")
    args = parser.parse_args()
    try:
        report = evaluate(
            questions_path=args.questions.resolve(),
            db_dir=args.db_dir.resolve(),
            report_path=args.report.resolve(),
            embedding_model=args.embedding_model,
            model_path=args.model_path,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"评估失败：{exc}", file=sys.stderr)
        return 1
    for result in report["results"]:
        print(
            f"{result['strategy']}: Recall@3={result['recall_at_3']:.2%}, "
            f"Recall@5={result['recall_at_5']:.2%}, MRR@5={result['mrr_at_5']:.4f}"
        )
    print(f"检索质量验收：{'通过' if report['quality_accepted'] else '未通过'}")
    print(f"报告：{args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
