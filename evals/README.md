# 评测状态 · 第二轮

2026-10-23。工程判定器和协议已增强；真实模型实验、开发集调优、冻结配置、留出成绩仍未发生。用户已明确暂时没有API，继续独立工程，不等待或重复询问密钥。

## 已运行的命令与结果

- `./.venv/Scripts/python.exe -m pytest -q`：31 passed。新增内容只针对证据/报价状态和执行协议风险。
- `./.venv/Scripts/python.exe evals/run_offline.py`：原有8/8功能检查通过；属于同一合成任务的8个检查，不是8个客户。
- `./.venv/Scripts/python.exe evals/replay_dynamic.py`：同一个开发任务的3个事件检查点（初次批准、撤价待澄清、新价重新批准），产品与确定性传输各3/3通过。结果在 results/dynamic-replay.json。分别输出行覆盖、可完成行完成覆盖、正确澄清率、来源支持率；无可完成/可澄清行时相应分母为零返回null，不刷100%。
- `./.venv/Scripts/python.exe evals/baselines/strong_agent.py --dry-run`：18轮、15次工具调用、3次Python子进程、3次脚本人答，protocol_status=completed、model_status=not_run。结果 results/protocol-fixture.json。Token标记fixture_simulated，不能作为真实模型耗费或延时。

所有results本地忽略；不提交原始官方素材或模型日志。没有提升比例、获奖概率、客户采用或强Agent领先结论。

## 修复的判定器漏洞

首轮按字段分别any(candidates)，可将不同错误行拼凑成正确答案。总控提供的R1/P1反例（错误数量ready行+错误单位clarify行+不存在引用）已原样加入回归，现在拒绝。整行一对一匹配，同时检查状态/关键字段/金额/来源，并拒绝额外候选。全拒答完成覆盖为0；缺价合理澄清可以正确，但不能输出虚构总价。

独立evidence读取器不调用产品提取器/业务引擎，按原始文件hash、文件名、页/表/行及片段核验字段支持；覆盖伪hash、错行、伪片段、前导零、PDF续页。价源另按当前事件快照hash和记录索引验证，拒绝虚构金额与旧批准答复/旧快照。畸形输出按错处理。该漏洞修复属于工程正确性，不证明产品或强Agent性能提高。

## 数据家族与预留

- DEV-MIXED-01：原有HTML重复/冲突案例及其衍生，保留为同一开发家族。
- DEV-EVENT-01：另行编写的TSV邮件与报价撤回/恢复事件家族；三个检查点仍是同一个任务。
- RESERVE-1/2：跨工作表单位修订、嵌套rfc822版本优先级两种作者生成结构，材料已生成但未交给产品/解析器/模型/判定器运行。不能声称作者未知或独立客户盲测。参考答案为作者定义，正式释放前需独立复核。
- manifest记录家族、lineage和hash；官方两组及轻微变体此前已检查，一律作为本地开发证据，不包装留出。
- CLI只允许cases/tasks/的开发任务，拒绝reserved/和gold/路径。gold在独立评判阶段加载，不传入模型上下文、文件工具或代码工作目录。代码审计不是恶意代码安全边界；正式不可信代码留出实验应先建立双方相同的宿主隔离。

## 强Agent原子工具和预算协议

protocol.py 不导入domain或完整产品流程；只共享原子解析。工具为state、parse（分页/总行数）、fragment（分页）、lookup（全价表快照hash及候选索引）、calculate、code、ask、render。对手可多轮自检、编写Python函数/循环与标准库验证、主动提问并独立生成输出，不是只调用固定规则或表达式。

每次run创建全新var/agent-work/run-*，仅复制白名单合成输入；净化环境，不复制密钥/gold。代码子进程使用-I基础解释器，协作式文件/导入审计；Windows Job Object限256MB/单进程，默认3秒/次，stdout32KB、普通文件写入1MB。直接读取项目gold、网络/子进程导入、死循环/超量写入等拒绝或超时已测试。具备真实代码执行，但不是无限制宿主执行，也不声称可抵御恶意Python反射绕过。

人答只从当前事件ask返回，state只公开可问键，不泄漏答复。无答案保持未解决；默认最多4次脚本oracle请求。它们不是外部真人试用或实际人工成本。

