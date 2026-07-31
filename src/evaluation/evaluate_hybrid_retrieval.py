"""Compare BGE, BM25, hybrid RRF and reranked hybrid retrieval."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.evaluation.evaluate_retrieval import (
    DEFAULT_QUESTIONS,
    first_relevant_rank,
    load_questions,
    parse_evidence_pages,
)
from src.indexing.build_index import DEFAULT_DB_DIR
from src.parsing.parse_report import ROOT
from src.retrieval.bm25 import search_bm25
from src.retrieval.hybrid import (
    DEFAULT_CONFIG,
    expand_query,
    load_retrieval_config,
    reciprocal_rank_fusion,
    rerank_hits,
)
from src.retrieval.search import search as search_vector


DEFAULT_REPORT = ROOT / "reports" / "002594_2025_hybrid_retrieval_evaluation.json"


def summarize_cases(
    method: str,
    cases: list[dict[str, object]],
    *,
    baseline_recall_at_5: float,
) -> dict[str, object]:
    total = len(cases)
    recall_at_3 = sum(bool(case["hit_at_3"]) for case in cases) / total
    recall_at_5 = sum(bool(case["hit_at_5"]) for case in cases) / total
    return {
        "method": method,
        "question_count": total,
        "recall_at_3": round(recall_at_3, 4),
        "recall_at_5": round(recall_at_5, 4),
        "mrr_at_5": round(
            sum(float(case["reciprocal_rank"]) for case in cases) / total, 4
        ),
        "recall_at_5_lift_vs_bge": round(recall_at_5 - baseline_recall_at_5, 4),
        "missed_question_ids_at_5": [
            case["question_id"] for case in cases if not case["hit_at_5"]
        ],
        "cases": cases,
    }


def _case(
    row: dict[str, str],
    hits: list[dict[str, object]],
) -> dict[str, object]:
    evidence_pages = parse_evidence_pages(row["evidence_pages"])
    returned = hits[:5]
    rank = first_relevant_rank(returned, evidence_pages)
    return {
        "question_id": row["question_id"],
        "question": row["question"],
        "question_type": row.get("question_type", ""),
        "difficulty": row.get("difficulty", ""),
        "evidence_pages": sorted(evidence_pages),
        "first_relevant_rank": rank,
        "hit_at_3": rank is not None and rank <= 3,
        "hit_at_5": rank is not None,
        "reciprocal_rank": round(1.0 / rank, 6) if rank else 0.0,
        "returned": [
            {
                key: hit[key]
                for key in (
                    "rank",
                    "chunk_id",
                    "pdf_pages",
                    "score",
                    "vector_rank",
                    "vector_score",
                    "bm25_rank",
                    "bm25_score",
                    "rrf_score",
                    "pre_rerank_rank",
                    "term_coverage",
                    "phrase_score",
                    "numeric_score",
                    "multi_metric_score",
                    "rerank_score",
                )
                if key in hit
            }
            for hit in returned
        ],
    }


def evaluate_strategy(
    questions: list[dict[str, str]],
    *,
    strategy: str,
    db_dir: Path,
    chunks_dir: Path,
    config_path: Path,
) -> dict[str, object]:
    config = load_retrieval_config(config_path)
    candidate_pool = int(config["candidate_pool"])
    method_cases: dict[str, list[dict[str, object]]] = {
        method: [] for method in ("bge", "bm25", "hybrid_rrf", "hybrid_rerank")
    }
    for row in questions:
        filters = {
            "strategy": strategy,
            "top_k": candidate_pool,
            "stock_code": row["target_stock_code"],
            "report_year": int(row["target_year"]),
        }
        vector_hits = search_vector(
            row["question"],
            db_dir=db_dir,
            embedding_model="bge",
            **filters,
        )
        bm25_hits = search_bm25(
            expand_query(row["question"]),
            chunks_dir=chunks_dir,
            k1=float(config["bm25_k1"]),
            b=float(config["bm25_b"]),
            **filters,
        )
        fused = reciprocal_rank_fusion(
            vector_hits,
            bm25_hits,
            rrf_k=int(config["rrf_k"]),
            vector_weight=float(config["rrf_vector_weight"]),
            bm25_weight=float(config["rrf_bm25_weight"]),
        )
        reranked = rerank_hits(
            row["question"],
            fused,
            rrf_weight=float(config["rerank_rrf_weight"]),
            coverage_weight=float(config["rerank_coverage_weight"]),
            phrase_weight=float(config["rerank_phrase_weight"]),
            numeric_weight=float(config["rerank_numeric_weight"]),
        )
        for method, hits in (
            ("bge", vector_hits),
            ("bm25", bm25_hits),
            ("hybrid_rrf", fused),
            ("hybrid_rerank", reranked),
        ):
            method_cases[method].append(_case(row, hits))

    bge_recall = sum(
        bool(case["hit_at_5"]) for case in method_cases["bge"]
    ) / len(questions)
    return {
        "strategy": strategy,
        "methods": [
            summarize_cases(
                method,
                method_cases[method],
                baseline_recall_at_5=bge_recall,
            )
            for method in method_cases
        ],
    }


def evaluate(
    *,
    questions_path: Path = DEFAULT_QUESTIONS,
    db_dir: Path = DEFAULT_DB_DIR,
    chunks_dir: Path = ROOT / "data" / "chunks",
    config_path: Path = DEFAULT_CONFIG,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, object]:
    questions = load_questions(questions_path)
    strategies = [
        evaluate_strategy(
            questions,
            strategy=strategy,
            db_dir=db_dir,
            chunks_dir=chunks_dir,
            config_path=config_path,
        )
        for strategy in ("baseline", "structured")
    ]
    threshold = 0.8
    report: dict[str, object] = {
        "document_id": "002594_2025",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set": str(questions_path),
        "question_count": len(questions),
        "gold_label_type": "manual_pdf_physical_page",
        "hit_rule": "任一Top-K Chunk的pdf_pages与标准证据页有交集",
        "acceptance_threshold": {"recall_at_5": threshold},
        "config": load_retrieval_config(config_path),
        "strategies": strategies,
        "quality_accepted": any(
            float(method["recall_at_5"]) >= threshold
            for strategy in strategies
            for method in strategy["methods"]
        ),
        "limitations": [
            "当前只评估比亚迪2025年单份年报",
            "评估检索证据页命中，不评估最终答案正确性",
            "通用财务术语扩展不读取参考答案、question_id或标准证据页",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="同口径评估四种财报检索方案")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--chunks-dir", type=Path, default=ROOT / "data" / "chunks")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    try:
        report = evaluate(
            questions_path=args.questions.resolve(),
            db_dir=args.db_dir.resolve(),
            chunks_dir=args.chunks_dir.resolve(),
            config_path=args.config.resolve(),
            report_path=args.report.resolve(),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"混合检索评估失败：{exc}", file=sys.stderr)
        return 1
    for strategy in report["strategies"]:
        for method in strategy["methods"]:
            print(
                f"{strategy['strategy']}/{method['method']}: "
                f"Recall@3={method['recall_at_3']:.2%}, "
                f"Recall@5={method['recall_at_5']:.2%}, "
                f"MRR@5={method['mrr_at_5']:.4f}"
            )
    print(f"检索质量验收：{'通过' if report['quality_accepted'] else '未通过'}")
    print(f"报告：{args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
