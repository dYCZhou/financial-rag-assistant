import csv
from pathlib import Path

import pytest

from src.evaluation.evaluate_retrieval import (
    first_relevant_rank,
    load_questions,
    parse_evidence_pages,
)


def test_parse_evidence_pages_supports_lists_and_ranges() -> None:
    assert parse_evidence_pages("11|29-31|252") == {11, 29, 30, 31, 252}
    with pytest.raises(ValueError):
        parse_evidence_pages("")
    with pytest.raises(ValueError):
        parse_evidence_pages("31-29")


def test_first_relevant_rank_uses_page_overlap() -> None:
    hits = [
        {"rank": 1, "pdf_pages": [8, 9]},
        {"rank": 2, "pdf_pages": [10, 11]},
    ]
    assert first_relevant_rank(hits, {11}) == 2
    assert first_relevant_rank(hits, {20}) is None


def test_load_questions_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "questions.csv"
    fields = [
        "question_id",
        "question",
        "target_stock_code",
        "target_year",
        "evidence_pages",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            {
                "question_id": "Q1",
                "question": "问题一",
                "target_stock_code": "002594",
                "target_year": "2025",
                "evidence_pages": "11",
            },
            {
                "question_id": "Q1",
                "question": "问题二",
                "target_stock_code": "002594",
                "target_year": "2025",
                "evidence_pages": "12",
            },
        ])
    with pytest.raises(ValueError):
        load_questions(path)
