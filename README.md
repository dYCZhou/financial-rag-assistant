# 基于 RAG 的上市公司财报智能问答助手

面向金融研究人员和研究实习生，将 5 家 A 股公司 2023—2025 年年度报告构建为可检索知识库，实现财报语义检索、基于原文的问答、来源引用与 PDF 页码定位。

> 项目边界：这是知识检索与信息整理工具，不提供股票预测、估值、选股或投资建议。

## 当前状态

- 阶段 0：设计确认完成
- 阶段 1：数据验收与自动登记工具已完成；比亚迪 2025 年报已登记
- 阶段 2：页面级解析与抽查工具已完成；比亚迪 2025 年报已通过人工确认
- 阶段 3：固定长度与章节＋段落感知切分均已实现并完成结构对比
- 阶段 4：ChromaDB双索引与可追溯检索已跑通；已接入正式中文语义
  Embedding 并完成15题冻结小测，但 Recall@5 仍未达到80%验收线
- 阶段 5—7：尚未实现

不要因为目录和文件已经存在，就把对应模块写进简历成果。只有通过验收的功能才算完成。

## 数据范围

| 公司 | 股票代码 | 财年 |
|---|---|---|
| 比亚迪 | 002594 | 2023、2024、2025 |
| 宁德时代 | 300750 | 2023、2024、2025 |
| 贵州茅台 | 600519 | 2023、2024、2025 |
| 美的集团 | 000333 | 2023、2024、2025 |
| 中国移动 | 600941 | 2023、2024、2025 |

仅采集年度报告全文 PDF，不用摘要、半年报或季度报告代替。

## 目录用途

```text
financial-rag-assistant/
├── configs/                # 可调整参数
├── data/
│   ├── raw_pdf/            # 原始年报 PDF
│   ├── manifests/          # 数据来源和验收清单
│   ├── parsed/             # 页面级 JSONL
│   ├── chunks/             # Chunk 级 JSONL
│   └── evaluation/         # 人工标注测试集
├── chroma_db/              # 本地向量索引（不提交 Git）
├── src/
│   ├── ingestion/          # 数据登记与文件校验
│   ├── parsing/            # PDF 逐页解析与清洗
│   ├── chunking/           # 章节/段落感知切分
│   ├── indexing/           # Embedding 与 ChromaDB 入库
│   ├── retrieval/          # 元数据过滤与 Top-K 检索
│   ├── generation/         # 受证据约束的答案生成
│   └── evaluation/         # 检索、回答、引用和耗时评估
├── app/                    # Streamlit 界面
├── tests/                  # 自动化测试
├── reports/                # 实验报告与误差分析
└── logs/                   # 运行日志（不提交 Git）
```

## 阶段 1：现在该做什么

1. 从法定披露渠道或公司投资者关系官网逐份下载年报全文。
2. 按 `股票代码_公司简称_报告年度_annual_report.pdf` 命名。
3. 放入 `data/raw_pdf/`。
4. 下载一份、验收一份，不要先堆满 15 份再检查。
5. 使用登记工具自动更新 `data/manifests/annual_reports_manifest.csv`。

登记命令示例：

```bash
python -m src.ingestion.register_report \
  /path/to/downloaded.pdf \
  --document-id 002594_2025 \
  --source-url "https://static.cninfo.com.cn/finalpage/2026-03-28/1225045351.PDF" \
  --publish-date 2026-03-28
```

工具会检查 PDF 能否打开、公司/年度/报告类型关键字以及正文可提取性，
再自动复制为统一文件名，并回填页数、大小、SHA-256 和数据状态。它不会
仅凭文件名登记，也不会把“已验收”冒充成“已完成页面解析”。

## 阶段 2：页面解析

将已通过验收的报告解析为逐页 JSONL：

```bash
python -m src.parsing.parse_report --document-id 002594_2025
```

产出：

- `data/parsed/002594_2025_pages.jsonl`：每行代表一页，保留公司、年度、
  PDF 物理页码、印刷页码、章节、正文、来源和异常标记。
- `reports/002594_2025_parse_quality.json`：字符量、异常短页、空页、
  页眉页脚清理结果等质量指标。

自动识别不可靠时，`printed_page` 保持空值、`chapter` 保持 `unknown`，
避免把猜测写成事实。`parse_status=parsed` 只代表程序解析完成，仍需人工
抽查封面、目录、正文、财务报表和异常页。

生成页面抽查包：

```bash
python -m src.parsing.audit_pages --document-id 002594_2025
```

产出：

- `reports/002594_2025_page_audit.md`：带复选框、页面图和提取文本的人工抽查报告。
- `reports/002594_2025_page_audit.json`：机器可读的抽样结果。
- `reports/002594_2025_audit_assets/`：被抽查PDF页的PNG图像。

自动选样只负责把高风险页面暴露出来，不能替代人工判断。只有逐项确认页面图像、
提取文本、表格数字和异常页原因后，才能进入文本切分阶段。

比亚迪 2025 年报已完成 6 个代表样本的视觉核验，Manifest 状态为
`audited`。该状态只表示页面解析质量达到后续切分的输入要求，不表示
Chunk、检索或RAG问答已经完成。

## 阶段 3：固定长度切分基线

将已通过页面人工抽查的报告按固定字符长度切分：

