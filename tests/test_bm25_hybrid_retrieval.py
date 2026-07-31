import json
import hashlib
from pathlib import Path

import pytest

from src.retrieval.bm25 import load_strategy_chunks, search_bm25, tokenize
from src.retrieval.hybrid import (
    expand_query,
    load_retrieval_config,
    reciprocal_rank_fusion,
    rerank_hits,
)
from src.parsing.parse_report import ROOT


def _write_chunks(directory: Path) -> None:
    directory.mkdir()
    records = [
        {
            "chunk_id": "000001_2025_baseline_00000",
            "document_id": "000001_2025",
            "strategy": "fixed_char",
            "company": "测试公司",
            "stock_code": "000001",
            "report_year": 2025,
            "report_type": "年度报告全文",
            "chapter": "主要财务指标",
            "pdf_page_start": 1,
            "pdf_page_end": 1,
            "pdf_pages": [1],
            "text": "营业收入为一百亿元，同比增长百分之十。",
            "source_file": "test.pdf",
            "source_url": "https://example.com/test.pdf",
        },
        {
            "chunk_id": "000002_2024_baseline_00000",
            "document_id": "000002_2024",
            "strategy": "fixed_char",
            "company": "另一公司",
            "stock_code": "000002",
            "report_year": 2024,
            "report_type": "年度报告全文",
            "chapter": "研发",
            "pdf_page_start": 2,
            "pdf_page_end": 2,
            "pdf_pages": [2],
            "text": "研发人员数量持续增加。",
            "source_file": "other.pdf",
            "source_url": "https://example.com/other.pdf",
        },
    ]
    (directory / "sample_baseline_chunks.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )


def test_chinese_tokenizer_and_bm25_metadata_filter(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    _write_chunks(chunks_dir)
    assert "营业收入" in tokenize("营业收入是多少？")
    hits = search_bm25(
        "营业收入",
        strategy="baseline",
        chunks_dir=chunks_dir,
        stock_code="000001",
        report_year=2025,
    )
    assert len(hits) == 1
    assert hits[0]["chunk_id"] == "000001_2025_baseline_00000"
    assert hits[0]["pdf_pages"] == [1]
    assert hits[0]["source_url"] == "https://example.com/test.pdf"
    assert search_bm25(
        "营业收入",
        strategy="baseline",
        chunks_dir=chunks_dir,
        stock_code="999999",
    ) == []


def test_chunk_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    _write_chunks(chunks_dir)
    original = chunks_dir / "sample_baseline_chunks.jsonl"
    (chunks_dir / "duplicate_baseline_chunks.jsonl").write_text(
        original.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Chunk ID不唯一"):
        load_strategy_chunks("baseline", chunks_dir=chunks_dir)


def test_rrf_deduplicates_and_preserves_audit_fields() -> None:
    common = {
        "chunk_id": "A",
        "score": 0.8,
        "text": "营业收入100元",
        "pdf_pages": [1],
        "source_url": "https://example.com",
    }
    vector = [dict(common, rank=1), dict(common, chunk_id="B", rank=2)]
    bm25 = [dict(common, rank=1, score=9.0)]
    hits = reciprocal_rank_fusion(vector, bm25, rrf_k=60)
    assert [hit["chunk_id"] for hit in hits] == ["A", "B"]
    assert hits[0]["vector_rank"] == 1
    assert hits[0]["bm25_rank"] == 1
    assert hits[0]["vector_score"] == 0.8
    assert hits[0]["bm25_score"] == 9.0


def test_reranker_promotes_term_and_numeric_match() -> None:
    hits = [
        {
            "rank": 1,
            "chunk_id": "A",
            "rrf_score": 0.02,
            "score": 0.02,
            "text": "公司持续发展。",
        },
        {
            "rank": 2,
            "chunk_id": "B",
            "rrf_score": 0.019,
            "score": 0.019,
            "text": "营业收入（元）803964958000.00。",
        },
    ]
    reranked = rerank_hits("营业收入是多少？", hits)
    assert reranked[0]["chunk_id"] == "B"
    assert reranked[0]["pre_rerank_rank"] == 2


def test_query_expansion_adds_table_semantics_for_balance() -> None:
    expanded = expand_query("2025年末存货余额是多少？")
    assert "账面价值" in expanded


def test_reranker_penalizes_implemented_plan_for_proposal_question() -> None:
    hits = [
        {
            "rank": 1,
            "chunk_id": "old",
            "rrf_score": 0.1,
            "score": 0.1,
            "text": "2024年度利润分配方案已实施完毕。",
        },
        {
            "rank": 2,
            "chunk_id": "proposal",
            "rrf_score": 0.09,
            "score": 0.09,
            "text": "2025年度利润分配预案为每10股派发现金红利。",
        },
    ]
    reranked = rerank_hits("公司2025年度拟如何分红？", hits)
    assert reranked[0]["chunk_id"] == "proposal"


def test_retrieval_config_validation(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "retrieval:\n  top_k: 5\n  candidate_pool: 4\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="candidate_pool"):
        load_retrieval_config(path)


def test_frozen_evaluation_set_has_not_changed() -> None:
    contents = (
        ROOT / "data" / "evaluation" / "evaluation_questions_template.csv"
    ).read_bytes()
    assert hashlib.sha256(contents).hexdigest() == (
        "3ba8632e46d54915ccf8ee2ab52e10dfd93c6045cfc8d012391ebb72918e676a"
    )
