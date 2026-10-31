## 2026-10-29 当前同步与实验状态

新运行包见 submissions/competitive-20261028/README.md；字段级人工归属审阅已实现，中文自由表达的可靠性与真正多轮工具Agent对照尚未完成。阶段累计19次Chat/75089保守tokens、费用unknown；本阶段原墙钟到期，未清账。详情见 docs/STATUS.md。submission_ready=false。

## 2026-10-28 真实模型有限验证

本地启动：`.\.venv\Scripts\python.exe scripts/serve_model_live.py`，入口http://127.0.0.1:8351/；仅本地进程读取指定私密配置，旧默认实例仍离线。已8次真实调用，保守22125tokens，费用unknown；主控单批修复后明示英文语句含截止日期可经人工核价批准，修订使旧批准失效。其他自由语句仍受独立证据语法限制，submission_ready=false。完整启动/预算/停止/结果见[本轮记录](docs/MODEL_LIVE_20261027.md)。运行副本和原件与旧库隔离，不重包既有交付。

# 航材询报价工作台 · RFQ Desk

2026-10-26 当前产品质量阶段 `product-quality-20261026-1`：现有青绿界面已接入按行澄清、答复审阅结论、进度摘要、纯预览与显式正式导出。补齐批准人刷新保护、价表等待中新修改及刷新恢复；**项目自测完成，等待主控独立新案验收**，不能称已到获奖水平。当前源码与旧运行ZIP分开，旧包/旧材料保留历史版本，尚未重包或重录。真实AI/平台与专业试用仍未运行，`submission_ready=false`。

