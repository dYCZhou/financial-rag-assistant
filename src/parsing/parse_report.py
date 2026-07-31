"""Parse an accepted annual-report PDF into traceable page-level JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data/manifests/annual_reports_manifest.csv"
DEFAULT_PARSED_DIR = ROOT / "data/parsed"
DEFAULT_REPORTS_DIR = ROOT / "reports"
DEFAULT_LOGS_DIR = ROOT / "logs"

WHITESPACE_RE = re.compile(r"[ \t\u3000]+")
EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
PRINTED_PAGE_PATTERNS = (
    re.compile(r"^\s*[-—–]?\s*(\d{1,4})\s*[-—–]?\s*$"),
    re.compile(r"^\s*第\s*(\d{1,4})\s*页\s*$"),
)
CHAPTER_PATTERNS = (
    re.compile(r"^第[一二三四五六七八九十百]+节\s+.+$"),
    re.compile(r"^第[一二三四五六七八九十百]+章\s+.+$"),
    re.compile(r"^[一二三四五六七八九十]+、\s*[^，。；]{2,40}$"),
)


@dataclass(frozen=True)
class PageRecord:
    document_id: str
    company: str
    stock_code: str
    report_year: int
    report_type: str
    pdf_page: int
    printed_page: int | None
    chapter: str
    text: str
    source_file: str
    source_url: str
    parse_method: str
    char_count: int
    quality_flags: list[str]


def compact_char_count(text: str) -> int:
    return sum(not char.isspace() for char in text)


def normalize_line(line: str) -> str:
    return WHITESPACE_RE.sub(" ", line).strip()


def normalize_text(lines: list[str]) -> str:
    cleaned = "\n".join(line for line in lines if line)
    return EXCESS_NEWLINES_RE.sub("\n\n", cleaned).strip()


def load_manifest_row(path: Path, document_id: str) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("Manifest 缺少表头")
        rows = list(reader)
        fieldnames = list(reader.fieldnames)
    matches = [row for row in rows if row["document_id"] == document_id]
    if len(matches) != 1:
        raise ValueError(
            f"document_id={document_id!r} 在 Manifest 中应恰好出现一次，实际 {len(matches)} 次"
        )
    return fieldnames, rows, matches[0]


def write_manifest_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with open(descriptor, "w", encoding="utf-8", newline="", closefd=True) as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def collect_repeated_margin_lines(
    page_lines: list[list[str]], *, min_ratio: float = 0.30
) -> set[str]:
    """Find short lines repeated in top/bottom margins on many pages."""
    counter: Counter[str] = Counter()
    for lines in page_lines:
        candidates = set(lines[:3] + lines[-3:])
        counter.update(
            line for line in candidates if 2 <= len(line) <= 80 and not line.isdigit()
        )
    threshold = max(3, round(len(page_lines) * min_ratio))
    return {line for line, count in counter.items() if count >= threshold}


def detect_printed_page(lines: list[str]) -> int | None:
    for line in lines[:3] + lines[-3:]:
        for pattern in PRINTED_PAGE_PATTERNS:
            match = pattern.match(line)
            if match:
                value = int(match.group(1))
                if value > 0:
                    return value
    return None


def detect_chapter(lines: list[str], previous: str) -> str:
    for line in lines[:12]:
        if len(line) <= 60 and any(pattern.match(line) for pattern in CHAPTER_PATTERNS):
            return line
    return previous


def quality_flags(raw_text: str, cleaned_text: str, min_page_chars: int) -> list[str]:
    flags: list[str] = []
    count = compact_char_count(cleaned_text)
    if not raw_text.strip():
        flags.append("empty_page")
    elif count < min_page_chars:
        flags.append("short_page")
    if "\ufffd" in cleaned_text:
        flags.append("replacement_character")
    if cleaned_text and cleaned_text.count("\x00"):
        flags.append("null_character")
    return flags


def parse_report(
    *,
    document_id: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    min_page_chars: int = 50,
) -> tuple[Path, Path, dict[str, object]]:
    fieldnames, rows, row = load_manifest_row(manifest_path, document_id)
    if not row.get("file_hash") or row.get("is_text_pdf", "").lower() != "true":
        raise ValueError("该报告尚未通过阶段1 PDF验收，不能进入页面解析")

    pdf_path = ROOT / row["local_path"]
    if not pdf_path.exists():
        raise FileNotFoundError(f"Manifest 指向的 PDF 不存在：{pdf_path}")

    with fitz.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError("PDF 已加密，需要密码")
        raw_texts = [page.get_text("text", sort=True) for page in document]

    page_lines = [
        [normalized for line in text.splitlines() if (normalized := normalize_line(line))]
        for text in raw_texts
    ]
    repeated_margin_lines = collect_repeated_margin_lines(page_lines)

    records: list[PageRecord] = []
    current_chapter = "unknown"
    for index, (raw_text, lines) in enumerate(zip(raw_texts, page_lines), start=1):
        printed_page = detect_printed_page(lines)
        content_lines = [line for line in lines if line not in repeated_margin_lines]
        cleaned_text = normalize_text(content_lines)
        current_chapter = detect_chapter(content_lines, current_chapter)
        flags = quality_flags(raw_text, cleaned_text, min_page_chars)
        records.append(
            PageRecord(
                document_id=document_id,
                company=row["company_name"],
                stock_code=row["stock_code"],
                report_year=int(row["report_year"]),
                report_type=row["report_type"],
                pdf_page=index,
                printed_page=printed_page,
                chapter=current_chapter,
                text=cleaned_text,
                source_file=row["file_name"],
                source_url=row["source_url"],
                parse_method="pymupdf",
                char_count=compact_char_count(cleaned_text),
                quality_flags=flags,
            )
        )

    parsed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = parsed_dir / f"{document_id}_pages.jsonl"
    report_path = reports_dir / f"{document_id}_parse_quality.json"

    with output_path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    flag_counts = Counter(flag for record in records for flag in record.quality_flags)
    total_chars = sum(record.char_count for record in records)
    report: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": row["file_name"],
        "page_count": len(records),
        "manifest_page_count": int(row["page_count"]),
        "total_char_count": total_chars,
        "average_chars_per_page": round(total_chars / len(records), 2),
        "pages_with_printed_page": sum(record.printed_page is not None for record in records),
        "pages_with_known_chapter": sum(record.chapter != "unknown" for record in records),
        "repeated_margin_lines_removed": sorted(repeated_margin_lines),
        "quality_flag_counts": dict(sorted(flag_counts.items())),
        "flagged_pages": [
            {"pdf_page": record.pdf_page, "flags": record.quality_flags, "char_count": record.char_count}
            for record in records
            if record.quality_flags
        ],
    }
    with report_path.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    if len(records) != int(row["page_count"]):
        raise ValueError("解析页数与 Manifest 登记页数不一致，未更新解析状态")
    row["parse_status"] = "parsed"
    row["notes"] = (
        f"页面解析完成：{len(records)}页，{total_chars}字符，"
        f"异常页{len(report['flagged_pages'])}页；待人工抽查"
    )
    write_manifest_atomic(manifest_path, fieldnames, rows)
    return output_path, report_path, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将已验收年报解析为页面级 JSONL")
    parser.add_argument("--document-id", required=True, help="例如 002594_2025")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--min-page-chars", type=int, default=50)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        output, report_path, report = parse_report(
            document_id=args.document_id,
            manifest_path=args.manifest.resolve(),
            parsed_dir=args.parsed_dir.resolve(),
            reports_dir=args.reports_dir.resolve(),
            min_page_chars=args.min_page_chars,
        )
    except (OSError, ValueError, fitz.FileDataError) as exc:
        print(f"解析失败：{exc}", file=sys.stderr)
        return 1
    print("解析成功")
    print(f"页面数据：{output}")
    print(f"质量报告：{report_path}")
    print(f"页数：{report['page_count']}")
    print(f"异常页：{len(report['flagged_pages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
