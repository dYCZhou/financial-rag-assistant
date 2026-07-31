"""Hybrid BGE/BM25 retrieval with auditable RRF and generic reranking."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from src.indexing.build_index import DEFAULT_DB_DIR
from src.indexing.semantic_embedding import MODEL_ID as BGE_MODEL_ID
from src.parsing.parse_report import ROOT
from src.retrieval.bm25 import search_bm25, tokenize
from src.retrieval.search import search as search_vector


DEFAULT_CONFIG = ROOT / "configs" / "config.yaml"

# Domain-level aliases only. They do not contain question IDs, answers or evidence pages.
FINANCIAL_ALIASES = {
    "归母净利润": "归属于上市公司股东的净利润",
    "研发资金": "研发投入金额",
    "员工人数": "在职员工数量",
    "经营现金流": "经营活动产生的现金流量净额",
    "现金流": "现金流量",
    "分红": "现金红利利润分配",
    "海外": "境外出口",
    "汽车相关业务": "汽车汽车相关产品及其他产品业务",
    "手机部件业务": "手机部件组装及其他产品业务",
}
FINANCIAL_TERMS = {
    "营业收入",
    "净利润",
    "现金红利",
    "研发投入",
    "研发人员",
    "客户",
    "境外收入",
    "在职员工",
    "审计意见",
    "存货",
    "汽车相关产品",
    "手机部件",
    "政府补助",
    "担保",
    "现金流量净额",
}
FINANCIAL_CONCEPT_COMPONENTS = {
    "归母净利润": ("归属于上市公司股东", "净利润"),
    "境外收入": ("境外", "收入"),
    "汽车相关业务": ("汽车", "相关产品", "收入"),
    "手机部件业务": ("手机部件", "收入"),
    "经营现金流": ("经营活动", "现金流量净额"),
}


def load_retrieval_config(path: Path = DEFAULT_CONFIG) -> dict[str, float | int]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    retrieval = raw.get("retrieval", {})
    values: dict[str, float | int] = {
        "top_k": int(retrieval.get("top_k", 5)),
        "candidate_pool": int(retrieval.get("candidate_pool", 30)),
        "bm25_k1": float(retrieval.get("bm25_k1", 1.5)),
        "bm25_b": float(retrieval.get("bm25_b", 0.75)),
        "rrf_k": int(retrieval.get("rrf_k", 60)),
        "rrf_vector_weight": float(retrieval.get("rrf_vector_weight", 1.0)),
        "rrf_bm25_weight": float(retrieval.get("rrf_bm25_weight", 1.0)),
        "rerank_rrf_weight": float(retrieval.get("rerank_rrf_weight", 1.0)),
        "rerank_coverage_weight": float(
            retrieval.get("rerank_coverage_weight", 0.08)
        ),
        "rerank_phrase_weight": float(retrieval.get("rerank_phrase_weight", 0.12)),
        "rerank_numeric_weight": float(retrieval.get("rerank_numeric_weight", 0.04)),
    }
    if values["top_k"] <= 0 or values["candidate_pool"] < values["top_k"]:
        raise ValueError("retrieval配置要求candidate_pool>=top_k>0")
    if values["rrf_k"] <= 0:
        raise ValueError("rrf_k必须大于0")
    return values


def expand_query(query: str) -> str:
    additions = [
        formal
        for alias, formal in FINANCIAL_ALIASES.items()
        if alias in query and formal not in query
    ]
    return " ".join([query, *additions])


def reciprocal_rank_fusion(
    vector_hits: list[dict[str, object]],
    bm25_hits: list[dict[str, object]],
    *,
    rrf_k: int = 60,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> list[dict[str, object]]:
    if rrf_k <= 0:
        raise ValueError("rrf_k必须大于0")
    if vector_weight < 0 or bm25_weight < 0 or vector_weight + bm25_weight == 0:
        raise ValueError("RRF权重必须非负且不能同时为0")
    merged: dict[str, dict[str, object]] = {}
    for retriever, weight, hits in (
        ("vector", vector_weight, vector_hits),
        ("bm25", bm25_weight, bm25_hits),
    ):
        for fallback_rank, hit in enumerate(hits, start=1):
            chunk_id = str(hit["chunk_id"])
            rank = int(hit.get("rank", fallback_rank))
            item = merged.setdefault(chunk_id, dict(hit))
            item[f"{retriever}_rank"] = rank
            item[f"{retriever}_score"] = float(hit["score"])
            item["rrf_score"] = float(item.get("rrf_score", 0.0)) + weight / (
                rrf_k + rank
            )
    fused = list(merged.values())
    fused.sort(key=lambda hit: (-float(hit["rrf_score"]), str(hit["chunk_id"])))
    for rank, hit in enumerate(fused, start=1):
        hit["rank"] = rank
        hit["score"] = round(float(hit["rrf_score"]), 8)
        hit["rrf_score"] = round(float(hit["rrf_score"]), 8)
    return fused


def _meaningful_query_terms(query: str) -> set[str]:
    return {
        token
        for token in tokenize(expand_query(query))
        if len(token) >= 2 and not token.isdigit()
    }


def _weighted_term_coverage(query: str, text: str) -> float:
    terms = _meaningful_query_terms(query)
    if not terms:
        return 0.0
    weights = {term: len(term) ** 2 for term in terms}
    return sum(weight for term, weight in weights.items() if term in text) / sum(
        weights.values()
    )


def _metric_value_score(query: str, text: str) -> float:
    if not re.search(r"多少|金额|比例|同比|增长|下降|余额|人数|分别", query):
        return 0.0
    salient = {
        term
        for term in _meaningful_query_terms(query)
        if len(term) >= 3
    }
    for term in salient:
        for match in re.finditer(re.escape(term), text):
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 50)
            if re.search(r"\d[\d,.]*(?:%|元|万元|百万元|千元|人|股)?", text[start:end]):
                return 1.0
    return 0.0


def _multi_metric_score(query: str, text: str) -> float:
    requested: set[str] = set()
    expanded = expand_query(query)
    for term in FINANCIAL_TERMS:
        if term in expanded:
            requested.add(term)
    for alias, formal in FINANCIAL_ALIASES.items():
        if alias in query:
            requested.add(formal)
    requested_score = (
        sum(term in text for term in requested) / len(requested)
        if requested
        else 0.0
    )
    component_scores = [
        sum(component in text for component in components) / len(components)
        for concept, components in FINANCIAL_CONCEPT_COMPONENTS.items()
        if concept in query
    ]
    return max([requested_score, *component_scores], default=0.0)


def rerank_hits(
    query: str,
    hits: list[dict[str, object]],
    *,
    rrf_weight: float = 1.0,
    coverage_weight: float = 0.08,
    phrase_weight: float = 0.12,
    numeric_weight: float = 0.04,
) -> list[dict[str, object]]:
    expanded = expand_query(query)
    phrases = [
        phrase
        for phrase in [query, *FINANCIAL_ALIASES.values()]
        if len(phrase) >= 2 and (phrase == query or phrase in expanded)
    ]
    wants_numeric = bool(re.search(r"多少|金额|比例|同比|增长|下降|余额|人数", query))
    reranked: list[dict[str, object]] = []
    for original_rank, hit in enumerate(hits, start=1):
        item = dict(hit)
        text = str(item["text"])
        coverage = _weighted_term_coverage(query, text)
        phrase_matches = sum(1 for phrase in phrases if phrase in text)
        phrase_score = phrase_matches / max(len(phrases), 1)
        numeric_score = _metric_value_score(query, text) if wants_numeric else 0.0
        multi_metric_score = _multi_metric_score(query, text)
        rerank_score = (
            rrf_weight * float(item.get("rrf_score", item.get("score", 0.0)))
            + coverage_weight * coverage
            + phrase_weight * phrase_score
            + numeric_weight * numeric_score
            + phrase_weight * multi_metric_score
        )
        item["pre_rerank_rank"] = int(item.get("rank", original_rank))
        item["term_coverage"] = round(coverage, 6)
        item["phrase_score"] = round(phrase_score, 6)
        item["numeric_score"] = numeric_score
        item["multi_metric_score"] = round(multi_metric_score, 6)
        item["rerank_score"] = round(rerank_score, 8)
        reranked.append(item)
    reranked.sort(
        key=lambda hit: (-float(hit["rerank_score"]), str(hit["chunk_id"]))
    )
    for rank, hit in enumerate(reranked, start=1):
        hit["rank"] = rank
        hit["score"] = hit["rerank_score"]
    return reranked


def search_hybrid(
    query: str,
    *,
    strategy: str,
    db_dir: Path = DEFAULT_DB_DIR,
    chunks_dir: Path,
    top_k: int | None = None,
    stock_code: str | None = None,
    report_year: int | None = None,
    embedding_model: str = "bge",
    model_path: str | Path = BGE_MODEL_ID,
    rerank: bool = False,
    config_path: Path = DEFAULT_CONFIG,
) -> list[dict[str, object]]:
    config = load_retrieval_config(config_path)
    final_k = int(top_k or config["top_k"])
    candidate_pool = max(final_k, int(config["candidate_pool"]))
    expanded_query = expand_query(query)
    vector_hits = search_vector(
        query,
        strategy=strategy,
        db_dir=db_dir,
        top_k=candidate_pool,
        stock_code=stock_code,
        report_year=report_year,
        embedding_model=embedding_model,
        model_path=model_path,
    )
    bm25_hits = search_bm25(
        expanded_query,
        strategy=strategy,
        chunks_dir=chunks_dir,
        top_k=candidate_pool,
        stock_code=stock_code,
        report_year=report_year,
        k1=float(config["bm25_k1"]),
        b=float(config["bm25_b"]),
    )
    hits = reciprocal_rank_fusion(
        vector_hits,
        bm25_hits,
        rrf_k=int(config["rrf_k"]),
        vector_weight=float(config["rrf_vector_weight"]),
        bm25_weight=float(config["rrf_bm25_weight"]),
    )
    if rerank:
        hits = rerank_hits(
            query,
            hits,
            rrf_weight=float(config["rerank_rrf_weight"]),
            coverage_weight=float(config["rerank_coverage_weight"]),
            phrase_weight=float(config["rerank_phrase_weight"]),
            numeric_weight=float(config["rerank_numeric_weight"]),
        )
    return hits[:final_k]


def main() -> int:
    parser = argparse.ArgumentParser(description="BGE与BM25混合检索")
    parser.add_argument("query")
    parser.add_argument("--strategy", choices=["baseline", "structured"], default="baseline")
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--chunks-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--stock-code")
    parser.add_argument("--report-year", type=int)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        hits = search_hybrid(
            args.query,
            strategy=args.strategy,
            db_dir=args.db_dir.resolve(),
            chunks_dir=args.chunks_dir.resolve(),
            top_k=args.top_k,
            stock_code=args.stock_code,
            report_year=args.report_year,
            rerank=args.rerank,
            config_path=args.config.resolve(),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"混合检索失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
