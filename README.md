# 航材询报价工作台 · RFQ Desk

把一封航材询价邮件（正文、表格、PDF）处理成可以放行的报价单。每个询价字段都绑定原文出处；重复、冲突、缺价、过期这些问题会挡住批准，不会被悄悄合并或补全。

参赛：MatrixNEXT 2026，赛题“RFQ 询价分析与报价智能体”。

## 能做什么

- **导入原件**：EML、CSV、XLSX、文本型 PDF、TXT。表格按表头识别询价号、件号、数量、单位、件状等列（中英文表头均可）。
- **询价 Agent**：贴一封邮件或在工作单里提问，它会提取询价行、查价、解释为什么还不能批准，有缺口时起草发给对方的澄清邮件。它的工具只能读取、提议和起草；接纳候选、改字段、录价、批准、导出、发送都由人在页面上完成。
- **模型提取候选**：自由文本邮件由模型提出候选行，每个值都必须是原文里逐字出现的片段，人工核对后才进入正式询价行。
- **核对与澄清**：同件号不同询价号不合并；同一询价里的重复、修订、数量冲突分别处理；不认识的缩写不解释，标出来等人确认。
- **核价**：按件号、单位、件状和有效期匹配价表；没有唯一有效价格时保持待报价。
- **批准与输出**：批准绑定当时的询价行、价格和澄清状态，之后任一项变化，旧批准自动失效。输出 HTML / CSV 报价响应。

## 运行

需要 Python 3.12，依赖在本目录的 `.venv`。

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe distribution/serve.py
```

打开 http://127.0.0.1:5311 。以上是离线模式，不调用任何模型：合成演示和人工流程都可用，询价 Agent 和模型提取不可用。

启用模型（OpenAI 兼容接口）：

```powershell
$env:RFQ_MODEL_URL="https://.../v1/chat/completions"
$env:RFQ_MODEL_KEY="..."
$env:RFQ_MODEL_NAME="..."
./.venv/Scripts/python.exe distribution/serve.py --model
```

每日调用次数上限默认 100，可用 `RFQ_MODEL_MAX_CALLS` 调整。它只限制次数，不限制金额。数据库和上传文件在 `var/`，不进 Git。

## 测试

```powershell
./.venv/Scripts/python.exe -m pytest tests -q
```

## 数据

- `data/synthetic/`：人工编写的合成邮件、表格和演示价表，可以公开演示，也可以发给模型。
- `data/raw/`：本机官方素材，不进 Git，不发给任何模型，仅用于本地解析研究。

## 现状与局限

最新进展见 [docs/STATUS.md](docs/STATUS.md) 末尾几节。主要局限：

- 模型和 Agent 的成绩都来自合成邮件，没有真人试用。
- MatrixOne / MOI 平台能力尚未接入，`apps/api/platform_snapshot.py` 只是文件格式层面的准备。
- Agent 一轮约 8 到 15 秒，没有流式进度。
- XLSX、PDF 询价附件的完整上传体验尚未在浏览器里走查。
