"""Build an apply_patch payload for independent, pre-retrieval annual-report question sets.

The generator only reads the manifest, parsed page JSONL and page-audit selection. It
prints a patch rather than writing artifacts so repository changes still go through
the normal patch review path.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    "300750_2023", "300750_2025",
    "600519_2023", "600519_2024", "600519_2025",
    "000333_2023", "000333_2024", "000333_2025",
    "600941_2023", "600941_2024", "600941_2025",
]
LABELS = [
    "货币资金", "应收票据", "应收账款", "预付款项", "其他应收款", "存货",
    "合同资产", "其他流动资产", "流动资产合计", "长期股权投资", "固定资产",
    "在建工程", "使用权资产", "无形资产", "开发支出", "商誉",
    "递延所得税资产", "其他非流动资产", "非流动资产合计", "资产总计",
    "短期借款", "应付票据", "应付账款", "合同负债", "流动负债合计",
    "长期借款", "应付债券", "递延收益", "非流动负债合计", "负债合计",
    "股本", "资本公积", "未分配利润", "归属于母公司所有者权益合计", "所有者权益合计",
]
UNITS = {
    "300750_2023": "人民币万元",
    "300750_2025": "人民币千元",
    "600519_2023": "人民币元",
    "600519_2024": "人民币元",
    "600519_2025": "人民币元",
    "000333_2023": "人民币千元",
    "000333_2024": "人民币千元",
    "000333_2025": "人民币千元",
    "600941_2023": "人民币百万元",
    "600941_2024": "人民币百万元",
    "600941_2025": "人民币百万元",
}


def add_file(path: str, content: str) -> str:
    target = ROOT / path
    if target.exists():
        old = target.read_text(encoding="utf-8")
        if old == content:
            return ""
        lines = [f"*** Update File: {path}", "@@"]
        lines.extend("-" + line for line in old.splitlines())
        lines.extend("+" + line for line in content.splitlines())
    else:
        lines = [f"*** Add File: {path}"]
        lines.extend("+" + line for line in content.splitlines())
        if content.endswith("\n"):
            lines.append("+")
    return "\n".join(lines)


def main() -> None:
    with (ROOT / "data/manifests/annual_reports_manifest.csv").open(encoding="utf-8") as fh:
        manifest = {row["document_id"]: row for row in csv.DictReader(fh)}

    additions: list[str] = []
    for document_id in DOCUMENTS:
        row = manifest[document_id]
        pages = {}
        with (ROOT / f"data/parsed/{document_id}_pages.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                page = json.loads(line)
                pages[page["pdf_page"]] = page
        audit = json.loads((ROOT / f"reports/{document_id}_page_audit.json").read_text(encoding="utf-8"))
        financial_page = next(s["pdf_page"] for s in audit["samples"] if s["category"] == "financial_table")

        facts: list[tuple[str, str, int, str]] = []
        seen: set[str] = set()
        for page_no in range(financial_page, min(financial_page + 8, max(pages) + 1)):
            text = pages[page_no]["text"]
            unit_line = f"金额单位：{UNITS[document_id]}"
            for raw in text.splitlines():
                line = " ".join(raw.split())
                for label in LABELS:
                    if label in seen or not line.startswith(label + " "):
                        continue
                    tail = line[len(label):].strip()
                    if not any(ch.isdigit() for ch in tail):
                        continue
                    amounts = re.findall(r"(?<![\w(])(?:-?\d[\d,]*\.\d+|-?\d{1,3}(?:,\d{3})+|-?\d{3,})(?![\w)])", tail)
                    if not amounts:
                        continue
                    facts.append((label, amounts[0], page_no, f"{unit_line}；{line}"))
                    seen.add(label)
                    break
        if len(facts) < 15:
            raise RuntimeError(f"{document_id}: only {len(facts)} usable facts")

        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["question_id", "question", "question_type", "target_company", "target_stock_code", "target_year", "reference_answer", "evidence_pages", "evidence_text", "difficulty"])
        prefix = f"{row['stock_code']}{row['report_year']}"
        for index, (label, value, page_no, evidence) in enumerate(facts[:15], 1):
            writer.writerow([
                f"{prefix}_Q{index:02d}",
                f"{row['company_short_name']}{row['report_year']}年末合并口径的{label}是多少（按年报原单位）？",
                "balance_sheet", row["company_name"], row["stock_code"], row["report_year"],
                f"{label}：{value}", page_no, evidence, "easy" if index <= 8 else "medium",
            ])
        csv_text = out.getvalue()
        csv_path = f"data/evaluation/{document_id}_evaluation_questions.csv"
        additions.append(add_file(csv_path, csv_text))

        digest = hashlib.sha256(csv_text.encode()).hexdigest()
        freeze = {
            "document_id": document_id,
            "evaluation_set": csv_path,
            "frozen_before_first_retrieval_run": True,
            "frozen_on": "2026-08-17",
            "question_count": 15,
            "sha256": digest,
            "labeling_method": "从人工核验通过的合并资产负债表抽取候选事实，并逐项保留PDF物理页、原始单位和证据原文；未使用检索结果调题",
            "coverage": {"balance_sheet_facts": 15},
            "constraints": [
                "冻结后不得为提高检索指标修改问题、参考答案或标准证据页",
                "检索与重排代码不得读取question_id、reference_answer或evidence_pages",
                "新增有效替代证据页只能在独立人工审计报告中记录，不回写冻结集",
            ],
        }
        additions.append(add_file(f"reports/{document_id}_evaluation_set_freeze.json", json.dumps(freeze, ensure_ascii=False, indent=2) + "\n"))

    print("*** Begin Patch")
    print("\n".join(item for item in additions if item))
    print("*** End Patch")


if __name__ == "__main__":
    main()
