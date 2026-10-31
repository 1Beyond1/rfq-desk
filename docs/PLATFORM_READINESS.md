# MatrixNEXT 平台准备：公开契约与实际边界

核查日期：2026-10-25（Asia/Taipei）。control_run_id=manual-20261025-1。本轮只核公开要求及准备最小适配，真实平台、原生版本能力、模型均未调用。

## 官方要求—现状—本轮结果

| 官方依据 | 核实与现状 | 本轮结果 / 尚缺条件 |
| --- | --- | --- |
| [S1 主赛页](https://matrixorigin.cn/matrixnext) | 当前30%为主题契合；允许在自有工具使用Genesis Key，并推荐平台能力。列评委可访问作品/视频/说明三链接、视频≤3分钟、命题数据合规说明；11月11日截止，具体时刻未见 | 本地工程不等于真实模型效果或评委可访问交付；账号/报名/付费/提交均未操作 |
| [S2 另一官方赛页](https://matrixorigin.cn/matrixnext2026) | 当前30%仍为产品契合，并强调Git for Data等核心能力；和S1表述差异仍存在 | 不自行选择有利口径、不认定SQLite日志或本次文件上传已满足评分；最终适用口径待官方确认 |
| [Catalog 上传文件](https://docs.matrixorigin.cn/moi/zh/5.0/reference/api/ai-studio/resource-center/catalog/upload-file.html) | 公共契约：`POST https://api.moi.matrixorigin.cn/v5/catalog/file/upload`；工作区PAT用`X-API-Key`，另传`X-Workspace-ID`；multipart字段`file`；成功`code=OK`及`data.file_id`。上传未关联卷，失败也可能留下记录 | 实现精确两步中的第一步，仅注入测试；不传官方原件，不自动重试或删除远端资源 |
| [关联文件到卷](https://docs.matrixorigin.cn/moi/zh/5.0/reference/api/ai-studio/resource-center/catalog/create-file.html) | `POST .../v5/catalog/file/create`；同上认证；JSON含整数`volume_id`、`file_ids`数组；成功`code=OK,data=null` | 实现第二步，必须使用上一步响应ID。关联未确认/超时保留已知file_id和未知结果，不伪称成功；未做真实读回 |
| [Genesis 调用指南](https://docs.matrixorigin.cn/moi/zh/5.0/developer/quickstart/genesis/http-api.html) | Genesis为模型接口，Bearer认证；应从环境复制Base URL、从模型列表确认ID | 既有`semantic.HTTPExtractionAdapter`是可替换模型入口，保持原样；不是Catalog适配，不混用认证。账户/模型权限/所选模型参数支持、真实调用尚未验证 |

主赛页和两张具体Catalog接口页本轮均直接读取成功。官方旧Product API环境页/血缘版本页的搜索摘要可见`newmoi`、Block Revision等线索，但直接读取出现Cache miss；不能据摘要拼接口。本适配只锁定已直接读到的两条v5文件契约，未覆盖工作流输出版本、记忆版本或Git-for-Data原生提交。换环境/网关须重新核实，不把旧`newmoi`前缀自动替换进当前契约。

## 最小适配能做什么

`apps/api/platform_snapshot.py`准备本应用自定`rfq-local-snapshot/v1` JSON：稳定工作单/行ID、本地revision、价格源版本号、字段及原值、逐字段出处file/hash/location、人工决策台账及事件时间/动作。JSON是上传文件的内容，**不是平台原生对象结构**；本地revision2也不是平台revision2。保留原值与人工说明，不能冒称说明由原文支持。

没有往导入/澄清/核价/批准/启动接入发送动作，没有新增UI/API端点。主业务、DB路径和`health.platform_connected=false`保持原样。既有平台快照适配不存在，因此只新增这一个独立边界；HTTP层复用既有httpx依赖，没有安装SDK或第二个平台。

默认`RFQ_ENABLE_PLATFORM_SNAPSHOT_REQUESTS=0`；配置项见`.env.example`，密钥不进前端/输出。当前只允许本轮合成原件hash；请求还绑定明确核对的完整快照hash和本地ID/revision。来源白名单不是对任意人工备注的外传授权：当前唯一命令仅构造固定合成fixture，不读主库/上传目录，不提供任意案件上传CLI。真实网络还须调用方明确授权`live_authorized=True`；本轮没有这一调用。环境开关本身不授予外传权限。

`Settings`可配置PAT/工作区/现有卷ID；服务地址只接受本次核实的v5地址。两请求不跟随重定向、不继承代理、认证不混用；失败不回显服务器正文/凭据，不自动重试。上传后关联失败不是事务回滚，可能留下平台文件记录；应由获授权操作者核实后决定处置，本工具不擅自清理。

## 已执行及重现

```powershell
Set-Location <repo-root>
./.venv/Scripts/python.exe -m pytest tests/test_platform_snapshot.py -q
./.venv/Scripts/python.exe -m scripts.platform_contract_fixture
```

结果：新边界11项通过；独立命令产生固定合成工作单snapshot和两次**MockTransport注入**请求（upload → create）。请求体/认证隔离、响应ID传递、关闭/未授权0请求、旧hash/错ID/未允许来源/错地址拒绝、上传/关联失败及超时/重定向不重试、主应用无自动hook均已验证。没有跑旧RFQ/UI/金额/来源全套。

输出在`var/platform-readiness-20261025/`：synthetic-snapshot.json、contract-report.json、tests.log、fixture.log、local-verification.json。`contract_acknowledged`只指注入契约通过；两次请求均非真实平台请求。旧主库文件hash读取被正在使用的文件锁拒绝，未确认hash一致，未为核hash停止服务或复制/重建主库；该限制单列，不能把两个null当一致。新代码/fixture不打开数据库，未调整旧服务。

## 精确停止点与继续条件

本地公开契约准备完成；实际平台状态为`waiting_external_validation`，不是平台已接入或参赛就绪。

- Catalog真调用：缺已授权配置的个人访问令牌、目标工作区ID及可写的现有卷ID，也缺明确数据/调用授权；这些是实际外部条件，不能从公开文档生成。
- 原生版本/审计能力：缺适用于本部署的完整可核实资源契约及真实资源ID/权限；本轮文件快照不能替代。关联确认后的真实读回、版本操作和比赛认可均未验证。
- Genesis/强Agent：缺已授权的有效模型配置与实际额度/模型支持验证，真实质量/成本/调优冻结留出、专业试用均not_run。

本轮到此收束，等待总控集中验收及用户提供所需条件并明确继续；不登录/注册/付费，不外发受限资料，不扩解析/UI或自动新开阶段。