```bash
python -m src.chunking.baseline_chunker \
  --document-id 002594_2025 \
  --chunk-size 800 \
  --chunk-overlap 150
```

产出：

- `data/chunks/002594_2025_baseline_chunks.jsonl`：用于后续向量检索的
  基线Chunk，每条保留公司、年度、章节、PDF页码范围和来源。
- `reports/002594_2025_baseline_chunk_quality.json`：Chunk数量、长度、
  跨页和跨章节统计。

`chunk_size` 是单个文本块允许包含的字符数，作用是控制检索粒度；
`chunk_overlap` 是相邻文本块重复保留的字符数，作用是降低答案恰好被
切分边界截断的风险。固定切分不是最终方案，它是章节感知切分的实验基线。

### 章节＋段落感知切分

固定长度基线完成后，运行优化切分与结构质量对比：

```bash
python -m src.chunking.structured_chunker \
  --document-id 002594_2025 \
  --target-chars 800 \
  --max-chars 1000 \
  --overlap-chars 150 \
  --max-unit-chars 400

python -m src.chunking.compare_strategies \
  --document-id 002594_2025
```

优化版把章节视为硬边界，并优先在段落或句子结束处切分；相邻块的重叠
由完整文本单元组成。它仍允许完整论述跨越PDF页面，也不会把线性化表格
宣称为二维结构化表格。边界更规整不等于检索一定更准，最终必须使用同一
问题集比较Top-K检索指标。

## 阶段 4：Embedding 与 ChromaDB

分别为固定切分和优化切分建立独立索引：

```bash
python -m src.indexing.build_index \
  --document-id 002594_2025 \
  --strategy baseline

python -m src.indexing.build_index \
  --document-id 002594_2025 \
  --strategy structured
```

带公司和年度过滤进行检索：

```bash
python -m src.retrieval.search "海外市场和出口业务表现如何？" \
  --strategy structured \
  --stock-code 002594 \
  --report-year 2025 \
  --top-k 5
```

字符基线 `local-character-ngram-v1` 将中文字符及其相邻组合映射为768维向量，
用途是离线验证建库、查询、过滤和页码追溯，不能冒充正式中文语义模型。
真实建库结果为基线384条、优化版439条。3题烟雾测试中，海外业务的正确
证据在优化版排第2；营业收入、研发投入问题未稳定命中正确证据，因此当前
结论是“索引管线通过，字符检索质量未通过”。

正式中文语义模型采用固定版本的 `BAAI/bge-small-zh-v1.5`，生成512维
向量。CPU环境先安装PyTorch CPU版，再安装其余依赖：

```bash
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

建立两套语义索引：

```bash
python -m src.indexing.build_index \
  --document-id 002594_2025 --strategy baseline --embedding-model bge
python -m src.indexing.build_index \
  --document-id 002594_2025 --strategy structured --embedding-model bge
```

### 检索小测

`data/evaluation/evaluation_questions_template.csv` 现包含15道人工标注题，
每题记录标准公司、年度、参考答案、PDF物理证据页和证据原文。运行：

```bash
python -m src.evaluation.evaluate_retrieval
```

产出 `reports/002594_2025_retrieval_evaluation.json`，分别报告固定切分与
优化切分的 Recall@3、Recall@5 和 MRR@5。Recall@K衡量正确证据是否进入
前K条，MRR衡量正确证据首次出现的排名。当前验收阈值为Recall@5至少80%；
若字符向量未达标，应保留失败结果并替换正式中文语义Embedding，不得改题
或放宽标准证据页来制造通过。

冻结15题实测结果：

| Embedding | 策略 | Recall@3 | Recall@5 | MRR@5 |
| --- | --- | ---: | ---: | ---: |
| 字符n-gram | 固定长度 | 20.00% | 26.67% | 0.2167 |
| 字符n-gram | 章节＋段落 | 13.33% | 13.33% | 0.1000 |
| BGE中文语义 | 固定长度 | 46.67% | 53.33% | 0.4500 |
| BGE中文语义 | 章节＋段落 | 26.67% | 46.67% | 0.2689 |

BGE让固定切分Recall@5提高26.66个百分点、结构化切分提高33.34个百分点，
证明语义模型有效，但两套索引仍未达到80%阈值。失败题主要集中在财务表格、
同类指标密集页面和简写/全称差异。下一步不能直接进入RAG生成，而应增加
关键词与向量混合召回，并对Top-K候选做重排；否则LLM只会把错误证据说得更流畅。

每份 PDF 至少核验：

- 公司和报告所属财年正确；
- 是年度报告全文；
- 文件可以打开；
- 正文可以复制（或明确标记为扫描件）；
- 来源 URL 可追溯；
- 页数、文件大小和 SHA-256 指纹已记录。

## 后续路线

1. 数据获取与管理
2. PDF 解析 Pipeline
3. 文本切分优化
4. Embedding 与 ChromaDB
5. RAG 问答和引用
6. Streamlit 产品化
7. 50 题效果评估与实验报告

完整决策和验收标准见 `PROJECT_BLUEPRINT.txt`。

## 环境启动（当前仅用于准备项目）

建议使用 Python 3.11：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 激活命令：

```powershell
.\.venv\Scripts\Activate.ps1
```

复制环境变量模板：

```bash
cp .env.example .env
```

API 密钥只写入本地 `.env`，不得提交到 Git。
