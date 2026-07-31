from src.evaluation.evaluate_rag import (
    evaluate_case,
    normalized_numbers,
    summarize,
)
from src.generation.rag import Citation, RagAnswer


def _row() -> dict[str, str]:
    return {
        "question_id": "Q1",
        "question": "研发投入是多少？",
        "question_type": "rd_fact",
        "difficulty": "easy",
        "reference_answer": "研发投入63441379000元占营业收入7.89%",
        "evidence_pages": "39",
    }


def _answer(*, pages: list[int], text: str) -> RagAnswer:
    return RagAnswer(
        question="研发投入是多少？",
        status="answered",
        answer=text,
        citations=[
            Citation(
                citation_id=1,
                chunk_id="chunk-1",
                company="测试公司",
                stock_code="000001",
                report_year=2025,
                chapter="研发",
                pdf_pages=pages,
                source_file="test.pdf",
                source_url="https://example.com",
                quote="研发投入63,441,379,000元，占比7.89%。",
                retrieval_score=0.5,
            )
        ],
        refusal_reason=None,
        retrieval_method="hybrid_rerank",
    )


def test_normalized_numbers_removes_grouping_commas() -> None:
    assert normalized_numbers("63,441,379,000.00元，7.89%") == [
        "63441379000",
        "7.89%",
    ]


def test_answer_proxy_requires_numbers_and_gold_page() -> None:
    valid = evaluate_case(
        _row(),
        _answer(
            pages=[39, 40],
            text="研发投入为63441379000元，占营业收入7.89%。[证据1]",
        ),
        1.2,
    )
    assert valid["reference_number_recall"] == 1.0
    assert valid["citation_page_hit"] is True
    assert valid["answer_accuracy_proxy"] is True

    wrong_page = evaluate_case(
        _row(),
        _answer(
            pages=[10],
            text="研发投入为63441379000元，占营业收入7.89%。[证据1]",
        ),
        1.0,
    )
    assert wrong_page["answer_accuracy_proxy"] is False


def test_summary_reports_failed_question_ids() -> None:
    cases = [
        {
            "question_id": "Q1",
            "status": "answered",
            "error": None,
            "citation_page_hit": True,
            "reference_number_recall": 1.0,
            "answer_accuracy_proxy": True,
            "elapsed_seconds": 1.0,
        },
        {
            "question_id": "Q2",
            "status": "answered",
            "error": None,
            "citation_page_hit": False,
            "reference_number_recall": 0.5,
            "answer_accuracy_proxy": False,
            "elapsed_seconds": 2.0,
        },
    ]
    result = summarize(cases)
    assert result["citation_page_hit_rate"] == 0.5
    assert result["answer_accuracy_proxy"] == 0.5
    assert result["failed_question_ids"] == ["Q2"]
