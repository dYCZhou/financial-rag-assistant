# 现有项目资产与运行路径清单

更新时间：2026-09-13  
对应 GitHub Issue：[M0-01 盘点现有项目资产与运行路径](https://github.com/dYCZhou/financial-rag-assistant/issues/1)

## 1. 当前主运行入口

- Streamlit 应用入口：`app/streamlit_app.py`。
- 启动后先执行 `prepare_runtime()`：读取 Streamlit Secrets 中的配置，并调用 `src/deployment/assets.py` 检查或下载 Release 运行资产。
- 报告选择来自 `data/manifests/annual_reports_manifest.csv`，当前 UI 只展示 `parse_status=retrieval_quality_accepted` 的报告。
- 用户在 UI 输入问题后，`submit_question()` 先判断导览问题和跨企业比较；普通问题进入 `RagPipeline.answer()`。

## 2. 主链路

```text
官方年报 PDF / Manifest
  → 页面级解析与元数据
  → baseline 或 structured Chunk
  → BGE 向量检索（ChromaDB） + 中文 BM25
  → 加权 RRF + 财务口径/数值/表型重排
  → 证据相关度门禁与 Citation 选择
  → DeepSeek 生成（有密钥）或 evidence_only（无密钥）
  → Streamlit 答案、原文、PDF物理页码和来源链接
```

代码对应关系：

| 环节 | 实现 |
| --- | --- |
| 页面解析 | `src/parsing/parse_report.py`（PyMuPDF） |
| 切分 | `src/chunking/baseline_chunker.py`、`src/chunking/structured_chunker.py` |
| 建索引 | `src/indexing/build_index.py`；本地字符向量见 `local_embedding.py`，语义模型见 `semantic_embedding.py` |
| 向量检索 | `src/retrieval/search.py` |
| BM25、RRF、重排 | `src/retrieval/bm25.py`、`src/retrieval/hybrid.py` |
| 生成与证据门禁 | `src/generation/rag.py`、`src/generation/deepseek.py` |
| 前端展示 | `app/streamlit_app.py`、`app/ui_helpers.py` |

## 3. 旁路与实验性资产

这些内容不构成 Streamlit 普通问答的直接入口，但用于准备数据、比较策略、评测或部署：

| 路径 | 用途 | 与主路径的关系 |
| --- | --- | --- |
| `src/ingestion/` | 检查 PDF 并登记到 Manifest | 离线数据入口 |
| `src/parsing/audit_pages.py` | 抽样渲染页面并生成审计包 | 离线质量审计 |
| `src/evaluation/` | 检索、混合检索和 RAG 评测 | 离线验收，不由 UI 调用 |
| `scripts/` | 打包 Demo 资产、构建独立冻结集 | 维护/发布工具 |
| `data/evaluation/`、`reports/` | 冻结题、审计、评测和人工复核证据 | 评测与 UI 验证示例的来源 |
| `src/indexing/local_embedding.py` | 无外部模型依赖的字符 n-gram 基线 | 建索引实验选项；当前配置正式语义模型为 BGE |
| `src/chunking/baseline_chunker.py` | 固定长度切分基线 | 可选策略；当前生成配置默认 `baseline` |
| `src/chunking/structured_chunker.py` | 章节/段落感知切分 | 可选策略；用于对比和评测 |
| `src/generation/comparison.py` | 同年度 2—5 家公司资产负债表比较 | UI 的受限旁路，不属于普通单报告 RAG |

## 4. 主要目录与资产边界

| 目录 | 内容 |
| --- | --- |
| `configs/` | 检索、切分、嵌入和生成参数（`config.yaml`） |
| `data/raw_pdf/` | 原始 PDF 输入；默认不提交 |
| `data/manifests/` | 年报登记、来源、哈希、页数和处理状态 |
| `data/parsed/` | 页面级 JSONL；运行资产，默认不提交 |
| `data/chunks/` | 两种策略的 Chunk JSONL；运行资产，默认不提交 |
| `chroma_db/` | ChromaDB 向量索引；运行资产，默认不提交 |
| `logs/` | 解析/运行日志目录，默认不提交 |
| `reports/` | 质量、审计、评测和验收报告 |
| `src/` | 数据处理、索引、检索、生成和部署代码 |
| `app/` | Streamlit 产品层 |
| `tests/` | 单元测试和轻量集成测试 |

Git 边界由 `.gitignore` 明确：`data/raw_pdf/*.pdf`、`data/parsed/*`、`data/chunks/*`、`chroma_db/*`、`logs/*`、`.env` 和模型/虚拟环境不进入版本库；各目录仅保留 `.gitkeep`。因此新克隆仓库不能仅靠 Git 工作树直接完成完整查询，云端或本地需先准备 Demo 资产。

## 5. 运行命令与环境变量

建议 Python 3.11，并先安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell 对应启动命令：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

完整测试：

```bash
python -m pytest -q
```

离线数据准备的典型命令（每一步都要求前一步产物和验收状态满足要求）：

```bash
python -m src.ingestion.register_report --help
python -m src.parsing.parse_report --document-id 002594_2025
python -m src.parsing.audit_pages --document-id 002594_2025
python -m src.chunking.baseline_chunker --document-id 002594_2025
python -m src.indexing.build_index --document-id 002594_2025 --strategy baseline --embedding-model bge
```

环境变量可放在未提交的 `.env`，模板见 `.env.example`：

| 变量 | 用途 | 必需性 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` 或 `LLM_API_KEY` | DeepSeek 生成鉴权 | 生成摘要时需要；没有则降级 evidence-only |
| `LLM_BASE_URL` | LLM API 地址，默认 `https://api.deepseek.com` | 可选 |
| `LLM_MODEL` | LLM 模型名，默认 `deepseek-v4-flash` | 可选 |
| `DEMO_ASSETS_URL` | 覆盖 Demo 资产下载地址 | 可选 |
| `DEMO_ASSETS_SHA256` | 覆盖 Demo 资产完整性哈希 | 使用自定义资产时需要 |

`EMBEDDING_API_KEY`、`EMBEDDING_MODEL` 在模板中存在，但当前代码路径未使用；正式语义模型由 `configs/config.yaml` 和 `src/indexing/semantic_embedding.py` 指定为 `BAAI/bge-small-zh-v1.5`，首次使用可能需要外网下载模型。

## 6. 已知问题与证据

- **新克隆仓库缺少运行资产。** 证据：`.gitignore` 排除了解析 JSONL、Chunk、ChromaDB 和 PDF；`src/deployment/assets.py` 的 `assets_ready()` 要求本地存在索引、至少 30 个 Chunk 文件和至少 15 个解析文件，不满足时会下载 Release 资产。
- **无 API Key 时不是模型故障。** 证据：`src/generation/rag.py` 的 `_default_generator()` 在 DeepSeek 配置不可用时使用 `EvidenceOnlyGenerator`；UI 会展示原文证据而不伪造模型摘要。
- **BGE 模型和资产冷启动依赖外网。** 证据：`semantic_embedding.py` 通过 `SentenceTransformer` 加载模型；`assets.py` 通过 URL 下载 Demo 资产。网络不可用时应用会提示运行资产准备失败。
- **表格是线性化文本，不是完整二维表格恢复。** 证据：配置将主解析器设为 PyMuPDF，`parse_report.py` 逐页调用 `page.get_text("text", sort=True)`；当前没有二维表格对象输出。
- **当前仍不是生产级服务。** 证据：仓库文档记录尚无应用层限流、完善监控、正式 SLA、Docker 或 CI/CD；本 Issue 不处理这些事项。

## 7. 本次盘点结论与范围

当前产品闭环是“年报 Manifest/运行资产 → Streamlit 单报告问答”，并带一个受限的同年度跨企业资产负债表比较入口。解析、审计、切分、建索引和评测是离线维护链路；本 Issue 仅记录事实基线，不实现 FastAPI、Next.js、PostgreSQL/pgvector、Agent 重写或大规模清理。
