# 数据字典与格式边界

2026-10-22。官方素材来源与 SHA-256 见 SOURCE_MANIFEST.json，原始字节只读，本地解析报告在 var/official-inspection.json，不提交原文或提取结果。

询价行：rfq 询价号、part 件号、description 描述、quantity 数量、unit 单位、condition 件状、due 截止日期、requirements 特殊要求、priority 原始优先级。标识用字符串；raw_fields 保留提取时原值；sources 保存文件名、SHA-256、HTML 表序/工作表/页/行及完整原始行。手工更正写入事件中的 before/after 和理由，原始行不覆盖。每个字段的出处为对应原始行及标题映射；尚无字符级坐标高亮。

EML：使用 MIME 声明编码，GB2312 按兼容的 GB18030 解码，优先 HTML 表，退回制表文本；递归解析支持格式附件。转发表只要保留规范表头即可读取；非表格式自由文本、复杂嵌套表尚不保证。正文片段保留在工作单中。

XLSX：只读取，不执行公式；公式单元格留空并发出警告。字符串和全零数字格式保留前导零。工作表/行号可追溯；不猜测独立附件没有给出的询价号。

PDF：pdfplumber 文本/表格 + 明确表单语法，支持官方两页 RFQ 表单（6+1 行）、续页沿用文档 RFQ 和 Respond by。Each 原样保留，Condition、List、Cost、Delivery 空栏不当作事实。扫描件报告需 OCR/人工处理；尚无 OCR，其他复杂 PDF 不保证完整。

价格依据：part、unit、condition 精确匹配；currency、amount、valid_from、valid_until、lead_time、source、kind 必填。kind 区分 synthetic/manual/authorized；不做单位/币种换算，不把未知缩写释义。没有唯一有效候选阻止批准。金额 Decimal，相乘后 ROUND_HALF_UP；JPY 取整数，其余已支持币种（USD/CNY/EUR/GBP）保留两位。不跨币种汇总。

批准：本地操作人姓名（没有企业身份认证）；批准 token 绑定行内容、裁定和有效价格记录，并绑定批准日期。输出实时检查期限、价格有效性、冲突和 token。无关价表项更新保留批准，相关变化只使关联行失效。每日重新批准是当前保守选择。CSV 标记合成来源并防公式注入；CSV 文件本身不能保证 Excel 自动保留前导零，需作为文本列导入，JSON 导出保存精确字符串。

数据库：var/rfq.sqlite3，SQLite 写事务与工作版本比较，过期写入返回 409。上传只存 var/uploads；没有跨项目共享数据库。当前本机原型无生产鉴权/多租户，不应直接公开部署。

## 第二轮证据契约

独立读取器 evals/judges/evidence.py 不调用产品parsing/domain，重新读取原件并形成(sha256,location)索引，比较文件名、原始行片段和字段值；仅有引用或存在同样数字均不足以通过。支持已声明的HTML/TSV/XLSX标题及官方PDF表单语法，超出语法保守返回未支持，不宣称任意PDF已核验。

GET /api/cases/{id}/evidence/{row_id} 返回每个字段的当前值、原文值、支持状态、原始记录和人工裁定理由。修改值不会覆盖raw_fields。批准和导出会重新核查原始文件完整性及原字段支持；合法人工更正由本机操作事件留痕，不能伪称原文值。当前没有企业身份或外部授权签名认证。

独立评测判定器对完整行一对一匹配，禁止从多个错误候选分别挑正确字段；拒绝多余/重复候选。动态任务另校验价格快照hash/记录索引、金额/单位/件状/有效期，以及批准答复ID和快照。完成覆盖率、正确澄清率与来源支持率分开报告，不用全部拒答代替完成。

金额/数量当前支持最多1万亿、12位小数，价表必填字段用字符串，日期须YYYY-MM-DD。非法更新在任何状态变更前拒绝，原批准快照保留。
