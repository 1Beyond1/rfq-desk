# 航材询报价工作台 · RFQ Desk

[English](README.en.md)

面向航空器材询报价场景的 **Agent 辅助工作台**。将客户的询价邮件（正文、表格、PDF 附件）转化为可追溯、可审核、可放行的正式报价单：Agent 负责读原文、提取带行级出处的候选、查库存与历史报价、匹配有效价表并起草澄清邮件；**接纳候选、核价、批准和导出始终由人工在工作台内确认**，任何改动都会自动令旧批准失效。

---

## 界面预览

| 询价 Agent 工作台（工具调用时间线 + 原文对照） | 候选审阅（逐字段绑定原文出处） |
|---|---|
| ![询价 Agent 工作台](docs/assets/agent.jpg) | ![候选审阅](docs/assets/review.jpg) |

<details>
<summary>查看更多截图：四项检查通过与版本批准</summary>

![批准当前版本](docs/assets/approve.jpg)

</details>

---

## 核心特性

- **多格式原件解析与出处绑定**：支持导入 `EML`、`CSV`、`XLSX`、文本型 `PDF` 与 `TXT`，自动识别中英文表头；每个提取出的字段（询价号、件号、数量、单位、件状、交期等）均绑定到原件文件的具体位置，点击即可在右侧原文高亮核对。
- **权限清晰的询价 Agent（Human-in-the-Loop）**：
  - 区分工作区首页工具与工单内工具，支持读取原件、提取结构化候选、查库存/历史报价/替代件、检索业务规则、比对版本历史与起草澄清邮件；
  - Agent 不持有任何修改正式数据、录入价格、批准或发送邮件的写工具，从机制上阻断提示词注入导致的越权操作。
- **严格业务规则与版本防漂移**：
  - 同件号不同询价号绝不误合并；重复行、修订冲突、未知缩写、缺价、过期价格均显式拦截；
  - 金额计算全程采用 `Decimal`（后端）与 `BigInt` 定点运算（前端），按币种分列合计，不擅自折汇；
  - 批准锁定整单有效行集合、原件快照、核查结论与待审状态；后续删行、改数、追加修订原件或更新价表均会自动失效旧批准并拦截旧版本导出（`409`）。
- **收件箱分流与参考知识库**：内置合成收件箱分流流程，支持按明确件号执行精确查询，或按自然语言描述结合向量召回匹配候选件号与业务规则。
- **可选 MatrixOne 扩展**：SQLite 作为本地主记录源保证断网可用；配置 MatrixOne 后可启用 SQL/向量检索、批准整库快照、候选数据分支差异、决策审计与 Agent 记忆同步。
- **多账号隔离与桌面/移动端引导**：支持普通用户、管理员与免注册隔离体验空间（`scrypt` 密码哈希、SHA-256 落库会话、`HttpOnly`/`SameSite=Strict`、Origin/CSRF 防护），并提供自适应桌面端与 375–390px 手机端的交互式聚光灯引导（Spotlight Tour）。

---

## 处理流程

```mermaid
flowchart LR
    A[原始邮件 / 附件<br/>EML · XLSX · PDF · CSV] --> B[询价 Agent<br/>提取候选 · 查价 · 查库存 · 起草澄清]
    B --> C[人工逐字段核对<br/>绑定原文行级出处]
    C --> D[正式询价行<br/>冲突/澄清清零 + 有效价表匹配]
    D --> E[人工批准当前版本<br/>锁定快照与批准人身份]
    E --> F[服务端二次核验导出<br/>HTML 报价响应 · CSV]
    D -. 任意修改 / 追加原件 .-> G[旧批准自动失效<br/>导出拦截 409]
```

---

## 快速开始

### 环境要求

- Python **3.12+**
- Node.js **20+**（仅用于运行前端单元测试）

### 1. 安装依赖

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

### 2. 启动本地离线模式（零外部依赖，开箱可试）

离线模式下全部合成示例、收件箱、人工核对、价表录入、批准、预览与导出均可完整运行（不向外发送任何模型请求）：

**Windows (PowerShell)**

```powershell
.\.venv\Scripts\python.exe distribution/serve.py
```

**macOS / Linux**

```bash
./.venv/bin/python distribution/serve.py
```

启动后访问 [http://127.0.0.1:5311/](http://127.0.0.1:5311/)（后端 API 监听 `http://127.0.0.1:8311`）。

### 3. 启用账号登录与 AI 模型（可选）

启用 OpenAI 兼容接口运行询价 Agent 与候选提取：

```bash
export RFQ_AUTH_REQUIRED=1
export RFQ_COOKIE_SECURE=0           # 本地 HTTP 调试设为 0，生产 HTTPS 保持 1
export RFQ_MODEL_URL="https://api.example.com/v1/chat/completions"
export RFQ_MODEL_NAME="your-model-name"
export RFQ_MODEL_KEY="your-api-key"

./.venv/bin/python distribution/serve.py --model
```

> 本地账号管理可使用 CLI 工具 `python scripts/accounts.py` 创建管理员与普通用户。完整变量说明见 [`.env.example`](.env.example)。

---

## 运行测试

```bash
# 后端 Python 测试套件
python -m pytest tests -q

# 前端 JavaScript 语法检查与 Node 单元测试
node --test tests/*.test.cjs
```

---

## 目录结构

```text
rfq-desk/
├── apps/
│   ├── api/            # FastAPI 后端：解析、业务域规则、Agent、账号、收件箱、MatrixOne 镜像
│   └── web/            # 原生 HTML/CSS/JS 三栏工作台、响应式移动端适配与 Spotlight 引导
├── data/
│   └── synthetic/      # 100% 合成的演示邮件、表格、价表、收件箱与参考库数据
├── distribution/       # 单进程前后端联合启动脚本与容器自检工具
├── docs/               # 数据字典、澄清闭环、草稿恢复、账号与运行手册及界面截图
├── evals/              # 原文证据索引（EvidenceIndex）与离线/协议评测集
├── scripts/            # 本地静态服务（支持 Range 206）、账号 CLI 与合成数据生成脚本
└── tests/              # Python pytest 与 Node 前端单元测试
```

---

## 延伸文档

- [账号隔离与体验引导说明](docs/ACCOUNTS_AND_GUIDE.md)
- [数据字典](docs/DATA_DICTIONARY.md)
- [澄清闭环规范](docs/CLARIFICATION_LOOP.md)
- [价表导入规范](docs/PRICE_IMPORT.md)
- [本地草稿恢复设计](docs/DRAFT_RECOVERY.md)
- [本地演示与运行手册](docs/DEMO_RUNBOOK.md)

## 许可证

本项目基于 [MIT License](LICENSE) 开源。仓库内所有业务样本数据均为人工构造的合成数据，不代表真实客户或商业报价。
