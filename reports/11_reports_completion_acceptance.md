# 11份新增年报阶段性交付与验收说明

日期：2026-08-17

## 已完成

- 补齐宁德时代2023/2025、贵州茅台2023—2025、美的集团2023—2025、中国移动2023—2025共11份年度报告全文。
- 逐份完成文件可打开性、公司、年度、报告类型、文本性、页数、文件大小与SHA-256校验；官方来源记录在Manifest。
- 逐份生成页面JSONL和解析质量报告。
- 人工查看64个样本页，覆盖封面、目录、正文、合并资产负债表及全部自动异常页；11份均通过页面抽查。
- 为每份报告建立独立15题，共165题；每题保存参考答案、原始单位、PDF物理页与证据原文，并为每份CSV保存SHA-256冻结记录。

## 最终验收结论（2026-08-18更新）

新增11份报告已完成两种切分、共享BGE索引、冻结题首次盲评、通用检索修复、最终复测、真实DeepSeek调用和人工复核。最终Recall@5为86.67%—100%；165题全部回答且人工复核正确，0拒答、0 API或管线错误。11份Manifest状态已升级为`retrieval_quality_accepted`。

首次盲评未覆盖问题被如实保留；修复只修改通用检索、证据门禁和引用窗口逻辑，没有修改冻结题、参考答案、标准页或SHA-256。美的2023存货题使用有效替代证据页，冻结集未回写。

## 建议验收步骤

1. 核对 `data/manifests/annual_reports_manifest.csv` 中11行的官方URL、页数、哈希和最终`retrieval_quality_accepted`状态；页面抽查通过记录在独立review JSON中。
2. 任抽一份 `reports/*_page_audit_review.json`，对照其PNG与页面JSONL，确认表格单位和数字一致。
3. 校验每个 `data/evaluation/*_evaluation_questions.csv` 恰有15题，并重算SHA-256与对应freeze JSON比较。
4. 依次运行baseline/structured切分与索引，不跨报告共享题集。
5. 每份题集只做一次首次盲评；以Recall@5≥80%作为最低检索门槛，并记录Recall@3、MRR@5和替代证据人工审计。
6. 检索通过后运行15题RAG，人工核对答案、单位、年份、公司和引用页；通过后才把Manifest状态改为`retrieval_quality_accepted`。
7. 使用`.venv/bin/streamlit run app/streamlit_app.py`启动网页，检查公司/年度过滤、每份报告4个已验证示例、引用页链接、正文隐藏引用编号、无密钥证据模式、越界拒答和跨文档串答。

## 可复验命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m src.parsing.audit_pages --document-id 600941_2025
shasum -a 256 data/evaluation/600941_2025_evaluation_questions.csv
```

截至2026-08-18，自动化测试基线为62项通过；该数字应随新增测试更新，不作为永久固定指标。
