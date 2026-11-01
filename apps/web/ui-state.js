/* Display contracts and tab-local, version-bound form memory. No business decisions. */
const RfqUiState=(()=>{
 const priceCodes=new Set(['missing_price','ambiguous_price']);
 function issueCode(message){
  return message.includes('价格')||message.includes('报价源')?'missing_price':message.startsWith('澄清未解决')?'open_clarification':message.startsWith('缺少')?'missing_field':message.startsWith('原值待确认')?'unconfirmed_value':message.startsWith('重复候选')?'duplicate_row':message.startsWith('同询价/件号字段冲突')?'conflicting_row':message.startsWith('数量')?'invalid_quantity':message.startsWith('询价期限已过')?'expired_due':message.startsWith('截止日期格式')?'invalid_due':message.startsWith('特殊要求')?'requirements_review':'unknown';
 }
 function issues(row){return (row.issues||[]).map(message=>{const structured=(row.issue_codes||[]).find(i=>i.message===message);return structured||{code:issueCode(message),message}})}
 const isPrice=i=>priceCodes.has(i.code);
 function apiBase(raw,loc){
  const local=['127.0.0.1','localhost','[::1]'].includes(loc.hostname);
  const value=raw==null||raw===''?(local?'http://127.0.0.1:8311/api':'/api'):raw;
  if(typeof value!=='string')throw Error('API配置必须是地址字符串');
  const url=new URL(value,loc.href);
  const loopback=['127.0.0.1','localhost','[::1]'].includes(url.hostname);
  if(value.startsWith('//')||url.username||url.password||url.search||url.hash||!['http:','https:'].includes(url.protocol)||/\s/.test(value)||(!value.startsWith('/')&&!/^https?:\/\//.test(value))||url.pathname.includes('//')||(url.protocol==='http:'&&!loopback&&url.origin!==loc.origin)||(loc.protocol==='https:'&&url.protocol!=='https:'))throw Error('API配置无效：使用同源路径或HTTPS地址，不得包含凭据、查询或不安全降级');
  return url.href.replace(/\/$/,'');
 }
 function progressText(c){
  if(!Number.isSafeInteger(c.active))return '';
  return `有效 ${c.active} 行 · 批准 ${c.approved??0} 行 · 异常 ${c.open_issues??0} 项 · 未决澄清 ${c.open_clarifications??0} 项${c.pending_parse_review?' · 待核查解析':''}${c.pending_candidates?' · 待审候选 '+c.pending_candidates:''}`;
 }
 function nextStep(c){return c.pending_candidates?'审阅当前候选':c.pending_parse_review?'先核查解析警告':c.open_clarifications?'继续处理澄清':c.issue_rows?'核对异常与价格依据':c.active&&c.approved===c.active?'查看当前输出':c.active?'人工批准当前版本':'导入并核对询价原件'}
 const reviewLabels={received:'收到 · 尚未审阅',pending_review:'有当前候选待审',no_answer:'已审阅 · 未回答此字段',reviewed_rejected:'已审阅 · 候选被拒绝',applied:'已回填'};
 function replyLabel(r){return reviewLabels[r.review_status]||(r.applications?.length?'已回填':'收到 · 尚未审阅')}
 function questionLabel(q){
  if(q.state==='received'&&q.replies?.length&&q.replies.every(r=>r.outdated||['no_answer','reviewed_rejected'].includes(r.review_status)))return '答复已审阅 · 澄清仍未解决';
  return {awaiting_reply:'待答复',received:'收到答复 · 待核对',resolved:'已解决',stale:'目标已变化 · 待重新核对',superseded:'旧目标已明确结束'}[q.state]||q.state;
 }
 function priceNotice(after,before){return after.revision===before.revision&&after.price_version===before.priceVersion?'价表内容未改变：没有生成新版本、追加事件或使批准失效。':`已保存价表 v${after.price_version}；仅受影响行重新核价并核验批准。`}
 return {issues,isPrice,apiBase,progressText,nextStep,replyLabel,questionLabel,priceNotice};
})();

class RfqFormMemory extends Map {
 static KEY='rfqdesk.tab-forms.v1';
 constructor(storage,policy,context,now=()=>Date.now()){
  super();this.storage=storage;this.policy=policy;this.context=context;this.now=now;this.meta=new Map();this.error='';
  try{if(!this.policy()){this.clearPersisted();return}const raw=storage?.getItem(RfqFormMemory.KEY);if(!raw)return;const entries=JSON.parse(raw);if(!Array.isArray(entries)||entries.length>150)throw Error();for(const r of entries){if(!r||typeof r.k!=='string'||!/^[\w-]+\|[\w:-]+\|[\w:-]+$/.test(r.k)||!['string','boolean'].includes(typeof r.v)||String(r.v).length>16384||!Number.isSafeInteger(r.revision)||!Number.isSafeInteger(r.pv)||!Number.isSafeInteger(r.time)||r.time>this.now()+300000||this.now()-r.time>12*3600000)continue;super.set(r.k,r.v);this.meta.set(r.k,r)}}catch{this.error='本标签页表单暂存无法读取；当前填写仅留在页面内'}
 }
 set(k,v){super.set(k,v);const c=this.context();this.meta.set(k,{k,v,revision:c?.revision??0,pv:c?.price_version??0,time:this.now()});this.persist();return this}
 delete(k){this.meta.delete(k);const result=super.delete(k);this.persist();return result}
 compatible(k,c){const m=this.meta.get(k);return k.includes('|g|g:actor')||Boolean(m&&m.revision===c.revision&&m.pv===c.price_version)}
 persist(){
  if(!this.policy()){this.clearPersisted();return false}
  try{if(!this.storage||[...this.values()].some(v=>String(v).length>16384))throw Error();const rows=[...this.meta.values()].filter(r=>this.has(r.k)).sort((a,b)=>b.time-a.time).slice(0,150);const raw=JSON.stringify(rows);if(raw.length>131072)throw Error();this.storage.setItem(RfqFormMemory.KEY,raw);this.error='';return true}catch{this.error='本标签页表单暂存失败或填写超限；刷新前请手动保留填写';return false}
 }
 clearPersisted(){try{this.storage?.removeItem(RfqFormMemory.KEY)}catch{this.error='表单暂存未能清除，请清除此站点数据'}}
 stale(scope,c){return [...this].filter(([k])=>k.startsWith(scope)&&!this.compatible(k,c))}
}
if(typeof module!=='undefined')module.exports={RfqUiState,RfqFormMemory};
if(typeof window!=='undefined')Object.assign(window,{RfqUiState,RfqFormMemory});
