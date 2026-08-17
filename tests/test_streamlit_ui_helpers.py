import json
from pathlib import Path

from app.ui_helpers import (
    answer_for_display,
    available_documents,
    capability_answer,
    citation_page_label,
    friendly_error,
    guide_intent,
    report_structure,
    result_message,
    structure_answer,
    verified_demo_questions,
)


def test_answer_for_display_hides_inline_citations_only() -> None:
    answer = "货币资金为26,430万元[证据1]。单位为万元【证据 2】。"
    assert answer_for_display(answer) == "货币资金为26,430万元。单位为万元。"


def test_guide_intent_routes_help_and_structure_questions() -> None:
    assert guide_intent("你能回答我什么？") == "capabilities"
    assert guide_intent("梳理一下财报结构") == "structure"
    assert guide_intent("营业收入是多少？") is None


def test_capability_answer_is_document_specific() -> None:
    answer = capability_answer("宁德时代", 2023)
    assert "宁德时代2023年年度报告" in answer
    assert "PDF物理页码" in answer
    assert "投资建议" in answer


def test_report_structure_extracts_unique_top_level_sections(tmp_path: Path) -> None:
    parsed = tmp_path / "pages.jsonl"
    parsed.write_text(
        '\n'.join(
            [
                json.dumps({"pdf_page": 2, "chapter": "第一节 重要提示"}, ensure_ascii=False),
                json.dumps({"pdf_page": 3, "chapter": "第一节 重要提示"}, ensure_ascii=False),
                json.dumps({"pdf_page": 6, "chapter": "第二节 公司简介和主要财务指标"}, ensure_ascii=False),
                json.dumps({"pdf_page": 7, "chapter": "五、主要会计数据和财务指标"}, ensure_ascii=False),
            ]
        ) + '\n',
        encoding="utf-8",
    )

    sections = report_structure(parsed)

    assert sections == [("第一节 重要提示", 2), ("第二节 公司简介和主要财务指标", 6)]
    assert "PDF第2页起" in structure_answer("示例公司", 2025, sections)


def test_report_structure_falls_back_to_unnumbered_toc(tmp_path: Path) -> None:
    parsed = tmp_path / "pages.jsonl"
    parsed.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "pdf_page": 3,
                        "printed_page": 2,
                        "chapter": "unknown",
                        "text": "目录\n公司简介 ........ 3\n业务概览 ........ 18\n财务报告 ........ 80",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {"pdf_page": 4, "printed_page": 3, "chapter": "unknown", "text": "公司简介"},
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert report_structure(parsed) == [
        ("公司简介", 4),
        ("业务概览", 19),
        ("财务报告", 81),
    ]


def test_available_documents_only_exposes_accepted_reports(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "document_id,company_short_name,stock_code,report_year,parse_status,source_url\n"
        "002594_2025,比亚迪,002594,2025,retrieval_quality_accepted,https://example.com/a.pdf\n"
        "300750_2025,宁德时代,300750,2025,pending,\n",
        encoding="utf-8",
    )

    documents = available_documents(manifest)

    assert list(documents) == ["比亚迪"]
    assert list(documents["比亚迪"]) == [2025]
    assert documents["比亚迪"][2025]["stock_code"] == "002594"


def test_citation_page_label_distinguishes_physical_pdf_pages() -> None:
    assert citation_page_label([39]) == "PDF第39页"
    assert citation_page_label([39, 40]) == "PDF第39–40页"
    assert citation_page_label([]) == "PDF页码未知"


def test_result_message_maps_product_states() -> None:
    assert "查看以下原文" in result_message({"status": "evidence_only"})
    assert "投资建议" in result_message(
        {
            "status": "refused",
            "refusal_reason": "investment_advice_out_of_scope",
        }
    )
    assert "足够可靠" in result_message(
        {"status": "refused", "refusal_reason": "low_evidence_relevance"}
    )
    assert result_message({"status": "answered"}) == ""


def test_friendly_error_never_exposes_backend_details() -> None:
    message = friendly_error(RuntimeError("secret API key and stack details"))
    assert message == "暂时无法完成查询，请稍后再试。"
    assert "secret" not in message


def test_verified_demo_questions_only_uses_manually_accepted_answers(
    tmp_path: Path,
) -> None:
    document_id = "000001_2025"
    (tmp_path / f"{document_id}_deepseek_rag_manual_review.json").write_text(
        json.dumps({"fully_correct_question_ids": ["Q1", "Q3"]}),
        encoding="utf-8",
    )
    (tmp_path / f"{document_id}_deepseek_rag_evaluation.json").write_text(
        json.dumps(
            {
                "results": [
                    {"question_id": "Q1", "question": "已验收问题一？", "status": "answered"},
                    {"question_id": "Q2", "question": "未验收问题？", "status": "answered"},
                    {"question_id": "Q3", "question": "被拒答问题？", "status": "refused"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert verified_demo_questions(tmp_path, document_id) == ["已验收问题一？"]


def test_verified_demo_questions_has_no_unverified_fallback(tmp_path: Path) -> None:
    assert verified_demo_questions(tmp_path, "missing") == []


def test_verified_demo_questions_accepts_full_review_summary(tmp_path: Path) -> None:
    document_id = "000001_2024"
    (tmp_path / f"{document_id}_deepseek_rag_manual_review.json").write_text(
        json.dumps(
            {
                "summary": {
                    "reviewed_questions": 2,
                    "fully_correct": 2,
                    "incorrect": 0,
                    "refused": 0,
                    "api_or_pipeline_errors": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / f"{document_id}_deepseek_rag_evaluation.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"question_id": "Q1", "question": "问题一？", "status": "answered"},
                    {"question_id": "Q2", "question": "问题二？", "status": "answered"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert verified_demo_questions(tmp_path, document_id) == ["问题一？", "问题二？"]
