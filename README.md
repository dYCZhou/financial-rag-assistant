# 基于 RAG 的上市公司财报智能问答助手

面向金融研究人员和研究实习生，将 5 家 A 股公司 2023—2025 年年度报告构建为可检索知识库，实现财报语义检索、基于原文的问答、来源引用与 PDF 页码定位。

> 项目边界：这是知识检索与信息整理工具，不提供股票预测、估值、选股或投资建议。

**[立即体验在线Demo](https://financial-rag-assistant-cspk5yuoqjq9a5mf6zx9hg.streamlit.app)**

无需登录。请选择公司与年度，点击“已验证问答示例”即可查看带年报原文和PDF物理页码的回答。

## 当前状态

- 阶段 0：设计确认完成
- 阶段 1：15份目标年报均已从法定披露渠道下载、校验并登记，来源URL、页数、大小和SHA-256可追溯
- 阶段 2：15份年报均已完成页面级解析和人工图像抽查；新增11份共核验64个代表/风险样本页并置为`audited`
- 阶段 3：15份年报均已完成固定长度与章节＋段落感知切分
- 阶段 4：ChromaDB双索引、BGE、中文BM25、加权RRF混合召回和通用重排
  已跑通；15份报告索引可共存并通过公司/年度过滤验证；共享BGE索引
  baseline为4,863条、structured为5,591条；新增11份冻结题最终
  Recall@5为86.67%—100%
- 阶段 5：DeepSeek证据问答已接入；15份报告共225道逐报告冻结题均完成真实调用与人工复核，其中新增11份对应165题全部正确、0拒答、0管线错误
- 阶段 6：Streamlit多公司、多年度问答产品已公开部署；支持首屏项目数据、
  能力导览、真实财报结构、已验证示例、答案状态、引用原文、PDF物理页码、
  来源链接、安全拒答和无密钥证据模式
- 阶段 7：15份报告均有独立冻结15题并完成逐报告验收；仍建议另建不参与调参的跨文档综合测试集

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

## 启动问答应用

应用只开放Manifest中已通过检索质量验收的报告；当前15份目标年报均已通过。

```bash
.venv/bin/streamlit run app/streamlit_app.py
```

打开 `http://localhost:8501`。应用会从 `.env` 读取DeepSeek配置；未配置
API密钥时自动进入仅证据模式，不会把原文摘录冒充模型答案。

## 在线Demo部署

GitHub Pages不能运行本项目的Python、ChromaDB和DeepSeek后端。项目采用
“GitHub代码 + GitHub Release运行资产 + Streamlit Community Cloud”的部署方式。
云端首次启动会下载并校验约103MB的只读索引资产；原始PDF和API密钥不进入资产包。
完整配置、SHA-256和上线验收步骤见[`DEPLOYMENT.md`](DEPLOYMENT.md)。

当前公开地址：

```text
https://financial-rag-assistant-cspk5yuoqjq9a5mf6zx9hg.streamlit.app
```

界面采用固定浅色主题，提供公司/年度联动、最近问题、答案与拒答状态、
可展开引用卡片、PDF物理页码和原始年报链接。每份报告显示4个来自真实
DeepSeek评测且经人工复核正确的“已验证示例”，不使用未经验证的通用兜底题。
“我能问什么”和“查看这份财报的结构”由专用意图路由处理，不消耗LLM额度；
结构来自当前报告真实章节/目录，导览回答下方继续保留4个已验证示例。
正文隐藏`[证据N]`标记以改善阅读体验，但原始结果和下方证据卡片仍保留引用映射。
切换公司或年度时会清空旧答案，避免显示上一份报告的结果。

若全局`streamlit`启动后出现`No module named 'fitz'`，说明误用了系统Python；
必须使用项目`.venv/bin/streamlit`。修改被导入的辅助模块后若热重载报旧符号错误，
应停止进程并完整重启，而不是依赖热重载。

## 阶段 1：数据登记（已完成）

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

15份目标年报均已完成人工视觉核验。新增11份共抽查64个样本，覆盖封面、
目录、普通正文、实际合并财务表格和全部自动标记短页；对应结论保存在
`reports/*_page_audit_review.json`，Manifest 状态为 `audited`。该状态只表示
页面解析质量达到后续切分的输入要求；后续切分、索引、检索和RAG验收记录另行保存，不能仅凭`audited`状态推断。

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
向量。项目使用Python 3.11，且NumPy固定为1.26系列以兼容当前CPU版
PyTorch。建立隔离环境并安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

建立两套语义索引：

```bash
python -m src.indexing.build_index \
  --document-id 002594_2025 --strategy baseline --embedding-model bge
python -m src.indexing.build_index \
  --document-id 002594_2025 --strategy structured --embedding-model bge
```

### 检索小测

`data/evaluation/` 中每份报告均有独立15题。原4套为既有综合题；新增11套
为合并资产负债表事实题，每题记录目标公司、年度、参考答案、原始单位、
PDF物理证据页和证据原文，并由 `reports/*_evaluation_set_freeze.json`
记录冻结日期与SHA-256。新增11套首次盲评原始报告、修复复测及最终报告均保留，运行：

```bash
HF_HUB_OFFLINE=1 python -m src.evaluation.evaluate_hybrid_retrieval
```

产出 `reports/002594_2025_hybrid_retrieval_evaluation.json`，同口径比较
BGE、BM25、加权RRF混合召回和混合召回＋通用重排。Recall@K衡量正确证据
是否进入前K条，MRR衡量正确证据首次出现的排名。验收阈值为Recall@5至少80%。

单独运行BM25或混合检索：

```bash
python -m src.retrieval.bm25 "营业收入是多少？" \
  --strategy baseline --stock-code 002594 --report-year 2025

HF_HUB_OFFLINE=1 python -m src.retrieval.hybrid "研发投入是多少？" \
  --strategy baseline --chunks-dir data/chunks \
  --stock-code 002594 --report-year 2025 --rerank
```

冻结15题实测结果：

| Embedding | 策略 | Recall@3 | Recall@5 | MRR@5 |
| --- | --- | ---: | ---: | ---: |
| 字符n-gram | 固定长度 | 20.00% | 26.67% | 0.2167 |
| 字符n-gram | 章节＋段落 | 13.33% | 13.33% | 0.1000 |
| BGE中文语义 | 固定长度 | 46.67% | 53.33% | 0.4500 |
| BGE中文语义 | 章节＋段落 | 26.67% | 46.67% | 0.2689 |
| 中文BM25＋术语扩展 | 固定长度 | 80.00% | 86.67% | 0.7833 |
| 加权RRF混合召回 | 固定长度 | 80.00% | 86.67% | 0.7833 |
| 混合召回＋口径重排 | 固定长度 | 93.33% | 93.33% | 0.9000 |

固定切分的口径重排已明显超过80%验收线。唯一按冻结页码仍未命中的存货题，
实际首条结果是第174页“存货分类”附注，合计账面价值与标准答案一致；原标准
只标注41和123页，因此自动指标低估了有效证据召回。当前生产候选继续采用
固定切分，同时保留自动指标和人工证据审计。

## 阶段 5：受证据约束的 RAG

阶段5核心链路已经实现：

- 使用固定切分的混合检索＋通用重排取得证据；
- 返回公司、股票代码、年度、章节、PDF物理页码、原文和来源URL；
- 投资建议、估值和股价预测类问题在检索前拒绝；
- 无检索结果或关键词覆盖率过低时拒答；
- Prompt要求每个事实引用证据，禁止补充证据外事实或缺失单位；
- 生成接口与检索、引用逻辑解耦，便于后续替换LLM。

未配置API密钥时默认状态为 `evidence_only`：系统只返回最相关的年报原文，
不把模板摘录冒充生成答案。当前开发环境已配置DeepSeek。运行：

```bash
HF_HUB_OFFLINE=1 python -m src.generation.rag \
  "比亚迪2025年投入了多少研发资金，占营收比例是多少？" \
  --stock-code 002594 \
  --report-year 2025
```

返回状态：

- `answered`：已配置生成器，并生成受证据约束的答案；
- `evidence_only`：未配置LLM，只返回带引用的原文；
- `refused`：问题越界、没有证据或证据相关度不足。

当前15份报告均已完成RAG核心工程、真实调用与逐报告冻结题人工复核；
全项目共225题，其中新增11份对应165题。

### DeepSeek 配置

生成器已接入DeepSeek官方Chat Completions接口，默认使用
`deepseek-v4-flash` 的非思考模式。旧模型别名 `deepseek-chat` 已进入停用
阶段，因此不再作为默认值。

```bash
cp .env.example .env
```

在 `.env` 中填写：

```dotenv
DEEPSEEK_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

`.env` 已被Git忽略。没有密钥时系统自动降级到 `evidence_only`；配置密钥后，
同一条RAG命令会调用DeepSeek并返回 `answered`。生成结果必须至少包含一个
真实 `[证据N]`，且不得引用本次上下文中不存在的编号，否则系统拒绝返回。

真实烟雾测试已完成：使用比亚迪2025年研发投入问题调用
`deepseek-v4-flash`，返回研发投入63,441,379,000元、占营业收入7.89%，
引用PDF第39—40页，端到端耗时16.893秒。结果保存在
`reports/002594_2025_deepseek_rag_smoke_test.json`。这只证明真实调用链路
跑通，不能替代正式答案评估。

冻结15题真实DeepSeek复测也已完成：

- 人工复核完全正确：15/15；
- 证据不足拒答：0/15；
- API或管线错误：0；
- 标准证据页命中率：93.33%；
- 自动答案代理准确率：66.67%（不会处理千元与元的等价换算，仅作辅助）。

详细机器指标和人工复核分别保存在：

- `reports/002594_2025_deepseek_rag_evaluation.json`
- `reports/002594_2025_deepseek_rag_manual_review.json`

比亚迪2023独立冻结15题的SHA-256为
`ccb9bf9ff799083b055f1479a83e4a47861187b7025ae1f3a9a0a13c14f3922f`。
固定切分首次盲评中，BGE、BM25、加权RRF和混合重排的Recall@5分别为
53.33%、93.33%、100.00%和100.00%；混合重排Recall@3为93.33%，
MRR@5为0.9056。真实DeepSeek评估15题全部回答、0管线错误，人工复核
15/15正确，标准证据页引用命中率100%。

比亚迪2024独立冻结15题的SHA-256为
`3ff85ad178d625a55869ee25f01fddcf80e47d5ed375b2000404b3b52f7ec955`。
固定切分首次盲评中，BGE、BM25、加权RRF和混合重排的Recall@5分别为
60.00%、93.33%、100.00%和100.00%；混合重排Recall@3为93.33%，
MRR@5为0.8611。真实DeepSeek评估15题全部回答、0管线错误，人工复核
15/15正确，标准证据页引用命中率100%。

宁德时代2024独立冻结15题的SHA-256为
`4e6d437ec2793334559c8920656c08f4866f0b7e6dc937f7f7e6eaf2aa6e7a5d`。
固定切分首次盲评中，BGE、BM25、加权RRF和混合重排的Recall@5分别为
26.67%、93.33%、93.33%和100%；混合重排Recall@3为100%，MRR@5为
0.8333。结构化切分混合重排Recall@5也为100%。真实DeepSeek评估15题
全部回答、0管线错误、引用页命中率100%，人工复核15/15正确。

因此当前结论是15份目标年报均完成数据、解析、页面抽查、两种切分、共享
BGE索引、独立冻结题检索和RAG人工验收。新增11份最终Recall@5均不低于
80%，新增165题人工复核全部正确；全项目225题均有逐报告人工复核记录，
Manifest均为`retrieval_quality_accepted`。

汇总材料见：

- `reports/11_reports_full_chain_summary.md`：新增11份逐报告最终指标；
- `reports/11_reports_completion_acceptance.md`：新增数据的验收与复验方法；
- `PROJECT_CONTEXT.md`：当前能力、边界和证据索引；
- `PROJECT_INTERVIEW_NOTES.md`：面试讲解与追问口径。

每份 PDF 至少核验：

- 公司和报告所属财年正确；
- 是年度报告全文；
- 文件可以打开；
- 正文可以复制（或明确标记为扫描件）；
- 来源 URL 可追溯；
- 页数、文件大小和 SHA-256 指纹已记录。

## 后续路线

1. 建立不参与当前规则调优的跨公司、跨年度综合测试集
2. 增加跨文档比较与聚合口径
3. 做15份报告的分公司、年度、题型误差分析和性能压测
4. 在干净环境执行部署复验、性能压测并准备固定面试演示脚本

完整决策和验收标准见 `PROJECT_BLUEPRINT.txt`。

## 环境准备

建议使用 Python 3.11：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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
