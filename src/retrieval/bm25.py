"""Dependency-free BM25 retrieval for Chinese annual-report chunks."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from src.chunking.baseline_chunker import DEFAULT_CHUNKS_DIR


CHUNK_SUFFIXES = {
    "baseline": "baseline_chunks",
    "structured": "structured_chunks",
}
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_ASCII_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?%?")


def tokenize(text: str) -> list[str]:
    """Tokenize Chinese with character n-grams and preserve numbers/Latin terms."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = _ASCII_TOKEN.findall(normalized)
    for run in _CJK_RUN.findall(normalized):
        for width in (1, 2, 3, 4):
            if len(run) < width:
                continue
            tokens.extend(run[index:index + width] for index in range(len(run) - width + 1))
    return tokens


def load_strategy_chunks(
    strategy: str,
    *,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
) -> list[dict[str, object]]:
    if strategy not in CHUNK_SUFFIXES:
        raise ValueError("strategy必须是baseline或structured")
    suffix = CHUNK_SUFFIXES[strategy]
    paths = sorted(chunks_dir.glob(f"*_{suffix}.jsonl"))
    if not paths:
        raise FileNotFoundError(f"缺少{strategy} Chunk文件：{chunks_dir}")
    chunks: list[dict[str, object]] = []
    for path in paths:
        chunks.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    ids = [str(chunk["chunk_id"]) for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{strategy} Chunk ID不唯一")
    return chunks


def _matches_filters(
    chunk: dict[str, object],
    *,
    company: str | None,
    stock_code: str | None,
    report_year: int | None,
) -> bool:
    return (
        (company is None or str(chunk["company"]) == company)
        and (stock_code is None or str(chunk["stock_code"]) == stock_code)
        and (report_year is None or int(chunk["report_year"]) == report_year)
    )


def _as_hit(chunk: dict[str, object], score: float, rank: int) -> dict[str, object]:
    pages = [int(page) for page in chunk["pdf_pages"]]
    return {
        "rank": rank,
        "chunk_id": str(chunk["chunk_id"]),
        "score": round(score, 6),
        "company": str(chunk["company"]),
        "stock_code": str(chunk["stock_code"]),
        "report_year": int(chunk["report_year"]),
        "chapter": str(chunk.get("chapter", "unknown")),
        "pdf_page_start": int(chunk["pdf_page_start"]),
        "pdf_page_end": int(chunk["pdf_page_end"]),
        "pdf_pages": pages,
        "source_file": str(chunk["source_file"]),
        "source_url": str(chunk["source_url"]),
        "text": str(chunk["text"]),
    }


def search_bm25(
    query: str,
    *,
    strategy: str,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
    top_k: int = 5,
    company: str | None = None,
    stock_code: str | None = None,
    report_year: int | None = None,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, object]]:
    """Search only the metadata-filtered corpus, then return traceable hits."""
    if not query.strip():
        raise ValueError("查询问题不能为空")
    if top_k <= 0:
        raise ValueError("top_k必须大于0")
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25参数要求k1>0且0<=b<=1")

    corpus = [
        chunk
        for chunk in load_strategy_chunks(strategy, chunks_dir=chunks_dir)
        if _matches_filters(
            chunk,
            company=company,
            stock_code=stock_code,
            report_year=report_year,
        )
    ]
    if not corpus:
        return []

    query_counts = Counter(tokenize(query))
    documents = [Counter(tokenize(str(chunk["text"]))) for chunk in corpus]
    lengths = [sum(terms.values()) for terms in documents]
    average_length = sum(lengths) / len(lengths)
    document_frequency = Counter(
        token for terms in documents for token in terms
    )
    scored: list[tuple[float, str, dict[str, object]]] = []
    corpus_size = len(corpus)
    for chunk, terms, length in zip(corpus, documents, lengths, strict=True):
        score = 0.0
        for token, query_frequency in query_counts.items():
            frequency = terms.get(token, 0)
            if not frequency:
                continue
            frequency_in_documents = document_frequency[token]
            inverse_document_frequency = math.log(
                1.0 + (corpus_size - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            normalization = frequency + k1 * (
                1.0 - b + b * length / max(average_length, 1.0)
            )
            score += (
                inverse_document_frequency
                * frequency
                * (k1 + 1.0)
                / normalization
                * query_frequency
            )
        if score > 0:
            scored.append((score, str(chunk["chunk_id"]), chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        _as_hit(chunk, score, rank)
        for rank, (score, _, chunk) in enumerate(scored[:top_k], start=1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="使用中文BM25检索财报Chunk")
    parser.add_argument("query")
    parser.add_argument("--strategy", choices=sorted(CHUNK_SUFFIXES), default="baseline")
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--company")
    parser.add_argument("--stock-code")
    parser.add_argument("--report-year", type=int)
    args = parser.parse_args()
    try:
        hits = search_bm25(
            args.query,
            strategy=args.strategy,
            chunks_dir=args.chunks_dir.resolve(),
            top_k=args.top_k,
            company=args.company,
            stock_code=args.stock_code,
            report_year=args.report_year,
        )
    except (OSError, ValueError) as exc:
        print(f"BM25检索失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
