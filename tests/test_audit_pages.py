import json
from pathlib import Path

import fitz

from src.parsing.audit_pages import render_page, select_samples


def record(
    page: int,
    text: str,
    *,
    chars: int = 900,
    flags=None,
    chapter: str = "第三节 管理层讨论与分析",
) -> dict:
    return {
        "pdf_page": page,
        "text": text,
        "char_count": chars,
        "quality_flags": [] if flags is None else flags,
        "chapter": chapter,
    }


def test_select_samples_covers_required_categories_and_flagged_pages() -> None:
    records = [
        record(1, "公司 2025 年年度报告", chars=20, flags=["short_page"]),
        record(2, "目录\n第一节\n第二节\n第三节\n第四节"),
        record(3, "管理层讨论与分析。" * 100),
        record(4, "1、合并资产负债表\n货币资金 " + " 100" * 12),
        record(5, "董事长签字", chars=10, flags=["short_page"]),
    ]
    quality = {
        "flagged_pages": [
            {"pdf_page": 1, "flags": ["short_page"]},
            {"pdf_page": 5, "flags": ["short_page"]},
        ]
    }

    selected = select_samples(records, quality)
    categories = {item.category for item in selected}
    pages = [item.pdf_page for item in selected]
    assert {"cover", "table_of_contents", "body_text", "financial_table"} <= categories
    assert 5 in pages
    assert len(pages) == len(set(pages))


def test_select_samples_accepts_sse_style_body_chapter() -> None:
    records = [
        record(1, "公司 2024 年年度报告", chars=20, flags=["short_page"]),
        record(2, "目录\n第一节\n第二节\n第三节\n第四节"),
        record(
            3,
            "公司持续推进市场建设和产品创新。" * 80,
            chapter="五、报告期内主要经营情况",
        ),
        record(4, "合并利润表\n营业收入 " + " 100" * 12, chapter="第十节 财务报告"),
    ]
    quality = {"flagged_pages": [{"pdf_page": 1, "flags": ["short_page"]}]}

    categories = {item.category for item in select_samples(records, quality)}
    assert {"cover", "table_of_contents", "body_text", "financial_table"} <= categories


def test_select_samples_accepts_spaced_toc_without_numbered_sections() -> None:
    records = [
        record(1, "公司 2025 年年度报告", chars=20, flags=["short_page"]),
        record(2, "目 录\n公司简介 .... 3\n董事长报告 .... 8\n业务概览 .... 12\n财务报告 .... 80"),
        record(3, "公司持续推进市场建设和产品创新。" * 80),
        record(4, "合并资产负债表\n货币资金 " + " 100" * 12),
    ]
    quality = {"flagged_pages": [{"pdf_page": 1, "flags": ["short_page"]}]}

    categories = {item.category for item in select_samples(records, quality)}
    assert "table_of_contents" in categories


def test_render_page_falls_back_to_pymupdf(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "annual report")
        document.save(pdf_path)

    monkeypatch.setattr("src.parsing.audit_pages.shutil.which", lambda _: None)
    output_dir = tmp_path / "images"
    output_dir.mkdir()
    output = render_page(pdf_path, 1, output_dir)

    assert output.name == "page_0001.png"
    assert output.stat().st_size > 0
