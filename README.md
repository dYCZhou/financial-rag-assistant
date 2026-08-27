# 基于 RAG 的上市公司财报智能问答助手

面向金融研究人员与研究实习生的证据约束 RAG 系统：从上市公司年度报告中检索原文，生成可追溯的财务信息回答，并提供 PDF 物理页码与来源链接。

在线 Demo：<https://financial-rag-assistant-cspk5yuoqjq9a5mf6zx9hg.streamlit.app>

## 你可以做什么

- 选择公司与年度，查询年报中的财务事实并查看原文证据；
- 查看 PDF 物理页码和原始年报链接；
- 使用已验证示例、能力导览和真实报告结构导览；
- 比较同一年 2—5 家公司的指定资产负债表指标，查看逐公司证据和统一口径排序；
- 在没有 API Key 时使用仅证据模式。

项目明确不提供投资建议、估值、选股或股价预测。

## 当前范围

覆盖比亚迪、宁德时代、贵州茅台、美的集团和中国移动 2023—2025 年的 15 份年度报告。系统采用 PDF 数据治理、页面审计、双策略切分、BGE 与中文 BM25 混合检索、加权 RRF、财务口径重排、证据门禁与引用校验。

## 本地启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
.venv/bin/streamlit run app/streamlit_app.py
```

必须使用项目虚拟环境中的 Streamlit。应用会从 `.env` 读取 DeepSeek 配置；未配置密钥时会降级为仅证据模式。

> 新克隆仓库不含原始 PDF、索引和模型缓存。在线部署会下载 Release 运行资产；本地运行时请自行准备资产或走同一下载流程。

## 项目全貌、评测与维护

开发、部署、评测、简历、面试与迭代信息统一见 [PROJECT_MASTER.md](PROJECT_MASTER.md)。原始解析、审计和实验记录保留在 `data/` 与 `reports/` 中，作为可复验证据。
