"""Evidence-first RAG orchestration with citations and explicit abstention."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

import yaml

from src.indexing.build_index import DEFAULT_DB_DIR
from src.parsing.parse_report import ROOT
from src.retrieval.bm25 import tokenize
from src.retrieval.hybrid import DEFAULT_CONFIG, search_hybrid


AnswerStatus = Literal["answered", "evidence_only", "refused"]
Retriever = Callable[..., list[dict[str, object]]]

INVESTMENT_ADVICE_PATTERNS = (
    r"应该.*买",
    r"应该.*卖",
    r"是否值得投资",
    r"投资建议",
    r"目标价",
    r"股价.*(?:涨|跌)",
    r"预测.*股价",
    r"推荐.*股票",
)


@dataclass(frozen=True)
class Citation:
    citation_id: int
    chunk_id: str
    company: str
    stock_code: str
    report_year: int
    chapter: str
    pdf_pages: list[int]
    source_file: str
    source_url: str
    quote: str
    retrieval_score: float


@dataclass(frozen=True)
class RagAnswer:
    question: str
    status: AnswerStatus
    answer: str
    citations: list[Citation]
    refusal_reason: str | None
    retrieval_method: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AnswerGenerator(Protocol):
    name: str

    def generate(
        self,
        *,
        question: str,
        prompt: str,
        citations: list[Citation],
    ) -> str:
        """Generate an answer from the supplied evidence only."""


def load_generation_config(path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    generation = raw.get("generation", {})
    config: dict[str, object] = {
        "provider": str(generation.get("provider", "evidence_only")),
        "model": str(generation.get("model", "deepseek-v4-flash")),
        "base_url": str(
            generation.get("base_url", "https://api.deepseek.com")
        ),
        "refuse_without_evidence": bool(
            generation.get("refuse_without_evidence", True)
        ),
        "provide_investment_advice": bool(
            generation.get("provide_investment_advice", False)
        ),
        "strategy": str(generation.get("strategy", "baseline")),
        "top_k": int(generation.get("top_k", 5)),
        "max_citations": int(generation.get("max_citations", 3)),
        "max_quote_chars": int(generation.get("max_quote_chars", 500)),
        "min_term_coverage": float(generation.get("min_term_coverage", 0.08)),
    }
    if config["strategy"] not in {"baseline", "structured"}:
        raise ValueError("generation.strategy必须是baseline或structured")
    if config["top_k"] <= 0 or config["max_citations"] <= 0:
        raise ValueError("generation的top_k和max_citations必须大于0")
    if config["max_quote_chars"] < 100:
        raise ValueError("max_quote_chars不得小于100")
    if not 0 <= config["min_term_coverage"] <= 1:
        raise ValueError("min_term_coverage必须位于0和1之间")
    return config


def is_investment_advice(question: str) -> bool:
    return any(re.search(pattern, question) for pattern in INVESTMENT_ADVICE_PATTERNS)


def _salient_terms(question: str) -> list[str]:
    ignored = {"公司", "比亚迪", "2025", "多少", "如何", "什么", "的是", "是否"}
    terms = {
        token
        for token in tokenize(question)
        if 2 <= len(token) <= 4 and token not in ignored and not token.isdigit()
    }
    return sorted(terms, key=lambda term: (-len(term), term))


def quote_around_query(text: str, question: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    positions = [
        compact.find(term)
        for term in _salient_terms(question)
        if compact.find(term) >= 0
    ]
    center = min(positions) if positions else 0
    start = max(0, center - max_chars // 4)
    end = min(len(compact), start + max_chars)
    start = max(0, end - max_chars)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


def citations_from_hits(
    hits: list[dict[str, object]],
    *,
    question: str,
    max_citations: int,
    max_quote_chars: int,
) -> list[Citation]:
    citations: list[Citation] = []
    seen_chunks: set[str] = set()
    for hit in hits:
        chunk_id = str(hit["chunk_id"])
        if chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk_id)
        citations.append(
            Citation(
                citation_id=len(citations) + 1,
                chunk_id=chunk_id,
                company=str(hit["company"]),
                stock_code=str(hit["stock_code"]),
                report_year=int(hit["report_year"]),
                chapter=str(hit.get("chapter", "unknown")),
                pdf_pages=[int(page) for page in hit["pdf_pages"]],
                source_file=str(hit["source_file"]),
                source_url=str(hit["source_url"]),
                quote=quote_around_query(
                    str(hit["text"]), question, max_chars=max_quote_chars
                ),
                retrieval_score=float(hit["score"]),
            )
        )
        if len(citations) >= max_citations:
            break
    return citations


def build_grounded_prompt(question: str, citations: list[Citation]) -> str:
    evidence = "\n\n".join(
        (
            f"[证据{citation.citation_id}] 公司：{citation.company}；"
            f"年度：{citation.report_year}；PDF页码：{citation.pdf_pages}\n"
            f"{citation.quote}"
        )
        for citation in citations
    )
    return f"""你是上市公司年报信息整理助手。必须遵守：
1. 只能使用下方证据，不得使用外部知识或猜测。
2. 每个事实结论后标注对应证据编号，如[证据1]。
3. 数值必须同时说明公司、年度和单位；证据未给出单位时不得自行补充。
4. 多条证据冲突时明确说明冲突，不得自行选择。
5. 证据不足以回答时只回答“现有证据不足，无法回答该问题”。
6. 不提供投资建议、估值、股价预测或买卖建议。

