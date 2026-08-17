import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_newly_audited_report_has_a_valid_independent_frozen_set() -> None:
    document_ids = [
        "300750_2023", "300750_2025",
        "600519_2023", "600519_2024", "600519_2025",
        "000333_2023", "000333_2024", "000333_2025",
        "600941_2023", "600941_2024", "600941_2025",
    ]

    question_ids: set[str] = set()
    for document_id in document_ids:
        csv_path = ROOT / f"data/evaluation/{document_id}_evaluation_questions.csv"
        freeze_path = ROOT / f"reports/{document_id}_evaluation_set_freeze.json"
        assert csv_path.is_file(), document_id
        assert freeze_path.is_file(), document_id

        with csv_path.open(encoding="utf-8", newline="") as handle:
            questions = list(csv.DictReader(handle))
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))

        assert len(questions) == freeze["question_count"] == 15
        assert freeze["document_id"] == document_id
        assert freeze["frozen_before_first_retrieval_run"] is True
        assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == freeze["sha256"]
        for question in questions:
            assert question["question_id"] not in question_ids
            question_ids.add(question["question_id"])
            assert question["reference_answer"]
            assert question["evidence_pages"]
            assert question["evidence_text"]

    assert len(question_ids) == 15 * len(document_ids)
