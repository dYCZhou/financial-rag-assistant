import csv
import json
from pathlib import Path

import pytest

from src.chunking.structured_chunker import (
    make_structured_chunks,
    structured_chunk_report,
)

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


def prose_pages() -> list[dict[str, object]]:
    pages = sample_pages()
    pages[0]["text"] = "第一段内容完整结束。" * 18 + "\n第二段继续说明；" * 10
    pages[1]["text"] = "本页延续第一节内容。" * 25
    pages[2]["text"] = "第二节的新内容。" * 30
    return pages


def test_structured_chunks_do_not_cross_chapters_and_keep_page_metadata() -> None:
    chunks = make_structured_chunks(
        prose_pages(),
        target_chars=180,
        max_chars=240,
        overlap_chars=40,
        max_unit_chars=100,
    )
    assert chunks
    assert all(len(chunk.chapters) <= 1 for chunk in chunks)
    assert all(chunk.char_count <= 240 for chunk in chunks)
    assert all(chunk.pdf_pages for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_invalid_structured_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        make_structured_chunks(
            prose_pages(),
            target_chars=300,
            max_chars=200,
            overlap_chars=20,
        )


def test_structured_report_updates_manifest(tmp_path: Path) -> None:
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    (parsed_dir / "000001_2025_pages.jsonl").write_text(
        "\n".join(json.dumps(page, ensure_ascii=False) for page in prose_pages()) + "\n",
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
            "parse_status": "baseline_chunked",
        })
    output, report_path, report = structured_chunk_report(
        document_id="000001_2025",
        manifest_path=manifest,
        parsed_dir=parsed_dir,
        chunks_dir=tmp_path / "chunks",
        reports_dir=tmp_path / "reports",
        target_chars=180,
        max_chars=240,
        overlap_chars=40,
        max_unit_chars=100,
    )
    assert output.exists() and report_path.exists()
    assert report["chunks_crossing_chapters"] == 0
    with manifest.open(encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["parse_status"] == "structured_chunked"