当前源码隔离入口：[本机工作台](http://127.0.0.1:5311/)，已有两单均为合成验证数据；请导入新样例做独立验收。准确范围、运行与证据见 [本轮交付](docs/PRODUCT_QUALITY_20261026.md) / [STATUS](docs/STATUS.md)。恢复同一隔离库（不清库、不改原主库）：

```powershell
./.venv/Scripts/python.exe scripts/prepare_product_quality.py
./.venv/Scripts/python.exe -I var/product-quality-20261026/runtime/distribution/serve.py
```

仅在两端口空闲时启动；已在运行则直接访问，不重复开服务。统一前台进程绑定127.0.0.1:8311/5311，Ctrl+C停止本次进程。新建业务原件使用 `data/synthetic/clarification/`。首次环境安装要求仍见下方，当前本项目依赖已具备。

API地址可在 `apps/web/config.js` 明确设置 `window.RFQ_CONFIG={apiBase:'/api'}` 或HTTPS地址；本机默认仍为8311，未配置的远程页面默认同源 `/api`。这只是受控配置能力，实际服务器/认证/域名/TLS/评委访问另需安排，本轮没有部署或放宽CORS。不得向配置文件写密钥。8项新UI契约检查：`node --test tests/ui-contracts.test.cjs`。

2026-10-26提交制作收尾：已制作并从新目录实测[独立本地ZIP](submissions/release-20261025/rfq-desk-local-candidate-20261025.zip)、[99.32秒真实界面字幕视频](submissions/release-20261025/media/DEMO_CURRENT.mp4)、[说明HTML](submissions/release-20261025/SUBMISSION_TEXT.html)和[提交清单](submissions/release-20261025/SUBMISSION_MANIFEST.json)。**submission_ready=false**：三条评委链接、localhost远程API接线、身份报名、真实AI验证与规则口径仍待落实；不等于已可正式投递。新包首次需联网安装，完整体验见包内README；原工作数据/Claude前端保留。

2026-10-25当前后端兼容阶段已完成并待总控验收，未改Claude前端。API增量契约、需前端接线、完整143项Python/18项Node及新UI实测见[后端交接回执](docs/FRONTEND_HANDOFF_BACKEND.md)。当前验收服务使用独立`var/backend-alignment-20261025/ui.sqlite3`；旧主库保留。启动脚本不再硬依赖Git，`./scripts/start.ps1 api -CheckOnly`可仅核路径。

本地询报价工作台（仍在争奖前产品完善，非参赛完成）：EML/XLSX/文本型PDF→可追溯询价行/待审候选→重复/冲突人工裁定→有据核价→批准/导出→相关变更后旧批准失效。当前展示离线规则、合成价格和人工审阅；真实模型与MOI/Genesis未运行。目标Top20并冲Top3不是成绩或概率。

上一候选版和总控实际体验验收结果沿用。2026-10-25新有限阶段只完成[官方平台要求及Catalog快照契约准备](docs/PLATFORM_READINESS.md)：默认关闭、只合成注入验证，不接入主业务发送，不代表平台原生版本管理或真实接入。现等待总控集中验收；真实平台/模型/强Agent调优冻结留出/专业试用仍未运行，不自动扩下一阶段。

## 本地启动（PowerShell）

所有命令从 `<repo-root>` 执行，Git根目录应相同，main分支。依赖已安装时跳过首次安装，不重建环境或覆盖素材。

```powershell
Set-Location <repo-root>
# 仅首次需要：系统有python时也可用python -m venv .venv
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
# 终端一：本地演示必须禁用真实模型请求
$env:RFQ_ENABLE_MODEL_REQUESTS='0'
./scripts/start.ps1 api
# 终端二：同一项目目录
./scripts/start.ps1 web
```

打开 http://127.0.0.1:5311 ，API文档 http://127.0.0.1:8311/docs 。默认端口8311/5311只绑定127.0.0.1；占用时核查归属，不终止其他项目。Ctrl+C停止自己终端。当前运行PID与恢复信息见[STATUS](docs/STATUS.md)，工具会话退出后需重新启动。Web入口现在使用scripts/serve_web.py返回no-store，避免继续显示旧版脚本。

技术栈FastAPI+SQLite+原生JS/CSS，无前端构建安装。完整Python依赖锁在requirements.txt，.venv/与运行数据var/独立。没有自动dotenv加载器，模型配置仅从当前进程环境读取；演示不需要密钥。

## 本轮产品入口

- 首页按实际状态显示下一步、异常待办和定位；演示/模型诊断收进次要入口。
- [本地澄清往返](docs/CLARIFICATION_LOOP.md)：登记绑定行/字段的问题，导出草稿，追加并关联答复；离线候选局部回填或人工裁定后明确解决，收到/未决/过期分开，未决项阻止批准。系统不发邮件。
- 行字段及理由在当前页面会话中保留为未保存草稿，切行/搜索/筛选/切案件可恢复；服务器版本变化保留旧草稿并拒绝覆盖。放弃按钮恢复服务器值，离开页面有提示，现有当前源的浏览器本地恢复入口，详见[草稿恢复范围](docs/DRAFT_RECOVERY.md)；不承诺跨浏览器/OS断电恢复。
- [CSV/XLSX价目规范与示例](docs/PRICE_IMPORT.md)：逐行预览、显式接纳、原件hash及表/行绑定，保留手工核价。
- 批准后预览/下载/打印HTML报价响应，原CSV/JSON保留。按币种汇总，不折汇或虚构条款，HTML必须带当前revision并重新核验批准及原件。
- 30行合成全UI演练见[runbook](docs/DEMO_RUNBOOK.md)。恢复后新案9f166402bdf8：排除1条重复后29行；修改前USD470.00/EUR430.50，局部数量修订并重批后USD473.75/EUR430.50。不是模型或真实业务指标。

## 其他准备入口

- [约3分钟主线、备选异常与实际演练记录](docs/DEMO_RUNBOOK.md)：真实文件选择器导入两行合成材料，同件号不同RFQ→缺价→合成核价→批准/CSV→撤价失效。3分钟是讲解预算，尚无真人计时或视频。
- [20分钟本地专业试用任务卡与空表](docs/USER_TRIAL.md)：两件具体任务、记录求助/错误/时间；尚未开展，没有用户反馈。
- [要求—行为—证据—缺口](docs/RULES_AND_EVIDENCE.md)：官方核验日期、30%口径差异及未完成项。
- [能力/合成场景待审草稿](submissions/draft/README.md)：只含合成卡和审查后的说明，未投稿，不含官方素材/截图/DB/日志。
- [准确状态](docs/STATUS.md)、[数据/语法边界](docs/DATA_DICTIONARY.md)、[取舍](docs/DECISIONS.md)、[评测限制](evals/README.md)。

本轮新案7c3351bfa96a和91ee48d41de5实走完成导出后撤价，原5案未改。证据var/demo-evidence/rehearsal.json、output/playwright/demo-short-*.png、demo-review-*.png及对应CSV均本地忽略，不进入参赛草稿。CSV标识列需按文本导入Excel，以保留前导零；旧下载文件仍是历史版本，系统不能回收文件。

## 候选与专业边界

侧栏合成正文/转发修订审阅支持声明的标签语法。点击生成离线标签候选只是规则提取，unsupported不得称成功；候选须核对人/理由、归属及必要的未知原值确认，再显式接纳。人工改3为4保留原文3，不补假引用。更换正式输入会使关联旧批准失效。重复/冲突、缺价、过期或多候选价源阻止批准。价格只能来自标明的合成/有授权人工核价，不由候选生成。

这不是任意自由文本、复杂指代、自动修订继承或扫描件OCR的保证；目前没有生产身份/签名/多租户。独立裁判对重复业务键须有harness来源记录选择；未知语义不刷为source，可信人工台账另计human。

## 定向核验（按风险选择，不为文案重跑全套）

本轮新增风险：`./.venv/Scripts/python.exe -m pytest tests/test_product_intake.py -q`（恢复后5 passed）。完整UI回归：服务启动后，`./scripts/browser.ps1 run-code --filename scripts/browser-check-drafts.js`和`./scripts/browser.ps1 run-code --filename scripts/browser-check-product.js`。两者创建新合成案件；后者从文件选择器初始化，不使用API建案。重复运行前另存同名截图/下载，原上传及价源归档始终按新案隔离。


```powershell
./.venv/Scripts/python.exe -m pytest tests/test_meter_terminal.py tests/test_fair_contract.py -q
./.venv/Scripts/python.exe -m pytest tests/test_literal_binding.py -q
./.venv/Scripts/python.exe evals/compare_dev.py --fixture
node --check apps/web/app.js
# 浏览器工具；缓存/会话只在本项目
./scripts/browser.ps1 open http://127.0.0.1:5311 --config .playwright/cli.config.json
./scripts/browser.ps1 snapshot
```

历史测试与本轮实跑分开见STATUS：Meter定向37通过；共同DEV两路径各3个检查点只属fixture联通。没有真实模型成本/时延、调优冻结、留出或领先结论。

## live与预算门禁

`evals/compare_dev.py`默认或`--live`仅预检，当前退出2/0真实请求；旧基线非dry-run入口同样拒绝，不能只设置型号/端点/密钥就运行。产品与基线共享RFQ_MODEL_URL/KEY/NAME及显式允许请求口径，正式比较还缺验证过的定价/花费授权、真实调优冻结、相同宿主隔离和可信token/费用预留。夹具不生成真实冻结，不释放预留。

整任务上限与产品内部8秒/6000token子调用上限分别记录；Meter遇未知usage或预算/超时等终止后，同实例不再调用模型/工具/人答。模拟token/费率不是真实账单。当前代码宿主仍协作式审计，不宣称恶意代码完整OS沙箱。普通UI单次提取也不是正式公平比较。

未报名/付费、外联、公开部署、正式投稿或企业试用。官方原件仅本地研究，不复制到草稿、不发送第三方模型。只有真实模型、业务样本/试用及正式平台/规则等外部前提满足后，才能补相应证据；目前不寻找API，不生成替代反馈。


已增加显式局部询价修订：追加另一文件后选择目标行和更新字段，未提供字段继承原出处；清空须单独操作与理由，原整行替换语义保留。浏览器两RFQ同件号演练及定向54项测试通过，见[局部修订演练](docs/DEMO_RUNBOOK.md)与[当前状态](docs/STATUS.md)。这仍是合成DEV工程验收，真实模型/强Agent性能比较未运行。


慢请求交互已加案件/行/版本及导航归属：等待中继续输入保留新草稿并要求核对，重复保存不重复发送，旧回包不拉回案件或降低同案版本。后台任务在“任务回报”注明归属，可明确打开对应案件；价目/候选窗口后填内容也不会被成功回包自动吞掉。定向`node --test tests/interaction.test.cjs`及两新案受控浏览器记录见STATUS。这里验证响应顺序安全，不是实网延迟或模型性能。


本轮新增[当前浏览器裁定恢复](docs/DRAFT_RECOVERY.md)：必要编辑默认有界暂存，刷新后明确选稿、对照并恢复到编辑区；不自动提交或改批准，旧版本不能直接覆盖。最长7天/50行/约256KiB，可关闭并清除；损坏/配额失败明确降级页内。两案实跑报告及13项相关检查见STATUS，17旧案和4份旧报价输出未动。只缓存行裁定，不缓存原附件、价目文件、模型配置或密钥。


已打开页也遵守暂存关闭：持久化前核最新策略；偏好损坏/不可读停写，关闭保存失败时本页保持off直到本页明确重开。此项并入恢复阶段收尾，集中双页与相关模块结果见STATUS，不是多标签实时协作。
