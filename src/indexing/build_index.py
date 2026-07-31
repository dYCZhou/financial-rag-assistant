"""Build reproducible Chroma collections from chunk JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.chunking.baseline_chunker import DEFAULT_CHUNKS_DIR, DEFAULT_REPORTS_DIR
from src.parsing.parse_report import ROOT
from src.indexing.local_embedding import CharacterNgramEmbedding
from src.indexing.semantic_embedding import BgeSmallZhEmbedding, MODEL_ID as BGE_MODEL_ID

DEFAULT_DB_DIR = ROOT / "chroma_db"
STRATEGIES = {
    "baseline": "baseline_chunks",
    "structured": "structured_chunks",
}
EMBEDDING_MODELS = {"character", "bge"}


def collection_name_for(strategy: str, embedding_model: str) -> str:
    if embedding_model == "character":
        return f"annual_reports_{strategy}_v1"
    return f"annual_reports_{strategy}_{embedding_model}_v1"


def make_embedder(
    embedding_model: str,
    *,
    dimensions: int = 768,
    model_path: str | Path = BGE_MODEL_ID,
):
    if embedding_model == "character":
        return CharacterNgramEmbedding(dimensions=dimensions)
    if embedding_model == "bge":
        return BgeSmallZhEmbedding(model_path=model_path)
    raise ValueError(f"未知Embedding模型：{embedding_model}")


def load_chunks(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"缺少Chunk文件：{path}")
    chunks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not chunks:
        raise ValueError(f"Chunk文件为空：{path}")
    ids = [str(item["chunk_id"]) for item in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Chunk ID不唯一")
    return chunks


def metadata_for(chunk: dict[str, object]) -> dict[str, str | int]:
    return {
        "document_id": str(chunk["document_id"]),
        "company": str(chunk["company"]),
        "stock_code": str(chunk["stock_code"]),
        "report_year": int(chunk["report_year"]),
        "report_type": str(chunk["report_type"]),
        "strategy": str(chunk["strategy"]),
        "chapter": str(chunk.get("chapter", "unknown")),
        "pdf_page_start": int(chunk["pdf_page_start"]),
        "pdf_page_end": int(chunk["pdf_page_end"]),
        "pdf_pages_json": json.dumps(chunk["pdf_pages"], ensure_ascii=False),
        "source_file": str(chunk["source_file"]),
        "source_url": str(chunk["source_url"]),
    }


def build_index(
    *,
    document_id: str,
    strategy: str,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
    db_dir: Path = DEFAULT_DB_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    dimensions: int = 768,
    batch_size: int = 100,
    embedding_model: str = "character",
    model_path: str | Path = BGE_MODEL_ID,
) -> tuple[Path, dict[str, object]]:
    if strategy not in STRATEGIES:
        raise ValueError(f"未知策略：{strategy}")
    if batch_size <= 0:
        raise ValueError("batch_size必须大于0")
    import chromadb

    suffix = STRATEGIES[strategy]
    chunks = load_chunks(chunks_dir / f"{document_id}_{suffix}.jsonl")
    expected_strategy = "fixed_char" if strategy == "baseline" else "chapter_paragraph"
    if any(str(item["document_id"]) != document_id for item in chunks):
        raise ValueError("Chunk文件混入其他document_id")
    if any(str(item["strategy"]) != expected_strategy for item in chunks):
        raise ValueError("Chunk策略与目标索引不一致")

    embedder = make_embedder(
        embedding_model, dimensions=dimensions, model_path=model_path
    )
    actual_dimensions = int(getattr(embedder, "dimensions", dimensions))
    db_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_dir))
    collection_name = collection_name_for(strategy, embedding_model)
    collection_metadata = {
        "hnsw:space": "cosine",
        "embedding_model": embedder.name(),
        "dimensions": actual_dimensions,
    }
    try:
        collection = client.get_collection(collection_name)
        existing_metadata = collection.metadata or {}
        if (
            existing_metadata.get("embedding_model") != embedder.name()
            or int(existing_metadata.get("dimensions", -1)) != actual_dimensions
        ):
            raise ValueError(
                f"现有Collection {collection_name} 的Embedding配置不一致"
            )
        # Re-indexing one report must not erase other companies or years.
        collection.delete(where={"document_id": document_id})
    except ValueError:
        raise
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata=collection_metadata,
        )
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        documents = [str(item["text"]) for item in batch]
        collection.add(
            ids=[str(item["chunk_id"]) for item in batch],
            documents=documents,
            metadatas=[metadata_for(item) for item in batch],
            embeddings=embedder.embed_documents(documents),
        )
    indexed_document = collection.get(
        where={"document_id": document_id},
        include=[],
    )
    indexed_document_count = len(indexed_document["ids"])
    if indexed_document_count != len(chunks):
        raise RuntimeError("当前文档的Chroma记录数与Chunk数量不一致")

    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / (
        f"{document_id}_{strategy}_{embedding_model}_index_report.json"
    )
    report: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_name": collection_name,
        "strategy": strategy,
        "embedding_model": embedder.name(),
        "embedding_type": (
            "offline_character_ngram_hashing_baseline"
            if embedding_model == "character"
            else "pretrained_chinese_semantic_embedding"
        ),
        "embedding_backend": embedding_model,
        "dimensions": actual_dimensions,
        "indexed_chunks": indexed_document_count,
        "collection_total_chunks": collection.count(),
        "company": str(chunks[0]["company"]),
        "stock_code": str(chunks[0]["stock_code"]),
        "report_year": int(chunks[0]["report_year"]),
        "db_path": str(db_dir),
        "limitations": [
            "检索质量必须通过同题Top-K评估后再下结论",
        ],
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_path, report


def main() -> int:
    parser = argparse.ArgumentParser(description="为Chunk建立ChromaDB索引")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), required=True)
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--dimensions", type=int, default=768)
    parser.add_argument(
        "--embedding-model", choices=sorted(EMBEDDING_MODELS), default="character"
    )
    parser.add_argument("--model-path", default=BGE_MODEL_ID)
    args = parser.parse_args()
    try:
        path, report = build_index(
            document_id=args.document_id,
            strategy=args.strategy,
            chunks_dir=args.chunks_dir.resolve(),
            db_dir=args.db_dir.resolve(),
            reports_dir=args.reports_dir.resolve(),
            dimensions=args.dimensions,
            embedding_model=args.embedding_model,
            model_path=args.model_path,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"索引失败：{exc}", file=sys.stderr)
        return 1
    print(f"索引成功：{report['collection_name']}，{report['indexed_chunks']}条")
    print(f"报告：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