问题：{question}

{evidence}
"""


class EvidenceOnlyGenerator:
    """Safe local fallback: return evidence excerpts without synthesizing facts."""

    name = "evidence_only"

    def generate(
        self,
        *,
        question: str,
        prompt: str,
        citations: list[Citation],
    ) -> str:
        del question, prompt
        lines = ["当前未配置LLM，以下是与问题最相关的年报原文证据："]
        lines.extend(
            f"[证据{item.citation_id}] {item.quote}" for item in citations
        )
        return "\n\n".join(lines)


class RagPipeline:
    def __init__(
        self,
        *,
        retriever: Retriever = search_hybrid,
        generator: AnswerGenerator | None = None,
        config_path: Path = DEFAULT_CONFIG,
        db_dir: Path = DEFAULT_DB_DIR,
        chunks_dir: Path = ROOT / "data" / "chunks",
    ):
        self.retriever = retriever
        self.config = load_generation_config(config_path)
        self.generator = generator or self._default_generator()
        self.config_path = config_path
        self.db_dir = db_dir
        self.chunks_dir = chunks_dir

    def _default_generator(self) -> AnswerGenerator:
        if str(self.config.get("provider", "evidence_only")) != "deepseek":
            return EvidenceOnlyGenerator()
        try:
            from src.generation.deepseek import DeepSeekGenerator, DeepSeekSettings

            return DeepSeekGenerator(
                DeepSeekSettings.from_environment(
                    default_base_url=str(self.config["base_url"]),
                    default_model=str(self.config["model"]),
                )
            )
        except ValueError:
            return EvidenceOnlyGenerator()

    def answer(
        self,
        question: str,
        *,
        stock_code: str,
        report_year: int,
    ) -> RagAnswer:
        if not question.strip():
            raise ValueError("问题不能为空")
        if (
            not bool(self.config["provide_investment_advice"])
            and is_investment_advice(question)
        ):
            return RagAnswer(
                question=question,
                status="refused",
                answer="本系统只用于财报信息检索，不提供投资建议、估值或股价预测。",
                citations=[],
                refusal_reason="investment_advice_out_of_scope",
                retrieval_method="hybrid_rerank",
            )

        hits = self.retriever(
            question,
            strategy=str(self.config["strategy"]),
            db_dir=self.db_dir,
            chunks_dir=self.chunks_dir,
            top_k=int(self.config["top_k"]),
            stock_code=stock_code,
            report_year=report_year,
            rerank=True,
            config_path=self.config_path,
        )
        max_coverage = max(
            (float(hit.get("term_coverage", 0.0)) for hit in hits),
            default=0.0,
        )
        if (
            bool(self.config["refuse_without_evidence"])
            and (
                not hits
                or max_coverage < float(self.config["min_term_coverage"])
            )
        ):
            return RagAnswer(
                question=question,
                status="refused",
                answer="现有证据不足，无法回答该问题。",
                citations=[],
                refusal_reason=(
                    "no_retrieval_results" if not hits else "low_evidence_relevance"
                ),
                retrieval_method="hybrid_rerank",
            )

        citations = citations_from_hits(
            hits,
            question=question,
            max_citations=int(self.config["max_citations"]),
            max_quote_chars=int(self.config["max_quote_chars"]),
        )
        prompt = build_grounded_prompt(question, citations)
        answer = self.generator.generate(
            question=question,
            prompt=prompt,
            citations=citations,
        )
        valid_ids = {citation.citation_id for citation in citations}
        cited_ids = {
            int(value) for value in re.findall(r"\[证据(\d+)\]", answer)
        }
        if not isinstance(self.generator, EvidenceOnlyGenerator):
            if not cited_ids:
                if re.search(r"证据不足|无法回答|不能回答", answer):
                    return RagAnswer(
                        question=question,
                        status="refused",
                        answer=answer,
                        citations=[],
                        refusal_reason="generator_evidence_insufficient",
                        retrieval_method="hybrid_rerank",
                    )
                raise RuntimeError("生成答案缺少证据编号，已拒绝返回")
            if not cited_ids <= valid_ids:
                raise RuntimeError("生成答案引用了不存在的证据编号，已拒绝返回")
        status: AnswerStatus = (
            "evidence_only"
            if isinstance(self.generator, EvidenceOnlyGenerator)
            else "answered"
        )
        return RagAnswer(
            question=question,
            status=status,
            answer=answer,
            citations=citations,
            refusal_reason=None,
            retrieval_method="hybrid_rerank",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="运行受证据约束的单文档RAG链")
    parser.add_argument("question")
    parser.add_argument("--stock-code", required=True)
    parser.add_argument("--report-year", type=int, required=True)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--chunks-dir", type=Path, default=ROOT / "data" / "chunks")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    try:
        result = RagPipeline(
            config_path=args.config.resolve(),
            db_dir=args.db_dir.resolve(),
            chunks_dir=args.chunks_dir.resolve(),
        ).answer(
            args.question,
            stock_code=args.stock_code,
            report_year=args.report_year,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"RAG执行失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
