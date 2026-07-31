"""Compare fixed-length and structured chunk quality with the same source report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.parsing.parse_report import ROOT

DEFAULT_REPORTS_DIR = ROOT / "reports"


def percent_change(before: int, after: int) -> float:
    return round((after - before) / before, 4) if before else 0.0


def compare_reports(
    baseline: dict[str, object], structured: dict[str, object]
) -> dict[str, object]:
    if baseline["document_id"] != structured["document_id"]:
        raise ValueError("两份质量报告不属于同一文档")
    if baseline["source_page_count"] != structured["source_page_count"]:
        raise ValueError("两种策略的源页面数量不一致，不能直接比较")
    baseline_count = int(baseline["chunk_count"])
    structured_count = int(structured["chunk_count"])
    baseline_cross_pages = int(baseline["chunks_crossing_pages"])
    structured_cross_pages = int(structured["chunks_crossing_pages"])
    baseline_cross_chapters = int(baseline["chunks_crossing_chapters"])
    structured_cross_chapters = int(structured["chunks_crossing_chapters"])
    return {
        "document_id": baseline["document_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_page_count": baseline["source_page_count"],
        "baseline": {
            "strategy": baseline["strategy"],
            "chunk_count": baseline_count,
            "chunks_crossing_pages": baseline_cross_pages,
            "chunks_crossing_chapters": baseline_cross_chapters,
            "average_compact_char_count": baseline["average_compact_char_count"],
        },
        "structured": {
            "strategy": structured["strategy"],
            "chunk_count": structured_count,
            "chunks_crossing_pages": structured_cross_pages,
            "chunks_crossing_chapters": structured_cross_chapters,
            "average_compact_char_count": structured["average_compact_char_count"],
            "natural_ending_rate": structured["natural_ending_rate"],
        },
        "differences": {
            "chunk_count_change": structured_count - baseline_count,
            "chunk_count_change_rate": percent_change(baseline_count, structured_count),
            "cross_page_chunk_change": structured_cross_pages - baseline_cross_pages,
            "cross_page_chunk_change_rate": percent_change(
                baseline_cross_pages, structured_cross_pages
            ),
            "cross_chapter_chunk_change": (
                structured_cross_chapters - baseline_cross_chapters
            ),
            "cross_chapter_chunk_change_rate": percent_change(
                baseline_cross_chapters, structured_cross_chapters
            ),
        },
        "conclusion_boundary": (
            "结构指标只能说明Chunk边界更规整；是否提升语义检索命中率，"
            "必须在同一人工标注问题集上完成Top-K检索评估后判断。"
        ),
    }


def compare_document(
    document_id: str, reports_dir: Path = DEFAULT_REPORTS_DIR
) -> tuple[Path, dict[str, object]]:
    baseline_path = reports_dir / f"{document_id}_baseline_chunk_quality.json"
    structured_path = reports_dir / f"{document_id}_structured_chunk_quality.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    structured = json.loads(structured_path.read_text(encoding="utf-8"))
    comparison = compare_reports(baseline, structured)
    output_path = reports_dir / f"{document_id}_chunk_strategy_comparison.json"
    output_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path, comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="比较基线与优化切分的结构质量")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    args = parser.parse_args()
    output, comparison = compare_document(
        args.document_id, args.reports_dir.resolve()
    )
    print(f"对比报告：{output}")
    print(json.dumps(comparison["differences"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
