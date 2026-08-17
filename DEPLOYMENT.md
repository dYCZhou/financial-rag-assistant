# 在线Demo部署说明

当前部署方案：GitHub托管代码，GitHub Release托管只读运行资产，Streamlit Community Cloud运行应用。

公开Demo：<https://financial-rag-assistant-cspk5yuoqjq9a5mf6zx9hg.streamlit.app>

## 架构与资产

Release `demo-assets-v1`中的`financial-rag-demo-assets-v1.tar.gz`包含：

- `chroma_db/`：15份报告的baseline/structured BGE索引；
- `data/chunks/`：30份双策略Chunk JSONL；
- `data/parsed/`：15份页面JSONL，用于财务附注单位上下文。

压缩包不包含原始PDF、API密钥、日志或模型缓存。当前资产：

```text
bytes: 103284781
sha256: 913b1a9a89e074c4ee9a858000a7db27176c0d2f8518727b06c2e482d81bb6fb
```

`src/deployment/assets.py`在首次启动时下载资产、校验SHA-256、拒绝路径穿越和链接文件，并检查30个Chunk文件、15个页面文件与Chroma数据库。实例重启后如本地资产消失，会重新下载。

## Streamlit Community Cloud配置

1. 登录`share.streamlit.io`并连接GitHub。
2. 选择仓库`dYCZhou/financial-rag-assistant`、分支`main`。
3. Main file path填写`app/streamlit_app.py`。
4. Advanced settings中选择Python 3.11。
5. Secrets填写：

```toml
DEEPSEEK_API_KEY = "单独创建的演示密钥"
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"
```

`DEMO_ASSETS_URL`与`DEMO_ASSETS_SHA256`已有代码默认值。只有发布新资产版本时才需要在Secrets临时覆盖：

```toml
DEMO_ASSETS_URL = "新的Release下载地址"
DEMO_ASSETS_SHA256 = "新的64位SHA-256"
```

## 发布新资产

本地准备好`chroma_db`、`data/chunks`和`data/parsed`后运行：

```bash
.venv/bin/python -m scripts.package_demo_assets
shasum -a 256 dist/financial-rag-demo-assets-v1.tar.gz
```

上传新Release前必须更新文件名、Release标签、`DEFAULT_ASSET_URL`和`DEFAULT_ASSET_SHA256`，避免用同一URL静默替换不同内容。

## 上线验收

1. 首次冷启动能完成约103MB资产下载，并显示首页而非堆栈。
2. 15份报告各显示4个已验证示例。
3. 至少抽查两家公司、两个年度，答案与引用不串库。
4. DeepSeek配置有效时返回答案；移除密钥时降级为证据模式。
5. 投资建议问题被拒答。
6. 日志不出现API密钥、用户完整请求历史或内部调用栈。

## 运维边界

- 免费实例可能休眠，HR首次打开可能经历冷启动。
- Release资产与BGE模型首次下载依赖外网。
- 应为公开Demo使用独立、低余额、可撤销的DeepSeek密钥。
- 当前未实现全局每日额度和用户级限流，公开投放前应在DeepSeek侧设置预算并定期检查用量。
