import json

import pytest

from src.generation.deepseek import DeepSeekGenerator, DeepSeekSettings
from src.generation.rag import Citation, RagPipeline


def _citation() -> Citation:
    return Citation(
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


def test_deepseek_generator_uses_current_endpoint_and_non_thinking_mode() -> None:
    captured: dict[str, object] = {}

    def transport(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return json.dumps(
            {
                "choices": [
                    {"message": {"content": "营业收入为100元。[证据1]"}}
                ]
            }
        ).encode("utf-8")

    generator = DeepSeekGenerator(
        DeepSeekSettings(api_key="test-key"),
        transport=transport,
    )
    answer = generator.generate(
        question="营业收入是多少？",
        prompt="测试Prompt",
        citations=[_citation()],
    )
    assert answer == "营业收入为100元。[证据1]"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    payload = captured["payload"]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["temperature"] == 0


def test_deepseek_generator_rejects_invalid_response() -> None:
    generator = DeepSeekGenerator(
        DeepSeekSettings(api_key="test-key"),
        transport=lambda request, timeout: b'{"choices":[]}',
    )
    with pytest.raises(RuntimeError, match="返回格式无效"):
        generator.generate(
            question="问题",
            prompt="Prompt",
            citations=[_citation()],
        )


class _Generator:
    name = "fake"

    def __init__(self, answer: str):
        self.answer = answer

    def generate(self, *, question, prompt, citations):
        del question, prompt, citations
        return self.answer


def _hit() -> dict[str, object]:
    return {
        "rank": 1,
        "chunk_id": "chunk-1",
        "score": 0.5,
        "company": "测试公司",
        "stock_code": "000001",
        "report_year": 2025,
        "chapter": "财务指标",
        "pdf_page_start": 10,
        "pdf_page_end": 10,
        "pdf_pages": [10],
        "source_file": "test.pdf",
        "source_url": "https://example.com",
        "text": "营业收入100元。",
        "term_coverage": 0.8,
    }


def _retriever(*args, **kwargs):
    del args, kwargs
    return [_hit()]


def test_pipeline_accepts_only_existing_citation_ids() -> None:
    valid = RagPipeline(
        retriever=_retriever,
        generator=_Generator("营业收入为100元。[证据1]"),
    ).answer("营业收入是多少？", stock_code="000001", report_year=2025)
    assert valid.status == "answered"

    with pytest.raises(RuntimeError, match="不存在的证据编号"):
        RagPipeline(
            retriever=_retriever,
            generator=_Generator("营业收入为100元。[证据9]"),
        ).answer("营业收入是多少？", stock_code="000001", report_year=2025)

    with pytest.raises(RuntimeError, match="缺少证据编号"):
        RagPipeline(
            retriever=_retriever,
            generator=_Generator("营业收入为100元。"),
        ).answer("营业收入是多少？", stock_code="000001", report_year=2025)

    refused = RagPipeline(
        retriever=_retriever,
        generator=_Generator("现有证据不足，无法回答该问题。"),
    ).answer("营业收入是多少？", stock_code="000001", report_year=2025)
    assert refused.status == "refused"
    assert refused.refusal_reason == "generator_evidence_insufficient"
    assert refused.citations == []
