from pathlib import Path

from src.generation.comparison import (
    ComparisonRequest,
    CrossCompanyComparator,
    _extract_value,
    _report_unit,
    parse_comparison_request,
)


DOCUMENTS = {
    "比亚迪": {2025: {"stock_code": "002594"}},
    "宁德时代": {2025: {"stock_code": "300750"}},
    "贵州茅台": {2025: {"stock_code": "600519"}},
}


def test_parse_explicit_companies_metric_and_year():
    request = parse_comparison_request(
        "比较比亚迪和宁德时代2025年的货币资金", DOCUMENTS, default_year=2024
    )
    assert request == ComparisonRequest(["比亚迪", "宁德时代"], 2025, "货币资金")


def test_parse_all_companies_and_alias():
    request = parse_comparison_request(
        "所有公司总资产哪家最高", DOCUMENTS, default_year=2025
    )
    assert request == ComparisonRequest(list(DOCUMENTS), 2025, "资产总计")


def test_non_comparison_does_not_intercept_single_company_question():
    assert parse_comparison_request("比亚迪货币资金是多少", DOCUMENTS, default_year=2025) is None


def test_extract_value_skips_note_number():
    text = "合并资产负债表\n货币资金 四(1) 171,094 242,275"
    assert str(_extract_value(text, "货币资金")) == "171094"


def test_report_unit_understands_report_wide_declaration(tmp_path: Path):
    (tmp_path / "002594_2025_pages.jsonl").write_text(
        '{"text":"财务附注中报表的单位为：千元\\n合并资产负债表","pdf_page":1}\n',
        encoding="utf-8",
    )
    assert _report_unit("002594", 2025, tmp_path) == "千元"


def test_comparator_retrieves_each_company_independently(tmp_path: Path):
    calls = []

    def retriever(query, **kwargs):
        calls.append((kwargs["stock_code"], kwargs["strategy"]))
        value = "100,000" if kwargs["stock_code"] == "002594" else "200,000"
        return [{
            "chunk_id": f"{kwargs['stock_code']}-1",
            "text": f"合并资产负债表\n单位：千元\n货币资金 四(1) {value} 1",
            "company": "x", "stock_code": kwargs["stock_code"], "report_year": 2025,
            "chapter": "财务报表", "pdf_pages": [10], "source_file": "x.pdf",
            "source_url": "https://example.com", "score": 1, "balance_sheet_row_score": 1,
        }]

    parsed = tmp_path / "parsed"
    parsed.mkdir()
    for code in ("002594", "300750"):
        (parsed / f"{code}_2025_pages.jsonl").write_text(
            '{"text":"合并资产负债表\\n单位：千元","pdf_page":1}\n', encoding="utf-8"
        )
    result = CrossCompanyComparator(retriever=retriever, parsed_dir=parsed).answer(
        "比较", ComparisonRequest(["比亚迪", "宁德时代"], 2025, "货币资金"), DOCUMENTS
    )
    assert result.status == "comparison"
    assert {code for code, _ in calls} == {"002594", "300750"}
    assert len(calls) == 4
    assert result.rows[0].value_yi == "1.00"
    assert result.rows[1].value_yi == "2.00"
