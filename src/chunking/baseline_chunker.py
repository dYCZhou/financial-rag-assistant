"""Create a reproducible fixed-length chunking baseline from page JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.parsing.parse_report import (
    DEFAULT_MANIFEST,
    ROOT,
    compact_char_count,
    load_manifest_row,
    write_manifest_atomic,
)


DEFAULT_PARSED_DIR = ROOT / "data/parsed"
DEFAULT_CHUNKS_DIR = ROOT / "data/chunks"
DEFAULT_REPORTS_DIR = ROOT / "reports"


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    company: str
    stock_code: str
    report_year: int
    report_type: str
    chapter: str
    chapters: list[str]
    pdf_page_start: int
    pdf_page_end: int
    pdf_pages: list[int]
    printed_pages: list[int]
    text: str
    char_count: int
    source_file: str
    source_url: str


def load_pages(path: Path) -> list[dict[str, object]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"页面数据为空：{path}")
    document_ids = {str(item.get("document_id", "")) for item in records}
    if len(document_ids) != 1:
        raise ValueError("页面JSONL混入了多个document_id")
    actual_pages = [int(item["pdf_page"]) for item in records]
    if actual_pages != list(range(1, len(records) + 1)):
        raise ValueError("页面JSONL中的PDF物理页码不连续")
    return records


def build_corpus(
    pages: list[dict[str, object]],
) -> tuple[str, list[tuple[int, int, dict[str, object]]]]:
    """Join non-empty pages and retain exact character intervals for citations."""
    parts: list[str] = []
    spans: list[tuple[int, int, dict[str, object]]] = []
    cursor = 0
    for page in pages:
        text = str(page.get("text", "")).strip()
        if not text:
            continue
        if parts:
            separator = "\n\n"
            parts.append(separator)
            cursor += len(separator)
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append((start, cursor, page))
    return "".join(parts), spans


def unique_in_order(values: list[object]) -> list[object]:
    return list(dict.fromkeys(values))


def make_chunks(
    pages: list[dict[str, object]],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[ChunkRecord]:
    if chunk_size <= 0:
        raise ValueError("chunk_size必须大于0")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap必须满足 0 <= overlap < chunk_size")

    corpus, spans = build_corpus(pages)
    if not corpus:
        raise ValueError("没有可切分的正文")

    first = pages[0]
    records: list[ChunkRecord] = []
    step = chunk_size - chunk_overlap
    for start in range(0, len(corpus), step):
        end = min(start + chunk_size, len(corpus))
        text = corpus[start:end].strip()
        if not text:
            continue
        contributing = [
            page for page_start, page_end, page in spans
            if page_start < end and page_end > start
        ]
        if not contributing:
            raise RuntimeError("Chunk未能映射回任何PDF页面")
        pdf_pages = unique_in_order([int(page["pdf_page"]) for page in contributing])
        printed_pages = unique_in_order([
            int(page["printed_page"])
            for page in contributing
            if page.get("printed_page") is not None
        ])
        chapters = unique_in_order([
            str(page.get("chapter", "unknown"))
            for page in contributing
            if str(page.get("chapter", "unknown")) != "unknown"
        ])
        index = len(records)
        records.append(
            ChunkRecord(
                chunk_id=f"{first['document_id']}_baseline_{index:05d}",
                document_id=str(first["document_id"]),
                chunk_index=index,
                strategy="fixed_char",
                company=str(first["company"]),
                stock_code=str(first["stock_code"]),
                report_year=int(first["report_year"]),
                report_type=str(first["report_type"]),
                chapter=str(chapters[0]) if chapters else "unknown",
                chapters=[str(item) for item in chapters],
                pdf_page_start=int(pdf_pages[0]),
                pdf_page_end=int(pdf_pages[-1]),
                pdf_pages=[int(item) for item in pdf_pages],
                printed_pages=[int(item) for item in printed_pages],
                text=text,
                char_count=compact_char_count(text),
                source_file=str(first["source_file"]),
                source_url=str(first["source_url"]),
            )
        )
        if end == len(corpus):
            break
    return records


def chunk_report(
    *,
    document_id: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> tuple[Path, Path, dict[str, object]]:
    fieldnames, manifest_rows, manifest_row = load_manifest_row(manifest_path, document_id)
    if manifest_row.get("parse_status") not in {"audited", "baseline_chunked"}:
        raise ValueError("报告尚未通过页面人工抽查，不能进入基线切分")

    parsed_path = parsed_dir / f"{document_id}_pages.jsonl"
    if not parsed_path.exists():
        raise FileNotFoundError(f"缺少页面数据：{parsed_path}")
    pages = load_pages(parsed_path)
    if str(pages[0]["document_id"]) != document_id:
        raise ValueError("页面数据与请求的document_id不一致")

    chunks = make_chunks(
        pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = chunks_dir / f"{document_id}_baseline_chunks.jsonl"
    report_path = reports_dir / f"{document_id}_baseline_chunk_quality.json"

    with output_path.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            stream.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    counts = [chunk.char_count for chunk in chunks]
    report: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "fixed_char",
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "chunk_count": len(chunks),
        "source_page_count": len(pages),
        "source_nonempty_page_count": sum(bool(str(page.get("text", "")).strip()) for page in pages),
        "chunks_crossing_pages": sum(chunk.pdf_page_start != chunk.pdf_page_end for chunk in chunks),
        "chunks_crossing_chapters": sum(len(chunk.chapters) > 1 for chunk in chunks),
        "min_compact_char_count": min(counts),
        "max_compact_char_count": max(counts),
        "average_compact_char_count": round(sum(counts) / len(counts), 2),
        "first_chunk_id": chunks[0].chunk_id,
        "last_chunk_id": chunks[-1].chunk_id,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_row["parse_status"] = "baseline_chunked"
    manifest_row["notes"] = (
        f"固定长度切分基线完成：size={chunk_size}，overlap={chunk_overlap}，"
        f"共{len(chunks)}个Chunk；待Chunk抽查与检索评估"
    )
    write_manifest_atomic(manifest_path, fieldnames, manifest_rows)
    return output_path, report_path, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成固定字符长度的切分基线")
    parser.add_argument("--document-id", required=True, help="例如 002594_2025")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_DIR)
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output, report_path, report = chunk_report(
            document_id=args.document_id,
            manifest_path=args.manifest.resolve(),
            parsed_dir=args.parsed_dir.resolve(),
            chunks_dir=args.chunks_dir.resolve(),
            reports_dir=args.reports_dir.resolve(),
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"切分失败：{exc}", file=sys.stderr)
        return 1
    print("切分成功")
    print(f"Chunk数据：{output}")
    print(f"质量报告：{report_path}")
    print(f"Chunk数量：{report['chunk_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
