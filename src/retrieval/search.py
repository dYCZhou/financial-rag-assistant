"""Query a Chroma collection with metadata filtering and traceable citations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.indexing.build_index import (
    DEFAULT_DB_DIR,
    collection_name_for,
    make_embedder,
)
from src.indexing.semantic_embedding import MODEL_ID as BGE_MODEL_ID


def search(
    query: str,
    *,
    strategy: str,
    db_dir: Path = DEFAULT_DB_DIR,
    top_k: int = 5,
    stock_code: str | None = None,
    report_year: int | None = None,
    dimensions: int = 768,
    embedding_model: str = "character",
    model_path: str | Path = BGE_MODEL_ID,
) -> list[dict[str, object]]:
    if not query.strip():
        raise ValueError("查询问题不能为空")
    if top_k <= 0:
        raise ValueError("top_k必须大于0")
    if strategy not in {"baseline", "structured"}:
        raise ValueError("strategy必须是baseline或structured")
    import chromadb

    client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_collection(collection_name_for(strategy, embedding_model))
    clauses: list[dict[str, object]] = []
    if stock_code:
        clauses.append({"stock_code": {"$eq": stock_code}})
    if report_year is not None:
        clauses.append({"report_year": {"$eq": report_year}})
    where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)
    embedder = make_embedder(
        embedding_model, dimensions=dimensions, model_path=model_path
    )
    result = collection.query(
        query_embeddings=[embedder.embed_query(query)],
        n_results=min(top_k, collection.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict[str, object]] = []
    for rank, chunk_id in enumerate(result["ids"][0], start=1):
        metadata = result["metadatas"][0][rank - 1]
        distance = float(result["distances"][0][rank - 1])
        hits.append({
            "rank": rank,
            "chunk_id": chunk_id,
            "score": round(1.0 - distance, 6),
            "company": metadata["company"],
            "stock_code": metadata["stock_code"],
            "report_year": metadata["report_year"],
            "chapter": metadata["chapter"],
            "pdf_page_start": metadata["pdf_page_start"],
            "pdf_page_end": metadata["pdf_page_end"],
            "pdf_pages": json.loads(metadata["pdf_pages_json"]),
            "source_file": metadata["source_file"],
            "source_url": metadata["source_url"],
            "text": result["documents"][0][rank - 1],
        })
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="查询财报向量索引")
    parser.add_argument("query")
    parser.add_argument("--strategy", choices=["baseline", "structured"], default="structured")
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--stock-code")
    parser.add_argument("--report-year", type=int)
    parser.add_argument(
        "--embedding-model", choices=["character", "bge"], default="character"
    )
    parser.add_argument("--model-path", default=BGE_MODEL_ID)
    args = parser.parse_args()
    try:
        hits = search(
            args.query,
            strategy=args.strategy,
            db_dir=args.db_dir.resolve(),
            top_k=args.top_k,
            stock_code=args.stock_code,
            report_year=args.report_year,
            embedding_model=args.embedding_model,
            model_path=args.model_path,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"检索失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(hits, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
