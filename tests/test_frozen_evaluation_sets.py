import csv
import json
from pathlib import Path

from src.evaluation.frozen_sets import frozen_sha256, manifest_document_ids


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/annual_reports_manifest.csv"
INVENTORY = ROOT / "reports/issue-3_evaluation_asset_inventory.json"


def test_every_newly_audited_report_has_a_valid_independent_frozen_set() -> None:
    document_ids = manifest_document_ids(
        MANIFEST, accepted_status="retrieval_quality_accepted"
    )
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))["documents"]
    assert set(inventory) == set(document_ids)

    question_ids: set[str] = set()
    for document_id in document_ids:
        csv_path = ROOT / f"data/evaluation/{document_id}_evaluation_questions.csv"
        freeze_path = ROOT / f"reports/{document_id}_evaluation_set_freeze.json"
        status = inventory[document_id]
        if status["status"] == "missing":
            assert not csv_path.exists()
            assert not freeze_path.exists()
            assert status["reason"]
            continue

        assert status["status"] == "available", document_id
        assert csv_path.is_file(), document_id
        assert freeze_path.is_file(), document_id

        with csv_path.open(encoding="utf-8", newline="") as handle:
            questions = list(csv.DictReader(handle))
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))

        assert len(questions) == freeze["question_count"] == 15
        assert freeze["document_id"] == document_id
        assert freeze.get("frozen_before_first_retrieval_run", freeze.get("frozen_before_first_evaluation")) is True
        assert frozen_sha256(csv_path) == freeze["sha256"]
        for question in questions:
            assert question["question_id"] not in question_ids
            question_ids.add(question["question_id"])
            assert question["reference_answer"]
            assert question["evidence_pages"]
            assert question["evidence_text"]

    available_count = sum(
        1 for document_id in document_ids if inventory[document_id]["status"] == "available"
    )
    assert len(question_ids) == 15 * available_count


def test_frozen_hash_is_identical_for_lf_and_crlf(tmp_path: Path) -> None:
    lf = tmp_path / "lf.csv"
    crlf = tmp_path / "crlf.csv"
    content = "question_id,question\nQ01,示例问题\n"
    lf.write_bytes(content.encode("utf-8"))
    crlf.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    assert frozen_sha256(lf) == frozen_sha256(crlf)
