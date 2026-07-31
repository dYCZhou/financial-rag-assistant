import csv
import json
from pathlib import Path

import fitz

from src.parsing.parse_report import parse_report


FIELDS = [
    "document_id", "company_name", "company_short_name", "stock_code",
    "report_year", "publish_date", "report_type", "source_url", "local_path",
    "file_name", "file_hash", "file_size", "page_count", "is_text_pdf",
    "parse_status", "notes",
]


def test_parse_report_outputs_traceable_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    for number in range(1, 5):
        page = document.new_page()
        page.insert_text((72, 50), "TEST COMPANY 2025 ANNUAL REPORT")
        page.insert_text((72, 100), f"Page {number} body " + "Revenue increased. " * 30)
        page.insert_text((72, 780), str(number))
    document.save(pdf_path)
    document.close()

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow({
            "document_id": "000001_2025",
            "company_name": "测试公司股份有限公司",
            "company_short_name": "测试公司",
            "stock_code": "000001",
            "report_year": "2025",
            "report_type": "年度报告全文",
            "source_url": "https://example.com/report.pdf",
            "local_path": str(pdf_path),
            "file_name": pdf_path.name,
            "file_hash": "accepted",
            "file_size": str(pdf_path.stat().st_size),
            "page_count": "4",
            "is_text_pdf": "true",
            "parse_status": "pending",
            "notes": "",
        })

    # The parser resolves absolute local_path values without changing them.
    output, report_path, report = parse_report(
        document_id="000001_2025",
        manifest_path=manifest,
        parsed_dir=tmp_path / "parsed",
        reports_dir=tmp_path / "reports",
    )

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 4
    assert [item["pdf_page"] for item in records] == [1, 2, 3, 4]
    assert all(item["document_id"] == "000001_2025" for item in records)
    assert all(item["parse_method"] == "pymupdf" for item in records)
    assert report_path.exists()
    assert report["page_count"] == 4
    assert "TEST COMPANY 2025 ANNUAL REPORT" in report["repeated_margin_lines_removed"]

    with manifest.open("r", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["parse_status"] == "parsed"
