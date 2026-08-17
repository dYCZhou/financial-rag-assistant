"""Controlled cross-company comparison over independently retrieved statements."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from src.indexing.build_index import DEFAULT_DB_DIR
from src.parsing.parse_report import ROOT
from src.retrieval.hybrid import DEFAULT_CONFIG, search_hybrid


METRIC_ALIASES = {
    "货币资金": ("货币资金",),
    "应收账款": ("应收账款",),
    "存货": ("存货",),
    "流动资产合计": ("流动资产合计", "流动资产总额"),
    "资产总计": ("资产总计", "总资产"),
    "负债合计": ("负债合计", "总负债"),
    "固定资产": ("固定资产",),
    "在建工程": ("在建工程",),
    "无形资产": ("无形资产",),
    "商誉": ("商誉",),
}
UNIT_MULTIPLIERS = {
    "元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
    "百万元": Decimal("1000000"),
    "亿元": Decimal("100000000"),
}
COMPARISON_SIGNALS = ("比较", "对比", "哪家", "排名", "最高", "最低", "分别", "各家")


@dataclass(frozen=True)
class ComparisonRequest:
    companies: list[str]
    year: int
    metric: str


@dataclass(frozen=True)
class ComparisonFact:
    company: str
    stock_code: str
    year: int
    metric: str
    raw_value: str
    unit: str
    value_yi: str
    citation: dict[str, object]


@dataclass(frozen=True)
class ComparisonAnswer:
    question: str
    status: str
    answer: str
    rows: list[ComparisonFact]
    citations: list[dict[str, object]]
    missing_companies: list[str]

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["comparison_rows"] = value.pop("rows")
        return value


def parse_comparison_request(
    question: str,
    documents: dict[str, dict[int, dict[str, str]]],
    *,
    default_year: int,
) -> ComparisonRequest | None:
    compact = re.sub(r"\s+", "", question)
    metric = next(
        (canonical for canonical, aliases in METRIC_ALIASES.items() if any(alias in compact for alias in aliases)),
        None,
    )
    explicit = [company for company in documents if company in compact]
    wants_all = any(term in compact for term in ("所有公司", "全部公司", "五家公司", "各家公司"))
    companies = list(documents) if wants_all else explicit
    year_match = re.search(r"(20\d{2})年?", compact)
    year = int(year_match.group(1)) if year_match else default_year
    if not metric or len(companies) < 2 or not any(signal in compact for signal in COMPARISON_SIGNALS):
        return None
    companies = [company for company in companies if year in documents[company]]
    return ComparisonRequest(companies=companies[:5], year=year, metric=metric) if len(companies) >= 2 else None


def _report_unit(stock_code: str, year: int, parsed_dir: Path) -> str | None:
    path = parsed_dir / f"{stock_code}_{year}_pages.jsonl"
    try:
        texts = [str(json.loads(line).get("text", "")) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, json.JSONDecodeError):
        return None
    statement_text = "\n".join(text for text in texts if "合并资产负债表" in text or "合并及公司资产负债表" in text)
    full_text = "\n".join(texts)
    for corpus in (statement_text, full_text):
        matches = re.findall(
            r"(?:金额单位为|单位为[：:]?|单位[：:]?)\s*(?:人民币)?(百万元|千元|万元|元)",
            corpus,
        )
        if matches:
            return matches[0]
    # Some audited statements omit the unit in extracted headers. Require repeated
    # explicit RMB-thousand annotations in the same report before inferring it.
    return "千元" if len(re.findall(r"人民币千元", full_text)) >= 2 else None


def _extract_value(text: str, metric: str) -> Decimal | None:
    aliases = METRIC_ALIASES[metric]
    for line in text.splitlines():
        alias = next((item for item in aliases if item in line), None)
        if not alias:
            continue
        tail = line.split(alias, 1)[1]
        # Notes such as 四(1) precede the actual statement value; a financial value
        # either contains a thousands separator/decimal or has at least four digits.
        matches = re.findall(r"\(?-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)\)?", tail)
        if not matches:
            continue
        try:
            return Decimal(matches[0].replace(",", "").strip("()"))
        except InvalidOperation:
            continue
    return None


class CrossCompanyComparator:
    def __init__(
        self,
        *,
        retriever: Callable[..., list[dict[str, object]]] = search_hybrid,
        db_dir: Path = DEFAULT_DB_DIR,
        chunks_dir: Path = ROOT / "data" / "chunks",
        parsed_dir: Path = ROOT / "data" / "parsed",
        config_path: Path = DEFAULT_CONFIG,
    ):
        self.retriever = retriever
        self.db_dir = db_dir
        self.chunks_dir = chunks_dir
        self.parsed_dir = parsed_dir
        self.config_path = config_path

    def answer(self, question: str, request: ComparisonRequest, documents: dict[str, dict[int, dict[str, str]]]) -> ComparisonAnswer:
        facts: list[ComparisonFact] = []
        missing: list[str] = []
        for company in request.companies:
            document = documents[company][request.year]
            query = f"{company}{request.year}年末合并口径的{request.metric}是多少？"
            hit = self._best_hit(query, document["stock_code"], request.year, request.metric)
            unit = _report_unit(document["stock_code"], request.year, self.parsed_dir)
            value = _extract_value(str(hit.get("text", "")), request.metric) if hit else None
            if not hit or value is None or unit not in UNIT_MULTIPLIERS:
                missing.append(company)
                continue
            citation = {
                "citation_id": len(facts) + 1,
                "company": company,
                "stock_code": document["stock_code"],
                "report_year": request.year,
                "chapter": hit.get("chapter", "unknown"),
                "pdf_pages": hit.get("pdf_pages", []),
                "source_file": hit.get("source_file", ""),
                "source_url": hit.get("source_url", ""),
                "quote": next((line.strip() for line in str(hit["text"]).splitlines() if request.metric in line), str(hit["text"])[:300]),
                "retrieval_score": hit.get("score", 0),
            }
            value_yi = value * UNIT_MULTIPLIERS[unit] / UNIT_MULTIPLIERS["亿元"]
            facts.append(ComparisonFact(company, document["stock_code"], request.year, request.metric, f"{value:,}", unit, f"{value_yi:,.2f}", citation))
        citations = [dict(fact.citation) for fact in facts]
        if missing:
            answer = f"已找到{len(facts)}家公司可核验数据；{ '、'.join(missing) }证据不足，因此不生成完整排名。"
            status = "comparison_partial"
        else:
            ordered = sorted(facts, key=lambda fact: Decimal(fact.value_yi.replace(",", "")), reverse=True)
            answer = f"{request.year}年末合并口径的{request.metric}已统一折算为亿元。由高到低为：" + "、".join(f"{fact.company}{fact.value_yi}亿元" for fact in ordered) + "。"
            status = "comparison"
        return ComparisonAnswer(question, status, answer, facts, citations, missing)

    def _best_hit(self, query: str, stock_code: str, year: int, metric: str) -> dict[str, object] | None:
        candidates: list[dict[str, object]] = []
        for strategy in ("structured", "baseline"):
            hits = self.retriever(query, strategy=strategy, db_dir=self.db_dir, chunks_dir=self.chunks_dir, top_k=8, stock_code=stock_code, report_year=year, rerank=True, config_path=self.config_path)
            candidates.extend(hits)
        valid = [hit for hit in candidates if metric in str(hit.get("text", "")) and ("合并资产负债表" in str(hit.get("text", "")) or "合并及公司资产负债表" in str(hit.get("text", ""))) and _extract_value(str(hit.get("text", "")), metric) is not None]
        return max(valid, key=lambda hit: (float(hit.get("balance_sheet_row_score", 0)), float(hit.get("score", 0))), default=None)
