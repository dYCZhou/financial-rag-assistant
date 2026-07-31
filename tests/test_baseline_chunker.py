import csv
import json
from pathlib import Path

import pytest

from src.chunking.baseline_chunker import chunk_report, make_chunks


FIELDS = [
    "document_id", "company_name", "company_short_name", "stock_code",
    "report_year", "publish_date", "report_type", "source_url", "local_path",
    "file_name", "file_hash", "file_size", "page_count", "is_text_pdf",
    "parse_status", "notes",
]


def sample_pages() -> list[dict[str, object]]:
    return [
        {
            "document_id": "000001_2025",
            "company": "测试公司",
            "stock_code": "000001",
            "report_year": 2025,
            "report_type": "年度报告全文",
            "pdf_page": number,
            "printed_page": number,
            "chapter": "第一节 测试" if number < 3 else "第二节 测试",
            "text": chr(64 + number) * 90,
            "source_file": "sample.pdf",
            "source_url": "https://example.com/sample.pdf",
        }
        for number in range(1, 4)
    ]


def test_make_chunks_preserves_page_traceability_and_overlap() -> None:
    chunks = make_chunks(sample_pages(), chunk_size=120, chunk_overlap=20)
    assert len(chunks) == 3
    assert chunks[0].pdf_pages == [1, 2]
    assert chunks[1].pdf_pages == [2, 3]
    assert chunks[1].chapters == ["第一节 测试", "第二节 测试"]
    assert chunks[0].text[-20:] == chunks[1].text[:20]
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_invalid_overlap_is_rejected() -> None:
    with pytest.raises(ValueError):
        make_chunks(sample_pages(), chunk_size=100, chunk_overlap=100)


def test_chunk_report_requires_audited_input_and_updates_manifest(tmp_path: Path) -> None:
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    parsed_path = parsed_dir / "000001_2025_pages.jsonl"
    parsed_path.write_text(
        "\n".join(json.dumps(page, ensure_ascii=False) for page in sample_pages()) + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow({
            "document_id": "000001_2025",
            "company_name": "测试公司",
            "company_short_name": "测试",
            "stock_code": "000001",
            "report_year": "2025",
            "report_type": "年度报告全文",
            "parse_status": "audited",
        })

    output, report_path, report = chunk_report(
        document_id="000001_2025",
        manifest_path=manifest,
        parsed_dir=parsed_dir,
        chunks_dir=tmp_path / "chunks",
        reports_dir=tmp_path / "reports",
        chunk_size=120,
        chunk_overlap=20,
    )
    assert output.exists()
    assert report_path.exists()
    assert report["chunk_count"] == 3
    with manifest.open("r", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["parse_status"] == "baseline_chunked"
