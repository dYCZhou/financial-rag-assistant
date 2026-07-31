import pytest

from src.chunking.compare_strategies import compare_reports


def test_compare_reports_requires_same_source() -> None:
    baseline = {
        "document_id": "doc",
        "source_page_count": 10,
        "strategy": "fixed_char",
        "chunk_count": 20,
        "chunks_crossing_pages": 12,
        "chunks_crossing_chapters": 5,
        "average_compact_char_count": 700,
    }
    structured = {
        "document_id": "doc",
        "source_page_count": 10,
        "strategy": "chapter_paragraph",
        "chunk_count": 22,
        "chunks_crossing_pages": 8,
        "chunks_crossing_chapters": 0,
        "average_compact_char_count": 680,
        "natural_ending_rate": 0.8,
    }
    result = compare_reports(baseline, structured)
    assert result["differences"]["cross_chapter_chunk_change"] == -5
    assert result["differences"]["cross_page_chunk_change_rate"] == -0.3333

    structured["source_page_count"] = 9
    with pytest.raises(ValueError):
        compare_reports(baseline, structured)