配置当前draft-not-tuned-not-frozen：32轮、180秒、单请求30秒、24000token、60次工具、最多1次传输重试。费用仅可按操作者提供的费率估计并限额，实际账单未知；缺usage停止并标usage_unavailable；超token/费用/时间失败不算完成；失败请求用量未知单列，不能记零。结果记录task/config/tool-code hash、逐阶段输出、工具耗时、重试/人答/代码次数。真实API暂缺，定价也未配置，没有发起真实付费请求。

## 尚未执行

真实同模型的产品语义路径及调优对照、冻结后预留评测、独立业务样本和来源/关键字段F1金标准、重复3次的成对统计、消融、真实人工试用。正式比较前统一双方资料、模型、原子工具、代码宿主、预算与人答规则，并真实记录调优过程，再冻结hash。当前没有性能或业务优势结论。

## 第三轮候选回归（2026-10-23）

`pytest -q`当前48 passed；新增tests/test_semantic.py为17项候选风险回归。`evals/replay_semantic.py`生成本地semantic-validation.json/XML，记录模型not_run、代码hash、两种作者合成开发格式、未使用预留。它不是模型对照；HTTP适配的MockTransport和依赖注入同样明确未运行真实模型。

覆盖：未配置0请求；两种正文格式只产生候选；伪hash/别的文件/错位置/越界/无依据值/错字段/跨修订拼接/畸形类型/禁价格字段；空/非法数量；人工裁定必须匹配外部授权台账；明确归属、异询价目标重新确认；旧revision/旧批次/原件变化拒绝接纳；未知原值确认；超时/用量超限/未知材料远程门禁；显式拒绝与缺核对人；HTTP请求契约mock；接纳新修订后旧批准不能导出。

独立EvidenceIndex支持原件字面span及verify_claim。source表示当前值有原文支撑；human表示外部授权记录匹配且原始引用仍真实。人工值不能用假引用刷原文支持率，authorized_human_fields单独报告。更复杂自然语言中的语义关联仍由人工核对，不宣称span验证等同语义正确。

未读取/运行原预留家族及其gold，未冻结/调优真实模型，也未增加独立客户样本或领先指标。产品语义请求预算当前单次8秒/6000token/24000字符/30候选，实际调用未发生；与通用Agent任务预算不是现成的公平比较，正式同模型对照仍需统一预算与真实运行。

## literal-span归属修复：可复现开发探针

命令：`./.venv/Scripts/python.exe -m pytest tests/test_literal_binding.py -q`（6 passed）；`./.venv/Scripts/python.exe evals/replay_literal_binding.py`。全项目最新54 passed。结果本地results/literal-binding-validation.json，记录代码hash及normal=true / priority_as_quantity=false / other_request_as_quantity=false；对应核实原文字段数5/4/4，错误各1不支持。

读取器从原件独立建立字段和业务行绑定；不使用产品semantic/materials/parsing/domain，不信citation.field。重复RFQ+Part、重复件号或同值修订必须给独立expected行source_binding={file,sha256,record_id}；对标签正文record_id为该次Part行，对静态表格为原行定位。同记录正确引用true，单字段和整记录错换false；缺少唯一记录选择时unverified，不能以所有拒绝冒充修复。

新探针完全内存生成，不读取预留/gold。原静态与语义测试保持通过，既有开发动态harness各3/3保持；没有看预留答案或据此调优。expected记录契约和可信授权台账仅供harness裁判，不能进入Agent上下文或工具结果。原子材料对各系统保持一致；若业务任务未说明版本选择，不能暗藏参考要求再声称对手失败。

跨文档human裁定需外部台账的source_binding及row/field/from/to/actor/reason匹配；候选不能自己提供可信签字。原文核实、未核实语义、人工授权分别计verified_source_fields/unverified_semantic_fields/authorized_human_fields；拒绝/缺行仍看完成覆盖率。无原文声明的人工新值不补假引用。畸形引用/出处对象按未支持处理，不崩溃。

这是裁判正确性修复，不是产品、强Agent性能提升实验。真实模型仍not_run，没有新业务样本或优势结论。

