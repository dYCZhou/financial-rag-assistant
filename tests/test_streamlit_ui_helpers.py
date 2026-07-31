from pathlib import Path

from app.ui_helpers import (
    available_documents,
    citation_page_label,
    friendly_error,
    result_message,
)


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
