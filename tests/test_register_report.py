import csv
import unittest
from pathlib import Path

import fitz

from src.ingestion.register_report import register_report


FIELDS = [
    "document_id",
    "company_name",
    "company_short_name",
    "stock_code",
    "report_year",
    "publish_date",
    "report_type",
    "source_url",
    "local_path",
    "file_name",
    "file_hash",
    "file_size",
    "page_count",
    "is_text_pdf",
    "parse_status",
    "notes",
]


def make_manifest(path: Path) -> None:
    row = dict.fromkeys(FIELDS, "")
    row.update(
        {
            "document_id": "002594_2025",
            "company_name": "比亚迪股份有限公司",
            "company_short_name": "比亚迪",
            "stock_code": "002594",
            "report_year": "2025",
            "report_type": "年度报告全文",
            "file_name": "002594_比亚迪_2025_annual_report.pdf",
            "parse_status": "pending",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)


def make_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    for _ in range(5):
        page = document.new_page()
        page.insert_textbox(
            fitz.Rect(50, 50, 545, 792),
            "\n".join([text] * 8),
            fontsize=10,
            fontname="china-s",
        )
    document.save(path)
    document.close()


def test_registers_valid_pdf(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    raw_dir = tmp_path / "raw"
    source = tmp_path / "source.pdf"
    make_manifest(manifest)
    make_pdf(source, "BYD 比亚迪 2025 年度报告 正文内容与财务数据")

    destination, inspection = register_report(
        input_pdf=source,
        document_id="002594_2025",
        source_url="https://example.com/report.pdf",
        publish_date="2026-03-28",
        manifest_path=manifest,
        raw_dir=raw_dir,
    )

    assert destination.exists()
    assert inspection.page_count == 5
    with manifest.open(encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["file_hash"] == inspection.sha256
    assert row["is_text_pdf"] == "true"
    assert row["parse_status"] == "pending"


def test_rejects_wrong_report(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    source = tmp_path / "wrong.pdf"
    make_manifest(manifest)
    make_pdf(source, "Unrelated document with enough body text for validation")

    with unittest.TestCase().assertRaisesRegex(ValueError, "关键标识"):
        register_report(
            input_pdf=source,
            document_id="002594_2025",
            source_url="https://example.com/wrong.pdf",
            publish_date="2026-03-28",
            manifest_path=manifest,
            raw_dir=tmp_path / "raw",
        )
