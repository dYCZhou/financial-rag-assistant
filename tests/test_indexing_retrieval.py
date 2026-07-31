import json
from pathlib import Path

from src.indexing.build_index import build_index
from src.indexing.local_embedding import CharacterNgramEmbedding
from src.indexing.semantic_embedding import BgeSmallZhEmbedding
from src.retrieval.search import search


def test_embedding_is_deterministic_and_normalized() -> None:
    model = CharacterNgramEmbedding(dimensions=64)
    first = model.embed_query("营业收入")
    second = model.embed_query("营业收入")
    assert first == second
    assert abs(sum(value * value for value in first) - 1.0) < 1e-6


def test_semantic_embedding_rejects_blank_query_before_model_load() -> None:
    model = BgeSmallZhEmbedding(model_path="/not/needed/for/this/test")
    try:
        model.embed_query("  ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("空查询应被拒绝")


def test_build_and_filtered_search(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    records = [
        {
            "chunk_id": f"000001_2025_structured_{index:05d}",
            "document_id": "000001_2025",
            "strategy": "chapter_paragraph",
            "company": "测试公司",
            "stock_code": "000001",
            "report_year": 2025,
            "report_type": "年度报告全文",
            "chapter": "经营情况",
            "pdf_page_start": index + 1,
            "pdf_page_end": index + 1,
            "pdf_pages": [index + 1],
            "text": text,
            "source_file": "test.pdf",
            "source_url": "https://example.com/test.pdf",
        }
        for index, text in enumerate(["营业收入同比增长百分之十。", "研发人员数量持续增加。"])
    ]
    path = chunks_dir / "000001_2025_structured_chunks.jsonl"
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )
    build_index(
        document_id="000001_2025",
        strategy="structured",
        chunks_dir=chunks_dir,
        db_dir=tmp_path / "db",
        reports_dir=tmp_path / "reports",
        dimensions=64,
        embedding_model="character",
    )
    hits = search(
        "营业收入增长",
        strategy="structured",
        db_dir=tmp_path / "db",
        top_k=1,
        stock_code="000001",
        report_year=2025,
        dimensions=64,
        embedding_model="character",
    )
    assert hits[0]["pdf_pages"] == [1]
    assert "营业收入" in hits[0]["text"]