## 共同DEV比较契约：仅fixture联通/readiness

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_fair_contract.py -q
./.venv/Scripts/python.exe evals/compare_dev.py --fixture
# 下列入口仅预检，退出2，0真实请求
./.venv/Scripts/python.exe evals/compare_dev.py
./.venv/Scripts/python.exe evals/compare_dev.py --live
./.venv/Scripts/python.exe evals/baselines/strong_agent.py --live
```

新增19项契约覆盖；本轮范围回归71 passed / 2 deselected，具体过滤命令见STATUS。两个旧测试涉及读取开发gold/尝试该路径，按本轮约束未运行，不算通过。新演练不读取任何gold或预留。

FAIR-DEV-01是衍生的合成联通任务，不是新客户或留出。产品和基线相同原始材料hash、as_of、价格/事件、业务规则、可问事实键及型号/端点。原文通过同一个materials分页原子解码器提供；基线仍有parse、fragment、code、计算、价源检索、ask、render，不共享完整报价引擎。judge-only source_binding/预期/台账只在两条输出返回后构造，task schema拒绝夹带；不得藏版本选择规则。

共用整任务预算：24000token、180秒、32调用、60工具、8人答、最多1次保证发送前的重试；合成费用上限1.00。输入/输出模拟费率分别1.00/2.00每百万token；这不是任何真实模型价格。产品内部语义8秒/6000token子上限另列，任务累计Meter跨事件不重置。实际比较应保留两种上限声明，不能拿内部较少调用上限当整任务同预算证据。

当前fixture产品3次调用/360模拟token/13工具/6脚本人答，基线21次调用/2520模拟token/19工具/6脚本人答；各3/3外部判定检查点通过。预设调度决定数字，**不能报告省token/省钱/更快/领先**。结果fair-dev-connectivity.json含公共task/config/代码hash、用量轨迹、工具状态/时延及独立判定，均not_run、real_requests=0、fixture_simulated，实际账单null。

缺usage/非法usage停止，未知总用量为null并列known部分；有效但超限usage保留实际数字，任务失败。失败请求可能有未知用量，不能记0或盲目重试。仅BeforeSendError表示可证明未发出，允许有限重试。响应/墙钟/请求时限及工具/人答耗尽均明确失败，保留已完成检查点。

live必须显式--live、RFQ_ENABLE_MODEL_REQUESTS=1、完整共享模型配置、有效预算/定价和花费授权、真实调优冻结。冻结须匹配model、endpoint/budget/data/runtime-code hash。测试仅在内存构造冻结形状验证拒绝分支，不写真实冻结。当前即便这些形状匹配，仍因hostile-code OS隔离与提供方token/费用可信预留未验证而blocked_prerequisite。真实HTTP无可信reserve_usage适配，不调用；现阶段不能合理宣称真实费用硬预留已完成。

正式模型调优、冻结、预留和成对性能比较全not_run。旧strong_agent.py --dry-run只保留旧协议功能回归，不替代此共同契约，也不释放任何live权限。

## Meter终止锁存小修复

复现命令：`./.venv/Scripts/python.exe -m pytest tests/test_meter_terminal.py tests/test_fair_contract.py -q`，本次37 passed。新18项覆盖总控“usage_missing后再次invoke却成功”的精确反例、终止后工具/人答/计量再入、预留违约/超限/墙钟/请求超时/重试耗尽及成功多事件未退化；未重跑无关全套或gold相关用例。

Meter首次失败保存只读terminal_reason，所有受计量动作在执行前拒绝后续调用，计数及首因保持。安全BeforeSendError只在尚未终止时可有限重试。报告保留已知usage与未知总量null，usage_trace副本不允许报告调用误清内部记录。单任务串行接口无reset/resume；不宣称抵御恶意反射或完整OS隔离。

本地meter-terminal-probe.json记录：第一次usage_missing、第二次仍usage_missing，transport/reservation均仅调用1次，unknown请求1、actual_tokens=null；普通工具和人答计数仍0。compare_dev --fixture两路径各3/3、live_ready=false。该文件与fair-dev-connectivity均为工程夹具证据，不是模型性能结果；真实模型/冻结/预留仍not_run。

## 评审演示浏览器核查（2026-10-23）

本轮为离线合成业务流程核查，没有运行强Agent比较、真实模型或专业人员试用。API明确设置`RFQ_ENABLE_MODEL_REQUESTS=0`；浏览器通过实际文件选择器分别导入`data/synthetic/tasks/lifecycle.eml`与`data/synthetic/demo.eml`。启动及逐步复现见`docs/DEMO_RUNBOOK.md`，匿名试用空卡见`docs/USER_TRIAL.md`。

新短案`7c3351bfa96a`保留同件号不同RFQ两行，显示数量出处与缺价，人工填入明确合成USD10.00后批准下载两行，金额30.00/20.00。新六行案`91ee48d41de5`经明确合成裁定排除重复及数量冲突、补齐合成价后下载四行，总额344.50。撤价后两案分别有两条批准失效，当前版本导出均返回409。下载CSV行数、合成标记、金额和409已断言；原有五案摘要/版本及输入文件hash未变。

本地记录`var/demo-evidence/rehearsal.json`、步骤脚本/snapshot及`output/playwright/`截图/CSV继续Git忽略，不复制到待审草稿。两案工具往返墙钟约306秒包含脚本准备和截图，不是真人完成时间，也不证明三分钟视频已完成。未发现演示阻断问题，无产品代码改动，未重跑无关测试；上方37/71等结果仍为既有工程验收。


## 局部询价修订DEV家族（2026-10-23）

全新手编合成原件在`data/synthetic/partial/`，不是预留/真实客户。`tests/test_partial_revision.py`含原行为复现（整行替换未提供字段置空）、独立字节/hash/record_id期望验收、显式局部继承及清空人工授权、同值跨修订错引、两RFQ同件号错目标、并发、原件篡改、非法数量原子性、原整行替换及API追加/审批/导出。未通过产品函数自证出处，也未改裁判放宽歧义规则。

命令：`./.venv/Scripts/python.exe -m pytest tests/test_partial_revision.py tests/test_semantic.py tests/test_literal_binding.py tests/test_evidence_api.py tests/test_evidence.py -q`。本次54 passed；初次复现1 passed；实现前测试9 failed/21 passed（编辑脚本因默认GBK解码失败未写入，实现仍为旧代码），改为显式UTF-8写入后定向通过。没有用失败运行充当验收。

浏览器案7fae7fc71563使用UI追加另一文件并只修R1数量，批准失效范围1/2、重批CSV50.00/40.00；脚本及独立核验在忽略目录`var/partial-evidence/`，截图/CSV在`output/playwright/partial-*`。R1原件独立检查9个source字段，human=0、inherited=8；继承是重叠属性，不能相加，不是支持率或基线实验。清空测试单独证明需要human台账。原7案保留；R2业务数据/出处保持，最后整单重批会更新其批准人。真实模型0请求，调优/冻结/留出not_run，不是模型能力结论。


## 2026-10-24：恢复服务与只读产品走查（非性能实验）

原8311/5311均无占用后启动本项目服务，模型请求禁用。浏览器只打开既有案、原件证据和价源窗口并取消，没有新建/保存/批准/导出或生成候选。`var/product-review-20261024/verification.json`记录两端HTTP200、8案body hash未变、新增0；截图继续本地忽略。问题与下一轮待验收行为见`docs/PRODUCT_REVIEW.md`。本轮未运行测试或模型/强Agent实验，不沿用此前54 passed冒称当前产品就绪，不提供用户反馈或可用性分数。


## 2026-10-24：产品里程碑与中断恢复验收

范围：真实状态/异常定位、页面内草稿版本保护、规范CSV/XLSX价目预览/原件绑定、批准revision HTML响应及30行全UI任务。材料手编生成于data/synthetic/product/，不读取gold/预留；不是模型或专业用户实测。

中断前：新两行实际复现搜索/筛选/切行/切案件丢草稿；相关44 passed为当时结果。恢复后：`./.venv/Scripts/python.exe -m pytest tests/test_product_intake.py -q`，5 passed，验证严格模板/数字标识拒绝、重复及现价冲突原子拒绝、旧预览/原件变化、HTML revision/原价目/原询价篡改/撤价拒绝、HTML转义与分币种。node --check通过。没有重跑无关全套或将历史44项累计冒称本轮测试数。

浏览器回归命令：`./scripts/browser.ps1 run-code --filename scripts/browser-check-drafts.js`（新案44a75cd56768，API只模拟并发冲突）；`./scripts/browser.ps1 run-code --filename scripts/browser-check-product.js`（新案9f166402bdf8，导入/核价/局部变更/批准下载全部UI，无初始化API建案）。30原行中含1个重复，经明确合成裁定排除后29行；两RFQ同件号仍保留，CSV缺价/过期阻止批准，XLSX补正需独立勾选整表替换。revision7与11的HTML/CSV实际下载；数量2→5后1行失效、28行保持，旧版输出禁用，重批后下载。桌面与390px核查通过，打印样式/按钮存在但未物理打印。

独立核对读取原EML、原XLSX及下载，不调用产品金额/来源函数：29行修改前USD470.00/EUR430.50，后USD473.75/EUR430.50；前导零保留；28个原价源hash/表行/字段；独立EvidenceIndex按外部期望绑定核验145个非空询价字段。source核验与4个继承字段重叠，不是来源支持率、性能或对照胜率。恢复前12案body hash保持。记录var/product-milestone/verification.json、recovery-before.json，既有证据另存prior-output；下载/截图仍忽略。

中途缓存误验、未等切案、原生modal中断已分开保留；资源版本/no-store及显式页面确认、等待界面状态后复验成功。当前0真实模型请求，调优/冻结/留出not_run，没有真实效率/采用反馈。


## 2026-10-24：异步交互回归（受控响应，不是模型实验）

新合成甲e82f90a68602、乙d7fb7369fa3a由文件选择器建立，原件data/synthetic/async/。reproduce.js实际复现三个原问题；same-case-repro.js额外复现初版修复后的同案GET版本倒退，修复后same-case-fixed.js通过。控制是Playwright route.fetch原API后延后fulfill，409场景先暂停发送再独立触发一次本地并发revision；不编造真实网络延迟或性能。

`node --test tests/interaction.test.cjs` 5 passed；node --check通过。`./scripts/browser.ps1 run-code --filename scripts/browser-check-async.js`真实主回归11组：正常、继续输入、切行/切案、重复、乱序、409、失败保留/重试、价目预览跨案及同案乱序、候选生成与迟到导入。以新两案为主，另有一个导入派生案；脚本需先有两案，重复运行前为追加revision.txt等准备全新两案并另存证据。var/.../review-check.js的3项额外候选/手填价源回包检查通过（含隔离归属用DOM关闭弹窗，不能说真人试用），同案版本边界独立复验通过。

首次主回归因gate未释放就unroute报Route is already handled，属脚本控制失败；passthrough修正后整段重新通过。未重跑旧Python5项或已验29行整段UI。var/async-interaction-20261024/verification.json核14旧案与4旧输出hash不变；甲最终quantity23正确分类为human（原文21+授权台账），乙所有未提交草稿未写DB。截图/报告不进入参赛草稿。0真实模型请求，调优/冻结/留出not_run，不提供支持率/领先或用户采用结论。


## 2026-10-24：本浏览器草稿恢复（合成工程回归）

原Map已在两新合成案d0d3d73aef32/17b3d52c8cd2实际重放：接受刷新后77和理由丢失。后续basic/pending/degraded三个本地浏览器报告覆盖明确恢复保存、同件号不同RFQ和案件隔离、旧版对照/拒绝写、放弃不复活、缺失稳定目标、成功只清已提交身份/后填跨刷新、跨案晚回包、损坏JSON和受控配额失败及关闭/清理偏好。缓存异常时仍能显式保存合成价1.00，没有提交页内13。没有模型API或真人效率/采用反馈。

`node --test tests/draft-store.test.cjs tests/interaction.test.cjs`：13 passed（新增存储8，相关归属5），语法通过。本轮不跑无关旧全套。首次上限测试11 pass/1 fail，因跨记录重复editId导致提前停淘汰，修case+row后通过；后补清理失败和零版本拒绝。浏览器控制脚本曾残留beforeunload once handlers导致重复accept诊断，未算产品故障也未隐去，改on/off生命周期并于同上下文新页干净复验反例。

证据var/draft-recovery-20261024/包含全部脚本、基础/等待/降级报告及verification.json；output/playwright/recovery-*。独立核对17旧案body hash及4旧CSV/HTML不变，原材料字节一致；新甲11/3、乙9/3是明确人工保存，数量13/旧稿8/后填10、12未提交。新增合成价来源标识清楚，无假原文支持或新批准。当前源/浏览器存储可用范围内验证，未模拟OS断电、不测多标签事务合并；强Agent真实调优/冻结/留出not_run。


## 2026-10-24：恢复阶段关闭策略集中验收

隔离双页+新合成policy.eml真实复现设置false之后旧页仍缓存8（不是把父模块探针当浏览器）。修复稳定后一次运行`node --test tests/draft-policy.test.cjs tests/draft-store.test.cjs`：13 passed，5新增策略/8受影响存储；未跑未改interaction/Python/29行主线。var/draft-policy-20261024/check.js双页实际验证关闭后输入/重试0缓存、刷新off、明确重开与恢复、损坏/定向读取失败停写、偏好写失败仅本页off锁及明确重开、显式合成核价和其他key保持。模块探针另覆盖无storage事件的旧实例、清理失败及开启写失败。没有新的实际失败。

报告与截图在var/draft-policy-20261024及output/playwright/policy-*，独立核19旧案/4旧导出hash；新案c69803b7dfcb仍数量2/3、合成价1.00且未批准。受控设置故障是工程验证，非模型或真人指标；0真实模型请求，不测多标签事务，既存恢复证据保留。


## 2026-10-24：本地澄清往返业务阶段

首次集中定向运行 tests/test_clarifications.py + test_partial_revision.py + test_product_intake.py：33 passed（6新增澄清、27相关既有局部修订/核价检查）；相关interaction模块5 passed与JS语法通过。补齐重新归属处置后仅复跑受影响的澄清7项，结果见STATUS；没有重跑旧17/19案/29行主线或模型全套。测试覆盖收到不关闭、同件号跨RFQ独立、不充分/错目标/旧版本/重复/缺绑定/原件篡改原子拒绝、采用未关闭仍阻断、显式人工裁定、过期结论及重新归属的旧目标结束/新目标未决、原价格变后批准失效。

浏览器完整案75b36f5536f9从文件选择器初始化，两问题逐项解决，CSV/HTML实际下载。合成单价12.35时61.75USD，13.00时旧批准失效并重批为65.00USD。另一案ecb3f54b26b4实走旧答复禁用、不充分人工关闭原子拒绝、明确人工EA、归属变更使结论过期及旧目标人工结束；新问题仍阻断。两个页面报告都无pageerror；HTTP422/409为预期反例，不是模型错误率。

证据var/clarification-20261024，截图output/playwright/clarification-*。独立verify.py使用外置明确文件/hash/record_id逐字段校验10个非空原文字段（原件与新答复分开），而非按同件号推断归属；下载金额按Decimal及原始数量2/3核对。20旧案body hash、4旧父审导出hash保持。首次核验脚本错用裁判返回键status，修为supported/kind及外置绑定后通过，未伪称应用失败。主浏览器第一次在已有关闭候选的confirm暂停，接受后同一段继续完成；可复用脚本有dialog生命周期处理。

本轮真实模型请求0；支持的离线冒号标签及人工裁定不是强Agent推理。调优/冻结/留出/专业试用/MOI均not_run，无领先、提升率或用户反馈结论，原共同DEV/公平协议设施保留但本轮不重测。

## 2026-10-25：平台快照公开契约准备（非平台/模型实测）

`./.venv/Scripts/python.exe -m pytest tests/test_platform_snapshot.py -q`：11 passed。只新边界：快照原值/人工决策/两RFQ/逐字段来源、关闭与未授权不建网络客户端、官方两步请求形态及响应ID传递、上传/关联失败/超时/重定向不重试/不泄密、错快照hash/ID/原件/配置拒绝、无主业务hook/health仍false。没有重跑原澄清33+5/7、旧金额/来源/29行/模型套件。

`./.venv/Scripts/python.exe -m scripts.platform_contract_fixture`独立执行通过：固定合成工作单revision2，原数量2→明确人工5、另一RFQ3不变；生成synthetic-snapshot.json，注入upload/create两次并得到人工构造的synthetic-file-001。contract-report.json同时明确real_platform_requests=0、real_model_requests=0、native_platform_versioning=not_run。此JSON为本应用文件格式，不是MOI原生revision；不计算语义质量或领先指标。

证据var/platform-readiness-20261025/{tests.log,fixture.log,synthetic-snapshot.json,contract-report.json,local-verification.json}。主库hash两次被文件锁拒绝，未确认hash保持；PowerShell最初null==null误给true，已明确修为not_verified_file_locked并保留原因，不把它当证据通过，也未据此停服务、复制或修改原库。模块和fixture不打开主DB；本轮不另加核库探针。真实平台账户/权限/网络/读回/原生版本、Genesis调用/强Agent调优冻结留出/专业试用均not_run或waiting_external_validation。
## 2026-10-25：后端对齐阶段实际回归

control_run_id=backend-alignment-20261025-1。按本轮明确要求集中完整pytest：143 passed（7新组合检查，136既有），无失败/跳过；3个tests/*.cjs共18 passed，无失败/跳过。不是重新运行强Agent质量比较或沿用历史数字。覆盖新导航/同值不同结构/已有附件、拒绝答复留结论不解决、纯预览无写/显式与旧导出守卫、价表单次/幂等版本、按行登记/摘要/code和无Git启动。

新 UI 全程实际主线新案8a9958f4f1de/r18：不充分答复禁接纳/拒绝仍未决、两RFQ独立澄清、合成13价下载65.00、改14失效409、未保存77草稿刷新/恢复仅编辑/阻批准/放弃、重批实际下载70.00。另案dffa6ec2ec43只验HTML结构精确定位，不冒充完成报价。均Playwright当前UI真实file input setInputFiles、点击/输入，非原生OS文件选择器。375px无整页溢出，pageErrors空；当前UI仍旧GET审计，未冒称纯预览接线完成。

var/backend-alignment-20261025/保存执行脚本/全部日志/browser-report/verification、14文件前后hash及CSV/HTML实际下载。独立Decimal以原合成邮件数量2/3核两版CSV行及HTML合计65/70，原件字节一致，前端集合/hash匹配父baseline。API隔离DB明确只有本轮两案，未用主var/rfq.sqlite3；本轮未测主库前后hash，不扩写为全面历史审计。首个前端hash脚本的属性集合计数误判已改为数组计数，14项均一致；没有业务测试失败或UI控制失败。未请求真实模型/平台，调优/冻结/留出/专业采用仍not_run。
## 2026-10-25至26：新解包提交切片实际验收

本轮不重复已接受的143 pytest/18 node。实际从白名单49文件ZIP新解包、创建include-system-site-packages=false的Python3.12.14虚拟环境，联网安装完整requirements锁后用包内START运行。初始列表空；代码/API、DB/上传/价源归档路径均在新副本，未复用原源码ROOT或运行数据。48条分发文件inventory及14原前端hash匹配。

从新副本真实file input经Playwright setInputFiles/点击/输入走合成case c22574bc272a：两RFQ分别缺字段、不足答复禁接纳且拒绝不解决、逐项回填另一行不受影响、明确合成价13/批准r16下载65.00、改14使旧与当前未批准输出409、重批r18下载70.00。只有GET用于断言，不API预置成功。独立从实际CSV/HTML和原数量2/3 Decimal读回，原件字节/前导零/单价/价源版本2核对一致；pageErrors空。原始实录33.12秒，带字幕3倍播放时长MP4 99.32秒（无音轨、H264、1536x864），不是真人用时/模型时延/优势指标。

初次录屏在创建页面前因工具FFmpeg1011与通用安装1013不同而失败，未产生新案；补匹配工具依赖后本轮仅一案完整录制。字幕初稿遮合计，原稿备份，仅缩小字幕重转码后已查看帧。10-26恢复时实际已存在素材/案件，未重录/重装/重建ZIP；恢复同一DB r18，昨日批准按日期正确失效（0当前批准/2 stale），不自动重批。Ctrl+C单一启动进程后8311/5311可bind，免安装再启动后案件body hash保持；控制中断工具退出1，不当作启动业务失败。浏览器工具会话关闭导致文档预览首试未执行，重开自己的浏览器后HTML图片/99.32秒元数据及实际播放解码readyState4均通过。

历史本地打包切片与自检记录保留在本地 `var/` 归档目录中，不随代码仓库分发。

## 2026-10-28 有限真实模型DEV
6次Chat，保守15696tokens，费用unknown，三类DEV与真实UI结果见../docs/MODEL_LIVE_20261027.md。此为产品接入/程序守卫开发验证，未做强Agent调优冻结或留出比较；不能计作公平效果/竞争优势。自然语句deadline遗漏和批准role验证422均保留失败。既有客观判定器未改。


2026-10-28主控单批修复：独立裁判新增明示英文请求/需求语法角色绑定（不读模型输出），source_guard逐字段原值角色+请求键核验并兼容明确局部修订/澄清；受影响63passed（含3项回归修复）。第7/8次真实自然语句正常/修订完成，8次合计22125tokens费用unknown。属于开发修复验证，不是冻结留出结果；受支持语法和人工操作见docs/MODEL_LIVE_20261027.md，历史6次报告保留，新REPORT_REVISION.json为当前。


## competitive-validation-20261028-1 恢复检查点（2026-10-29）

状态：本地字段级裁定及当前源码运行包已准备和自测；真实模型选择工具的调优与两案例成对试验未完成，本阶段 **not_ready，submission_ready=false**。原阶段7200秒累计墙钟到期；本次恢复时首请求距今约43714秒，遵照要求没有重置账本或墙钟，也没有追加真实调用。未完成项目内部可继续工作，交主控决定有限接续方式。

- 台账 `var/competitive-20261028/usage.sqlite3`：19次真实Chat、已知保守75089 tokens、unknown/inflight 0、费用unknown。首次7157 tokens高于6000预留虽HTTP200，明确作为失败保留；后续修正预算预留及完整响应归档。两种自主选工具Agent调优均调用2次但返回非合法JSON而失败，原始响应保留；没有假称真实冻结。`FROZEN.json`仅属于先前固定步骤试验，不适用于自主工具Agent，`AGENT_FROZEN.json`不存在。
- 固定步骤试验：同一中文双询价同件号文件，两臂各2次都输出两行六字段并与作者事实相符，分别调用2次；完整核价/批准/导出、人工成本、动态修订未对照。另一次修订产品臂返回不合法JSON并失败。固定两步工具序列不是由模型选择工具，不满足本阶段主要强Agent要求，不作性能或竞争优势结论；输入原文按同一材料单元提供，尚未证明两臂均拿到完整原始字节。`var/competitive-20261028/FINAL_STATUS.json`逐次raw usage及实验边界，原始响应在本地responses/，不入包。
- 一批本地修复：新增按字段手工确认来源语义的API/UI，字段与目标行、行版本、原始文件hash/精确span、快照、原值/当前值、配置的本地审阅人及审阅事件绑定。每字段须明确填写理由并确认；需本地进程事先配置审阅人和凭据，凭据不写事件。此为受控本机能力，非多用户身份认证或对抗本机恶意进程的安全边界。明确字段标签错配、错询价锚点、旧版本/快照、错误凭据和伪事件拒绝；追加材料后此类旧批准失效。原文自动支持、人工语义确认、人工更正分开显示。中文询价锚点用于拒绝跨询价拼接，非任意中文语义自动验证。
- 测试：前一版相关66项通过；加审阅凭据后受影响53项通过，JS语法通过。模拟本机审阅账号的实际UI案254feafde016，使用此前实际模型输出本地回放（本轮恢复0模型请求）；人工逐字段确认6项、人工输入合成USD9.95 ×4，批准39.80，pageErrors空，凭据未入DB。此前UI首试因折叠项隐藏、浏览器缓存及beforeunload有等待/恢复记录；没有重造模型结果或冒称真人试用。页面复用一页，完成后仅关闭本项目专用会话，1→0页；其他页面未动。
- 本地独立源码包与清单哈希校验均在隔离目录复核通过，默认离线运行且不包含密钥或受限原件。
- 产品/模型局限：字段审阅要逐项人工操作，旧模型输出回放不代表真人使用；自由中文及跨材料关联仍有保守拒绝。真实外部专业试用暂无、A尚未报名、评委获取/资格及平台接入未落实；调优冻结后两案例两臂各2次工具Agent比较与独立留出仍not_run。未commit/push/购买注册/部署/外联/投稿/定时/子代理。
- 自用测试页已关闭；阶段隔离服务8353可供主控只读复验，运行库在var/competitive-20261028/runtime。包内默认数据与此库隔离。历史model-live 8次/22125 ledger单独保留不混计。

## 2026-10-30 局部修订候选层检查点

真实模型账本60次、104105保守tokens、unknown/inflight均0，费用unknown；配额已满。局部修订试验选用旧开发材料调优得到的direct策略，`var/goal-readiness-20261029/FROZEN_SPARSE.json` 在独立新合成sparse-a/b试验前保存工具、提示、模型预算和源码hash。sparse-a首轮产品/基线两臂均完成且值正确；第二轮产品臂四次模型调用后未完成，基线与sparse-b未运行。此为不完整的候选提取对照，不是完整报价工作流或竞争力结论。空字段来源后续修复改变semantic.py，续跑须使用冻结源码或新配置重新冻结并明确区分。先前试验和失败不覆盖。

## 2026-10-30 sparse-v2 冻结与成对任务

完整候选闭包另立新配置，旧缺失依赖不伪造证明。两种策略实际调优并先冻结，然后对作者合成的两个新DEV各两臂2次，共8任务：6次完成并经作者原件事实一对一核对字段与来源行，2次基线达到4调用限制未提交。八任务26次模型调用/47068保守tokens、30工具调用、0请求人工事实，总耗时163.53秒；调优6次/11062 tokens。整个持续Goal台账92次/162235，unknown/在途0，费用unknown。裁定初稿漏读sparse-b修订行EA，原稿保留并依原字节修正；没有重试任何模型任务。详情 `var/goal-readiness-20261029/sparse-v2/JUDGMENT.json`，非独立留出或真实用户试用；两臂共用模型和工具，产品臂只是候选回放适配，不能推断完整工作流优势。

