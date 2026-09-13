"""Rebuild the missing BYD 2025 frozen evaluation set from its audit record."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.evaluation.frozen_sets import frozen_sha256


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/002594_2025_deepseek_rag_evaluation.json"
CSV_PATH = ROOT / "data/evaluation/002594_2025_evaluation_questions.csv"
FREEZE_PATH = ROOT / "reports/002594_2025_evaluation_set_freeze.json"

def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    fields = [
        "question_id", "question", "question_type", "target_company",
        "target_stock_code", "target_year", "reference_answer", "evidence_pages",
        "evidence_text", "difficulty",
    ]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for case in source["cases"]:
            evidence_pages = [int(page) for page in case["gold_evidence_pages"]]
            evidence_text = (
                "历史评测记录摘要；标准证据页："
                + "、".join(str(page) for page in evidence_pages)
                + "；参考答案："
                + case["reference_answer"]
            )
            writer.writerow({
                "question_id": case["question_id"],
                "question": case["question"],
                "question_type": case["question_type"],
                "target_company": "比亚迪股份有限公司",
                "target_stock_code": "002594",
                "target_year": "2025",
                "reference_answer": case["reference_answer"],
                "evidence_pages": "|".join(str(page) for page in evidence_pages),
                "evidence_text": evidence_text,
                "difficulty": case["difficulty"],
            })

    freeze = {
        "document_id": "002594_2025",
        "evaluation_set": "data/evaluation/002594_2025_evaluation_questions.csv",
        "question_count": len(source["cases"]),
        "frozen_before_first_evaluation": True,
        "frozen_on": "2026-07-31",
        "sha256": frozen_sha256(CSV_PATH),
        "label_source": "从历史人工复核评测记录恢复题目、参考答案和标准证据页；当前仓库缺少原始PDF和解析页面，因此未重新抽取证据原文",
        "evidence_page_type": "pdf_physical_page",
        "source_audit": "reports/002594_2025_deepseek_rag_manual_review.json",
        "notes": [
            "题目、参考答案和标准证据页来自既有 002594_2025 评测记录",
            "人工复核记录显示 15/15 题正确；本次恢复不修改该历史结论",
            "冻结后不得为提高检索指标修改题目、参考答案或标准证据页",
        ],
    }
    FREEZE_PATH.write_text(
        json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"rebuilt={CSV_PATH}")
    print(f"sha256={freeze['sha256']}")


if __name__ == "__main__":
    main()
