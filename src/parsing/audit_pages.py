"""Build a human-review pack for parsed annual-report pages."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.parsing.parse_report import DEFAULT_MANIFEST, ROOT, load_manifest_row


DEFAULT_PARSED_DIR = ROOT / "data/parsed"
DEFAULT_REPORTS_DIR = ROOT / "reports"


@dataclass(frozen=True)
class AuditSample:
    category: str
    pdf_page: int
    reason: str


def load_jsonl(path: Path) -> list[dict[str, object]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"页面数据为空：{path}")
    expected = list(range(1, len(records) + 1))
    actual = [record.get("pdf_page") for record in records]
    if actual != expected:
        raise ValueError("JSONL 中的 PDF 物理页码不连续")
    return records


def first_matching_page(
    records: list[dict[str, object]], predicate
) -> dict[str, object] | None:
    return next((record for record in records if predicate(record)), None)


def select_samples(
    records: list[dict[str, object]], quality_report: dict[str, object]
) -> list[AuditSample]:
    """Select representative pages without relying on report-specific page numbers."""
    selections: list[AuditSample] = [
        AuditSample("cover", 1, "PDF封面与报告身份核验")
    ]

    toc = first_matching_page(
        records,
        lambda item: (
            str(item.get("text", "")).lstrip().startswith("目录")
            and str(item.get("text", "")).count("第") >= 4
        ),
    )
    if toc:
        selections.append(
            AuditSample("table_of_contents", int(toc["pdf_page"]), "目录与章节页码核验")
        )

    financial = first_matching_page(
        records,
        lambda item: any(
            keyword in str(item.get("text", ""))
            for keyword in ("合并资产负债表", "合并利润表", "合并现金流量表")
        ),
    )
    if financial:
        selections.append(
            AuditSample(
                "financial_table",
                int(financial["pdf_page"]),
                "财务表格行列、数字和单位核验",
            )
        )

    excluded = {sample.pdf_page for sample in selections}
    body_candidates = [
        item
        for item in records
        if item.get("quality_flags") == []
        and int(item.get("pdf_page", 0)) not in excluded
        and 700 <= int(item.get("char_count", 0)) <= 2000
        and "管理层讨论与分析" in str(item.get("chapter", ""))
        and not any(
            keyword in str(item.get("text", ""))
            for keyword in ("资产负债表", "利润表", "现金流量表", "目录")
        )
    ]
    if body_candidates:
        # Narrative pages tend to have longer lines than dense tables or item lists.
        midpoint = max(
            body_candidates,
            key=lambda item: (
                sum(map(len, str(item.get("text", "")).splitlines()))
                / max(1, len(str(item.get("text", "")).splitlines()))
            ),
        )
        selections.append(
            AuditSample("body_text", int(midpoint["pdf_page"]), "普通正文顺序与可读性核验")
        )

    for flagged in quality_report.get("flagged_pages", []):
        page = int(flagged["pdf_page"])
        selections.append(
            AuditSample(
                "flagged_page",
                page,
                "异常页复核：" + ",".join(flagged.get("flags", [])),
            )
        )

    unique: list[AuditSample] = []
    seen: set[int] = set()
    for sample in selections:
        if sample.pdf_page not in seen:
            seen.add(sample.pdf_page)
            unique.append(sample)
    return unique


def render_page(pdf_path: Path, pdf_page: int, output_dir: Path) -> Path:
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("缺少 pdftoppm，无法生成页面视觉抽查图")
    prefix = output_dir / f"page_{pdf_page:04d}"
    command = [
        executable,
        "-f", str(pdf_page),
        "-l", str(pdf_page),
        "-r", "110",
        "-png",
        "-singlefile",
        str(pdf_path),
        str(prefix),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"第{pdf_page}页渲染失败：{completed.stderr.strip()}")
    output = prefix.with_suffix(".png")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(f"第{pdf_page}页未生成有效PNG")
    return output


def build_audit_pack(
    *,
    document_id: str,
    manifest_path: Path = DEFAULT_MANIFEST,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
) -> tuple[Path, Path, dict[str, object]]:
    _, _, row = load_manifest_row(manifest_path, document_id)
    if row.get("parse_status") not in {"parsed", "audited", "baseline_chunked"}:
        raise ValueError("报告尚未完成页面解析，不能执行人工抽查")

    parsed_path = parsed_dir / f"{document_id}_pages.jsonl"
    quality_path = reports_dir / f"{document_id}_parse_quality.json"
    if not parsed_path.exists() or not quality_path.exists():
        raise FileNotFoundError("缺少页面JSONL或解析质量报告")

    records = load_jsonl(parsed_path)
    quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
    samples = select_samples(records, quality_report)
    if not {"cover", "table_of_contents", "body_text", "financial_table"}.issubset(
        {sample.category for sample in samples}
    ):
        raise ValueError("无法自动选齐封面、目录、正文和财务表格四类基础样本")

    pdf_path = Path(row["local_path"])
    if not pdf_path.is_absolute():
        pdf_path = ROOT / pdf_path
    asset_dir = reports_dir / f"{document_id}_audit_assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for stale_image in asset_dir.glob("page_*.png"):
        stale_image.unlink()

    by_page = {int(item["pdf_page"]): item for item in records}
    result_samples: list[dict[str, object]] = []
    for sample in samples:
        image_path = render_page(pdf_path, sample.pdf_page, asset_dir)
        record = by_page[sample.pdf_page]
        result_samples.append(
            {
                "category": sample.category,
                "pdf_page": sample.pdf_page,
                "printed_page": record.get("printed_page"),
                "chapter": record.get("chapter"),
                "reason": sample.reason,
                "quality_flags": record.get("quality_flags", []),
                "char_count": record.get("char_count"),
                "image": image_path.relative_to(reports_dir).as_posix(),
                "text": record.get("text", ""),
            }
        )

    result: dict[str, object] = {
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending_human_review",
        "sample_count": len(result_samples),
        "samples": result_samples,
        "review_checklist": [
            "页面图像与提取文本属于同一PDF物理页",
            "公司、报告年度和报告类型正确",
            "目录章节与页码关系未明显错乱",
            "正文阅读顺序基本正确且无大面积乱码",
            "财务表格的项目、单位和关键数字可对应",
            "异常页属于合理短页/封面/签署页，而非正文漏提取",
        ],
    }

    json_path = reports_dir / f"{document_id}_page_audit.json"
    markdown_path = reports_dir / f"{document_id}_page_audit.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {document_id} 页面解析人工抽查",
        "",
        f"- 样本数：{len(result_samples)}",
        "- 当前状态：待人工确认",
        "",
        "## 验收清单",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in result["review_checklist"])
    for item in result_samples:
        lines.extend(
            [
                "",
                f"## {item['category']} - PDF第{item['pdf_page']}页",
                "",
                f"- 抽查原因：{item['reason']}",
                f"- 印刷页码：{item['printed_page']}",
                f"- 章节：{item['chapter']}",
                f"- 字符数：{item['char_count']}",
                f"- 质量标记：{item['quality_flags']}",
                "",
                f"![PDF第{item['pdf_page']}页]({item['image']})",
                "",
                "### 提取文本",
                "",
                "```text",
                str(item["text"]),
                "```",
            ]
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return markdown_path, json_path, result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成页面解析人工抽查包")
    parser.add_argument("--document-id", required=True, help="例如 002594_2025")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    markdown, data, result = build_audit_pack(
        document_id=args.document_id,
        manifest_path=args.manifest.resolve(),
        parsed_dir=args.parsed_dir.resolve(),
        reports_dir=args.reports_dir.resolve(),
    )
    print(f"抽查包已生成：{markdown}")
    print(f"机器可读结果：{data}")
    print(f"样本数：{result['sample_count']}，状态：{result['review_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
