import json
from pathlib import Path

from src.parsing.audit_pages import select_samples


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
        record(4, "1、合并资产负债表\n货币资金 100"),
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
