# 账号隔离与交互式体验引导

## 使用方式

管理员和普通用户使用同一个登录页，角色由服务器确定。管理员通过右上角姓名菜单进入“账号管理”，开通、停用或重新启用普通账号，也可查看账号操作记录。没有开放自助注册。初始密码由管理员私下交给本人；首次登录必须修改，之后才能访问工作单。管理员账号通过本机维护命令创建，网页不能把普通用户提升为管理员。

每个账号只访问自己创建的工作单，换浏览器登录仍能继续处理。管理员的账号管理权限不等于跨用户查看原件的权限。批准和候选裁定中的操作人由服务端绑定当前账号，新业务事件附账号身份；前端填写姓名不能冒充另一账号。模型只负责原有语义处理，不决定访问权限。

右下角“体验引导”可以展开、收起、结束，收起状态保留在本标签页。引导按当前工作单状态提示核对、核价、人工批准和输出；不自动接纳候选，不代填裁定理由或自动批准。开始合成体验创建独立两行询价，两个询价号使用同件号，不调用模型。演示价表标记为合成，真实工作单仍须使用有来源的有效价目。

## 启用与初始化

无默认管理员、无默认密码。先在目标数据库创建管理员，再开启账号模式。`.env.example`只作说明，程序不会自动加载它。服务端和维护命令须指向同一个`RFQ_DB`，且以业务进程相同的系统用户执行。

```powershell
$env:RFQ_DB='D:\指定运行目录\rfq.sqlite3'
.venv/Scripts/python.exe scripts/accounts.py create-admin --username your.admin --name 管理员姓名
# 密码只在终端隐藏提示中输入，不作为命令参数或环境变量保存。
$env:RFQ_AUTH_REQUIRED='1'
$env:RFQ_COOKIE_SECURE='0' # 仅回环HTTP开发；公开HTTPS必须为1
$env:RFQ_PUBLIC_ORIGIN='http://127.0.0.1:5311'
.venv/Scripts/python.exe distribution/serve.py
```

公开部署建议通过环境变量配置 `RFQ_AUTH_REQUIRED=1`、`RFQ_COOKIE_SECURE=1` 与正式 `RFQ_PUBLIC_ORIGIN`，并在反向代理后使用 HTTPS 访问。

忘记密码时，由具备主机维护权限的人执行以下命令；会撤销该账号全部会话，下次登录要求更换密码。停用账号不会因重置密码自动启用。

```powershell
.venv/Scripts/python.exe scripts/accounts.py reset-password --username user.name
```

## 既有数据

切换账号模式不会修改旧工作单、原件、报价、批准或原访客归属，也不会把历史工作单自动分给第一个管理员。旧数据继续保留在原库，暂不在新账号列表中显示。核实具体工作单和接收人、得到分配授权后，可在目标主机显式执行：

```powershell
.venv/Scripts/python.exe scripts/accounts.py assign-legacy --username user.name --case 完整工作单ID
```

只更新该单归属并记录账号审计，不改业务内容；已属于账号的单禁止通过该命令覆盖。此次开发没有对线上历史数据执行分配。该操作不可用来绕过用户之间的数据权限。

## 会话和存储

密码使用随机盐scrypt（N=2^17、r=8、p=1），最多同时计算两个哈希。服务器仅保存会话令牌摘要，Cookie为HttpOnly、SameSite=Strict，公开环境必须Secure。会话最多8小时，30分钟无业务请求失效；状态检查不延长空闲时间。退出、停用、密码修改或重置会撤销相应会话，改密码撤销该用户所有设备会话。

写操作要求CSRF令牌、来源校验和当前账号标识。旧标签页与当前Cookie账号不一致时拒绝请求并刷新；每分钟检查账号状态，退出/换号通过浏览器事件同步其他标签页。所有账号API与业务API响应不缓存。登录和改密尝试有限速，密码和会话令牌不写审计或浏览器暂存。

本机草稿、表单暂存和引导状态按账号隔离，不读取旧匿名暂存。退出会清除当前账号的本机裁定草稿；其他账号和无关站点设置保留。浏览器本机存储隔离用于避免产品内串号，不能替代操作系统账户隔离或抵御同源恶意脚本。尚无邮箱找回、MFA、企业SSO或组织共享工作单功能。

设计依据：[OWASP密码存储建议](https://github.com/OWASP/CheatSheetSeries/blob/master/cheatsheets/Password_Storage_Cheat_Sheet.md)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet)、[CSRF防护](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)。不是独立安全审计或生产渗透测试。

## 定向验证

```bash
python -m pytest tests/test_accounts.py tests/test_judge_demo.py -q
node --test tests/account-storage.test.cjs tests/spotlight.test.cjs
```
