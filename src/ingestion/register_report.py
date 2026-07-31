"""Validate an annual-report PDF and update its row in the manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data/manifests/annual_reports_manifest.csv"
DEFAULT_RAW_DIR = ROOT / "data/raw_pdf"


@dataclass(frozen=True)
class PdfInspection:
    page_count: int
    file_size: int
    sha256: str
    is_text_pdf: bool
    sample_text_chars: int
    matched_keywords: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_pdf(path: Path, keywords: list[str]) -> PdfInspection:
    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError("PDF 已加密，需要密码")
            if document.page_count == 0:
                raise ValueError("PDF 没有页面")

            page_count = document.page_count
            sample_pages = sorted({0, 1, 2, page_count // 2, page_count - 1})
            sample_text = "\n".join(
                document.load_page(page).get_text("text") for page in sample_pages
            )
    except (fitz.FileDataError, RuntimeError) as exc:
        raise ValueError(f"无法打开有效 PDF：{exc}") from exc

    compact_chars = sum(not char.isspace() for char in sample_text)
    matched = tuple(keyword for keyword in keywords if keyword in sample_text)
    return PdfInspection(
        page_count=page_count,
        file_size=path.stat().st_size,
        sha256=sha256_file(path),
        is_text_pdf=compact_chars >= 200,
        sample_text_chars=compact_chars,
        matched_keywords=matched,
    )


def load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("Manifest 缺少表头")
        return list(reader.fieldnames), list(reader)


def write_manifest_atomic(
    path: Path, fieldnames: list[str], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def register_report(
    *,
    input_pdf: Path,
    document_id: str,
    source_url: str,
    publish_date: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    raw_dir: Path = DEFAULT_RAW_DIR,
    copy_file: bool = True,
) -> tuple[Path, PdfInspection]:
    fieldnames, rows = load_manifest(manifest_path)
    matches = [row for row in rows if row["document_id"] == document_id]
    if len(matches) != 1:
        raise ValueError(
            f"document_id={document_id!r} 在 Manifest 中应恰好出现一次，实际 {len(matches)} 次"
        )

    row = matches[0]
    expected_name = row["file_name"]
    destination = raw_dir / expected_name
    keywords = [
        row["company_short_name"],
        str(row["report_year"]),
        "年度报告",
    ]
    inspection = inspect_pdf(input_pdf, keywords)

    missing = [keyword for keyword in keywords if keyword not in inspection.matched_keywords]
    if missing:
        raise ValueError(f"PDF 抽样文本未匹配关键标识：{', '.join(missing)}")
    if not inspection.is_text_pdf:
        raise ValueError(
            f"PDF 抽样页仅提取到 {inspection.sample_text_chars} 个非空白字符，"
            "疑似扫描件，未自动登记"
        )

    if destination.exists() and destination.resolve() != input_pdf.resolve():
        existing_hash = sha256_file(destination)
        if existing_hash != inspection.sha256:
            raise FileExistsError(f"目标文件已存在且内容不同：{destination}")

    if copy_file and destination.resolve() != input_pdf.resolve():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_pdf, destination)

    row.update(
        {
            "publish_date": publish_date,
            "source_url": source_url,
            "local_path": f"data/raw_pdf/{expected_name}",
            "file_name": expected_name,
            "file_hash": inspection.sha256,
            "file_size": str(inspection.file_size),
            "page_count": str(inspection.page_count),
            "is_text_pdf": "true",
            "parse_status": "pending",
            "notes": "工具验收通过：PDF可打开、关键标识匹配、正文可提取；待页面解析",
        }
    )
    write_manifest_atomic(manifest_path, fieldnames, rows)
    return destination, inspection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="验收年度报告 PDF，并自动回填 annual_reports_manifest.csv"
    )
    parser.add_argument("pdf", type=Path, help="待登记的 PDF 文件")
    parser.add_argument("--document-id", required=True, help="例如 002594_2025")
    parser.add_argument("--source-url", required=True, help="原始 PDF 下载地址")
    parser.add_argument("--publish-date", required=True, help="正式披露日期 YYYY-MM-DD")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="文件已在 raw_pdf 时只验收和登记，不复制",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        destination, result = register_report(
            input_pdf=args.pdf.resolve(),
            document_id=args.document_id,
            source_url=args.source_url,
            publish_date=args.publish_date,
            manifest_path=args.manifest.resolve(),
            raw_dir=args.raw_dir.resolve(),
            copy_file=not args.no_copy,
        )
    except (OSError, ValueError) as exc:
        print(f"登记失败：{exc}", file=sys.stderr)
        return 1

    print("登记成功")
    print(f"文件：{destination}")
    print(f"页数：{result.page_count}")
    print(f"大小：{result.file_size} bytes")
    print(f"SHA-256：{result.sha256}")
    print(f"文本型 PDF：{str(result.is_text_pdf).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
