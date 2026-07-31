"""Create chapter- and paragraph-aware chunks from page-level annual-report text."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.chunking.baseline_chunker import (
    DEFAULT_CHUNKS_DIR,
    DEFAULT_PARSED_DIR,
    DEFAULT_REPORTS_DIR,
    ChunkRecord,
    load_pages,
    unique_in_order,
)
from src.parsing.parse_report import (
    DEFAULT_MANIFEST,
    compact_char_count,
    load_manifest_row,
    write_manifest_atomic,
)

SENTENCE_END_RE = re.compile(r"(?<=[。！？；])")
HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百]+[章节]|[一二三四五六七八九十]+、)"
)


@dataclass(frozen=True)
class TextUnit:
    text: str
    pdf_page: int
    printed_page: int | None
    chapter: str


def split_long_text(text: str, max_chars: int) -> list[str]:
    sentences = [item.strip() for item in SENTENCE_END_RE.split(text) if item.strip()]
    if len(sentences) <= 1:
        return [text[start:start + max_chars] for start in range(0, len(text), max_chars)]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(
                sentence[start:start + max_chars]
                for start in range(0, len(sentence), max_chars)
            )
        elif current and len(current) + len(sentence) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        parts.append(current)
    return parts


def page_to_units(page: dict[str, object], *, max_unit_chars: int) -> list[TextUnit]:
    """Group adjacent PDF text lines into paragraph-like, traceable units."""
    text = str(page.get("text", "")).strip()
    if not text:
        return []
    chapter = str(page.get("chapter", "unknown"))
    units: list[str] = []
    current: list[str] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if current:
            block = "\n".join(current).strip()
            units.extend(split_long_text(block, max_unit_chars))
            current = []
            current_chars = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        is_heading = bool(HEADING_RE.match(line)) and len(line) <= 80
        if is_heading:
            flush()
            units.append(line)
            continue
        if current and current_chars + len(line) > max_unit_chars:
            flush()
        current.append(line)
        current_chars += len(line)
        if line.endswith(("。", "！", "？", "；")) and current_chars >= max_unit_chars // 2:
            flush()
    flush()

    return [
        TextUnit(
            text=unit,
            pdf_page=int(page["pdf_page"]),
            printed_page=(
                int(page["printed_page"])
                if page.get("printed_page") is not None
                else None
            ),
            chapter=chapter,
        )
        for unit in units
        if unit.strip()
    ]


def make_structured_chunks(
    pages: list[dict[str, object]],
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
    max_unit_chars: int = 400,
) -> list[ChunkRecord]:
    if not 0 < target_chars <= max_chars:
        raise ValueError("必须满足 0 < target_chars <= max_chars")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap_chars必须满足 0 <= overlap < target_chars")
    if max_unit_chars <= 0 or max_unit_chars > max_chars:
        raise ValueError("max_unit_chars必须大于0且不超过max_chars")

    all_units = [
        unit
        for page in pages
        for unit in page_to_units(page, max_unit_chars=max_unit_chars)
    ]
    if not all_units:
        raise ValueError("没有可切分的正文")

    first = pages[0]
    records: list[ChunkRecord] = []
    current: list[TextUnit] = []
    has_new_content = False

    def current_length(units: list[TextUnit]) -> int:
        return len("\n\n".join(unit.text for unit in units))

    def emit(*, keep_overlap: bool) -> None:
        nonlocal current, has_new_content
        if not current or not has_new_content:
            return
        text = "\n\n".join(unit.text for unit in current).strip()
        pdf_pages = unique_in_order([unit.pdf_page for unit in current])
        printed_pages = unique_in_order([
            unit.printed_page for unit in current if unit.printed_page is not None
        ])
        chapters = unique_in_order([
            unit.chapter for unit in current if unit.chapter != "unknown"
        ])
        index = len(records)
        records.append(
            ChunkRecord(
                chunk_id=f"{first['document_id']}_structured_{index:05d}",
                document_id=str(first["document_id"]),
                chunk_index=index,
                strategy="chapter_paragraph",
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
        carry: list[TextUnit] = []
        carry_chars = 0
        for unit in reversed(current):
            if carry and carry_chars + len(unit.text) > overlap_chars:
                break
            carry.insert(0, unit)
            carry_chars += len(unit.text)
            if carry_chars >= overlap_chars:
                break
        current = carry if keep_overlap and overlap_chars else []
        has_new_content = False

    for unit in all_units:
        if current and unit.chapter != current[-1].chapter:
            emit(keep_overlap=False)
            current = []
            has_new_content = False
        if current and current_length(current + [unit]) > max_chars:
            emit(keep_overlap=True)
        current.append(unit)
        has_new_content = True
        if current_length(current) >= target_chars:
            emit(keep_overlap=True)
    emit(keep_overlap=False)
    return records


def structured_chunk_report(
    *,
    document_id: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    target_chars: int = 800,
    max_chars: int = 1000,
    overlap_chars: int = 150,
    max_unit_chars: int = 400,
) -> tuple[Path, Path, dict[str, object]]:
    fieldnames, manifest_rows, row = load_manifest_row(manifest_path, document_id)
    if row.get("parse_status") not in {"baseline_chunked", "structured_chunked"}:
        raise ValueError("必须先完成页面抽查和固定长度基线，才能运行优化切分")
    parsed_path = parsed_dir / f"{document_id}_pages.jsonl"
    pages = load_pages(parsed_path)
    chunks = make_structured_chunks(
        pages,
        target_chars=target_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        max_unit_chars=max_unit_chars,
    )
    chunks_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = chunks_dir / f"{document_id}_structured_chunks.jsonl"
    report_path = reports_dir / f"{document_id}_structured_chunk_quality.json"
    with output_path.open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            stream.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")

    counts = [chunk.char_count for chunk in chunks]
    natural_endings = ("。", "！", "？", "；", "：")
    natural_count = sum(
        chunk.text.rstrip().endswith(natural_endings) for chunk in chunks
    )
    report: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "chapter_paragraph",
        "target_chars": target_chars,
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "max_unit_chars": max_unit_chars,
        "chunk_count": len(chunks),
        "source_page_count": len(pages),
        "chunks_crossing_pages": sum(chunk.pdf_page_start != chunk.pdf_page_end for chunk in chunks),
        "chunks_crossing_chapters": sum(len(chunk.chapters) > 1 for chunk in chunks),
        "chunks_ending_naturally": natural_count,
        "natural_ending_rate": round(natural_count / len(chunks), 4),
        "min_compact_char_count": min(counts),
        "max_compact_char_count": max(counts),
        "average_compact_char_count": round(sum(counts) / len(counts), 2),
        "first_chunk_id": chunks[0].chunk_id,
        "last_chunk_id": chunks[-1].chunk_id,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    row["parse_status"] = "structured_chunked"
    row["notes"] = (
        f"章节+段落感知切分完成：target={target_chars}，max={max_chars}，"
        f"overlap={overlap_chars}，共{len(chunks)}个Chunk；待检索评估"
    )
    write_manifest_atomic(manifest_path, fieldnames, manifest_rows)
    return output_path, report_path, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成章节和段落感知的优化Chunk")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_DIR)
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--target-chars", type=int, default=800)
    parser.add_argument("--max-chars", type=int, default=1000)
    parser.add_argument("--overlap-chars", type=int, default=150)
    parser.add_argument("--max-unit-chars", type=int, default=400)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output, report_path, report = structured_chunk_report(
            document_id=args.document_id,
            manifest_path=args.manifest.resolve(),
            parsed_dir=args.parsed_dir.resolve(),
            chunks_dir=args.chunks_dir.resolve(),
            reports_dir=args.reports_dir.resolve(),
            target_chars=args.target_chars,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            max_unit_chars=args.max_unit_chars,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"优化切分失败：{exc}", file=sys.stderr)
        return 1
    print("优化切分成功")
    print(f"Chunk数据：{output}")
    print(f"质量报告：{report_path}")
    print(f"Chunk数量：{report['chunk_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
