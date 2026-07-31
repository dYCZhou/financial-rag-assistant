from pathlib import Path

from src.generation.rag import (
    Citation,
    EvidenceOnlyGenerator,
    RagPipeline,
    build_grounded_prompt,
    citations_from_hits,
    quote_around_query,
)


def _hit(*, coverage: float = 0.5) -> dict[str, object]:
    return {
        "rank": 1,
        "chunk_id": "002594_2025_baseline_00069",
        "score": 0.18,
        "company": "比亚迪股份有限公司",
        "stock_code": "002594",
        "report_year": 2025,
        "chapter": "主营业务分析",
        "pdf_page_start": 39,
        "pdf_page_end": 40,
        "pdf_pages": [39, 40],
        "source_file": "002594_比亚迪_2025_annual_report.pdf",
        "source_url": "https://example.com/report.pdf",
        "text": "研发投入金额（元）63,441,379,000.00，占营业收入比例7.89%。",
        "term_coverage": coverage,
    }


def _retriever_with(hits: list[dict[str, object]]):
    def retrieve(*args, **kwargs):
        del args, kwargs
        return hits

    return retrieve


def test_pipeline_refuses_investment_advice_before_retrieval() -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("越界问题不应触发检索")

    answer = RagPipeline(retriever=should_not_run).answer(
        "现在是否值得投资比亚迪？",
        stock_code="002594",
        report_year=2025,
    )
    assert answer.status == "refused"
    assert answer.refusal_reason == "investment_advice_out_of_scope"
    assert answer.citations == []


def test_pipeline_refuses_empty_or_low_relevance_evidence() -> None:
    empty = RagPipeline(retriever=_retriever_with([])).answer(
        "今天天气如何？",
        stock_code="002594",
        report_year=2025,
    )
    assert empty.status == "refused"
    assert empty.refusal_reason == "no_retrieval_results"

    low = RagPipeline(retriever=_retriever_with([_hit(coverage=0.01)])).answer(
        "今天天气如何？",
        stock_code="002594",
        report_year=2025,
    )
    assert low.status == "refused"
    assert low.refusal_reason == "low_evidence_relevance"


def test_evidence_only_answer_preserves_traceable_citation() -> None:
    answer = RagPipeline(
        retriever=_retriever_with([_hit()]),
        generator=EvidenceOnlyGenerator(),
    ).answer(
        "研发投入是多少？",
        stock_code="002594",
        report_year=2025,
    )
    assert answer.status == "evidence_only"
    assert "[证据1]" in answer.answer
    assert len(answer.citations) == 1
    citation = answer.citations[0]
    assert citation.pdf_pages == [39, 40]
    assert citation.source_url == "https://example.com/report.pdf"
    assert "63,441,379,000.00" in citation.quote


def test_grounded_prompt_contains_constraints_and_evidence() -> None:
    citation = Citation(
        citation_id=1,
        chunk_id="chunk-1",
        company="测试公司",
        stock_code="000001",
        report_year=2025,
        chapter="财务指标",
        pdf_pages=[10],
        source_file="test.pdf",
        source_url="https://example.com",
        quote="营业收入100元。",
        retrieval_score=0.5,
    )
    prompt = build_grounded_prompt("营业收入是多少？", [citation])
    assert "只能使用下方证据" in prompt
    assert "证据不足" in prompt
    assert "不提供投资建议" in prompt
    assert "[证据1]" in prompt
    assert "营业收入100元" in prompt


def test_prompt_carries_inherited_financial_statement_unit() -> None:
    hit = _hit()
    citation = citations_from_hits(
        [hit],
        question="研发投入是多少？",
        max_citations=1,
        max_quote_chars=500,
        unit_context_by_page={39: "财务附注报表单位为千元"},
    )[0]
    prompt = build_grounded_prompt("研发投入是多少？", [citation])
    assert citation.unit_context == "财务附注报表单位为千元"
    assert "单位上下文：财务附注报表单位为千元" in prompt


def test_citation_selection_drops_large_relevance_gap() -> None:
    strong = _hit()
    weak = dict(_hit(), chunk_id="weak", score=0.05)
    citations = citations_from_hits(
        [strong, weak],
        question="研发投入是多少？",
        max_citations=3,
        max_quote_chars=500,
        relative_score_threshold=0.7,
    )
    assert [item.chunk_id for item in citations] == [strong["chunk_id"]]


def test_quote_window_keeps_query_neighbourhood() -> None:
    text = "开头" * 200 + "研发投入金额为100元" + "结尾" * 200
    quote = quote_around_query(text, "研发投入是多少？", max_chars=120)
    assert len(quote) <= 122
    assert "研发投入" in quote


def test_quote_window_prefers_specific_metric_over_earlier_period_word() -> None:
    text = "2025年末" + "无关内容" * 150 + "存货余额为138元" + "结尾" * 150
    quote = quote_around_query(text, "2025年末存货余额是多少？", max_chars=120)
    assert "存货余额为138元" in quote


def test_prompt_explains_default_meaning_of_year_over_year_change() -> None:
    citation = citations_from_hits(
        [_hit()],
        question="经营现金流同比下降多少？",
        max_citations=1,
        max_quote_chars=500,
    )[0]
    prompt = build_grounded_prompt("经营现金流同比下降多少？", [citation])

    assert "默认询问同比变动比例" in prompt
