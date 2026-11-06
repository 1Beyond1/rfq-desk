/* RFQ Desk shell: queue → workbench → source. The API response is the only business state; this file owns view state, request ownership and unsaved input. */
const engineName=e=>({http_model:'模型提议',offline_label_rules:'离线标签规则'}[e]||e);
const fieldNames={rfq:'询价号',part:'件号',description:'描述',quantity:'数量',unit:'单位',condition:'件状',due:'截止日期',requirements:'特殊要求',priority:'优先级'};
const monoFields=new Set(['rfq','part','quantity','unit','condition','due']);
let API='',apiConfigError='';
try{API=RfqUiState.apiBase(window.RFQ_CONFIG?.apiBase,location)}catch(e){apiConfigError=e.message}
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tail=id=>String(id||'').slice(-6);
const today=()=>new Date().toLocaleDateString('en-CA');
const narrow=()=>matchMedia('(max-width: 900px)').matches;

let current=null,caseList=[],focus=null,queueMode='todo',rowFilter='all',srcField=null,srcFile=null;
let materials={caseId:null,revision:-1,files:[],error:''};
const interaction=new RfqInteraction();
const rowDrafts=new Map(),pendingRowValues=new Map(),priceDrafts=new Map();
let browserStorage=null;try{browserStorage=window.localStorage}catch{}
const localDrafts=new RfqDraftStore(browserStorage);
let listRequest=0,materialRequest=0,recoverySelection=null,recoveryRequest=0;
const draftKey=(id,row)=>id+':'+row;

/* ---------- unsaved form input ----------
   Any workbench control with data-keep survives re-render, server refreshes and focus switches.
   Keys are per case and per focus; names starting with "g:" are per case only (e.g. the approver). */
let tabStorage=null;try{tabStorage=window.sessionStorage}catch{}
const kept=new RfqFormMemory(tabStorage,()=>localDrafts.syncPolicy(),()=>current);
const focusKey=()=>focus?focus.type+':'+(focus.id||''):'none';
const keepKey=name=>current.id+'|'+(name.startsWith('g:')?'g':focusKey())+'|'+name;
function rememberInput(e){const el=e.target.closest?.('[data-keep]');if(!el||!current)return;kept.set(keepKey(el.dataset.keep),el.type==='checkbox'?el.checked:el.value);renderLocalDraftStatus()}
function restoreKept(root){root.querySelectorAll('[data-keep]').forEach(el=>{const key=keepKey(el.dataset.keep),v=kept.get(key);if(v===undefined||!kept.compatible(key,current))return;if(el.type==='checkbox')el.checked=v;else el.value=v})}
function snapshotKept(root){const s=new Map();root.querySelectorAll('[data-keep]').forEach(el=>s.set(keepKey(el.dataset.keep),el.type==='checkbox'?el.checked:el.value));return s}
// After a successful submit only drop values that were not edited again while the request was pending.
function releaseKept(snapshot){for(const [k,v] of snapshot)if(kept.get(k)===v)kept.delete(k)}
const editedSince=snapshot=>[...snapshot].some(([k,v])=>kept.has(k)&&kept.get(k)!==v);

/* ---------- feedback ---------- */
function notice(text,tone=false){const n=$('notice');n.textContent=text;n.className='notice'+(tone===true?' error':tone==='ok'?' ok':'')}
async function request(path,options={}){
  if(apiConfigError)throw Error(apiConfigError+'；请检查config.js，本次未发送请求。');
  let r;
  try{r=await fetch(API+path,options)}catch{const e=Error('无法连接本地 API（'+API+'）。请确认服务已启动；本次操作结果未知，请刷新后核对。');e.network=true;throw e}
  if(!r.ok){let detail;try{const body=await r.json();detail=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)}catch{detail='HTTP '+r.status}const e=Error(detail);e.status=r.status;throw e}
  return r.json();
}
async function run(action){try{await action()}catch(e){notice(e.message,true)}}
let activityCount=0;
function activity(ctx,message,error=false){
  const p=document.createElement('div');p.className='act'+(error?' error':'');
  const text=document.createElement('p');text.textContent=`${ctx.title||'工作单'} · 尾码 ${tail(ctx.caseId)||'新导入'} — ${message}`;p.append(text);
  if(ctx.caseId){const b=document.createElement('button');b.type='button';b.className='btn btn-sm';b.textContent='打开对应工作单';b.onclick=()=>{toggleActivity(false);run(()=>openCase(ctx.caseId))};p.append(b)}
  $('taskActivity').prepend(p);activityCount++;$('activityCount').hidden=false;$('activityCount').textContent=activityCount;
  if(error)notice('后台操作失败（详见“回报”）：'+message,true);
}
function toggleActivity(open=$('activityPanel').hidden){$('activityPanel').hidden=!open;$('activityBtn').setAttribute('aria-expanded',String(open));if(open){activityCount=0;$('activityCount').hidden=true}}
$('activityBtn').onclick=e=>{e.stopPropagation();toggleActivity()};
$('activityClear').onclick=()=>{$('taskActivity').innerHTML='';toggleActivity(false)};
document.addEventListener('click',e=>{if(!$('activityPanel').hidden&&!e.target.closest('.activity'))toggleActivity(false)});

/* ---------- navigation & server round trips ---------- */
function applyResponse(c,ctx,message){const applied=interaction.canApply(ctx,current,c);if(applied){show(c);if(message)notice(message,'ok')}else activity({...ctx,caseId:c.id,title:c.title},message||'后台已完成，请打开对应工作单核查');refreshList();return applied}
async function openCase(id){
  const ctx=interaction.navigate(id);
  try{const c=await request('/cases/'+encodeURIComponent(id));if(interaction.canDisplayNavigation(ctx,current,c)){show(c);notice('已打开 '+c.title+'（尾码 '+tail(c.id)+'），请核对当前版本。');closeDrawer();return c}}
  catch(e){if(interaction.navigationActive(ctx)){interaction.navigate(current?.id||null);notice('无法打开工作单 '+tail(id)+'：'+e.message,true)}}
}
async function refreshList(){const requestId=++listRequest;const list=await request('/cases');if(requestId!==listRequest)return;caseList=list;renderCaseLists()}
function caseButtons(filter,cls){const q=filter.trim().toLowerCase();return caseList.filter(c=>(c.title+' '+c.id).toLowerCase().includes(q)).map(c=>`<button type="button" role="listitem" data-case="${esc(c.id)}" class="${cls}${c.id===current?.id?' current':''}"><b>${esc(c.title)}</b><span class="mono">…${esc(tail(c.id))} · 版本 ${c.revision}</span><span>${esc(RfqUiState.progressText(c))}</span><small>下一步：${esc(RfqUiState.nextStep(c))}</small></button>`).join('')||'<p class="hint">没有匹配的工作单。请导入自己的询价原件，或打开明确标记的合成演示。</p>'}
function renderCaseLists(){
  $('cases').innerHTML=caseButtons($('caseFilter').value,'case-item');
  $('landingCases').innerHTML=caseButtons($('landingFilter').value,'case-card');
  document.querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>run(()=>openCase(b.dataset.case)));
}
$('caseFilter').oninput=$('landingFilter').oninput=renderCaseLists;

function show(c){
  const switched=current?.id!==c.id;
  current=c;
  restorePriceDraft(c);
  if(switched){focus=null;srcField=null;srcFile=null;queueMode='todo';rowFilter='all'}
  $('landing').hidden=true;$('desk').hidden=false;$('mobileNav').hidden=false;$('srcToggle').hidden=false;
  const desk=$('desk');desk.dataset.caseId=c.id;desk.dataset.revision=c.revision;desk.dataset.priceVersion=c.price_version;
  $('caseEyebrow').textContent='工作单 · 尾码 '+tail(c.id);$('title').textContent=c.title;
  $('version').innerHTML=`工作版本 <b class="mono" id="revNo">${c.revision}</b> · 价表 <b class="mono">v${c.price_version}</b>`;
  if(location.hash!=='#'+c.id)history.replaceState(null,'','#'+c.id);
  if(!focusValid())focus=firstFocus();
  render();renderCaseLists();refreshMaterials(c);renderLocalDraftStatus();
}
async function change(path,values,message='',ctx=null){
  ctx=ctx||interaction.capture(current);
  if(!interaction.active(ctx,current)){activity(ctx,'页面已切换，未发送旧操作',true);return false}
  const task=interaction.begin(ctx,path),before={revision:ctx.revision,priceVersion:current.price_version};
  try{const c=await request(`/cases/${ctx.caseId}/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ctx.revision,values})});return applyResponse(c,ctx,typeof message==='function'?message(c,before):message)}
  catch(e){if(interaction.active(ctx,current))throw e;activity(ctx,'操作失败：'+e.message,true);return false}
  finally{interaction.finish(task)}
}
async function importCase(path,options,message){
  if(interaction.busy(null,'import'))throw Error('询价导入正在进行，请等待结果；未重复提交');
  const ctx=interaction.navigate(null),task=interaction.begin(ctx,'import');notice('正在导入并解析…');
  try{const c=await request(path,options);if(interaction.navigationActive(ctx)){interaction.desired=c.id;current=null;show(c);notice(message,'ok');closeDrawer();return true}activity({...ctx,caseId:c.id,title:c.title},'导入已完成，未切换当前页面');refreshList();return false}
  catch(e){if(interaction.navigationActive(ctx)){interaction.navigate(current?.id||null);throw e}activity(ctx,'导入失败：'+e.message,true);return false}
  finally{interaction.finish(task)}
}
async function refreshMaterials(c){
  if(materials.caseId===c.id&&materials.revision===c.revision)return;
  const requestId=++materialRequest;
  try{const m=await request(`/cases/${c.id}/materials`);if(requestId!==materialRequest||current?.id!==c.id||current.revision!==c.revision)return;materials={caseId:c.id,revision:c.revision,files:m.files,error:''}}
  catch(e){if(requestId!==materialRequest||current?.id!==c.id)return;materials={caseId:c.id,revision:c.revision,files:[],error:e.message}}
  renderSource();if(['materials','q'].includes(focus?.type))renderWork();
}

/* ---------- derived state (display only; the server decides) ---------- */
const priceIssue=x=>x.includes('价格')||x.includes('报价源');
const rowPriceIssue=r=>RfqUiState.issues(r).find(RfqUiState.isPrice)?.message||'';
const clarifyIssue=x=>x.startsWith('澄清未解决');
const openQuestion=q=>!['resolved','superseded'].includes(q.state);
function freshCandidates(c){return (c.candidate_batches||[]).filter(b=>b.expected_revision===c.revision).flatMap(b=>b.candidates.filter(x=>x.status==='pending').map(x=>({b,x})))}
function replyCandidate(c,{x}){return (c.clarifications||[]).some(q=>q.replies.some(r=>Object.values(x.field_sources).every(s=>s.file===r.filename&&s.sha256===r.sha256)))}
function summarize(c){
  const active=c.rows.filter(r=>!r.excluded),issues=active.filter(r=>r.issues.length),approved=active.filter(r=>r.approved);
  const content=active.filter(r=>RfqUiState.issues(r).some(x=>!RfqUiState.isPrice(x)&&x.code!=='open_clarification'));
  const structural=active.filter(r=>RfqUiState.issues(r).some(x=>!RfqUiState.isPrice(x)));
  const priced=active.filter(r=>RfqUiState.issues(r).some(RfqUiState.isPrice));
  const ready=Boolean(active.length&&active.every(r=>r.approved)),needsReview=Boolean(c.warnings.length&&!c.review_note);
  const openQs=(c.clarifications||[]).filter(q=>openQuestion(q)&&active.some(r=>r.id===q.row_id)),stale=active.filter(r=>r.stale);
  const dirty=[...rowDrafts.keys()].filter(k=>k.startsWith(c.id+':')).length;
  const cands=freshCandidates(c).filter(p=>!replyCandidate(c,p));
  return {active,issues,approved,content,structural,priced,ready,needsReview,openQs,stale,dirty,cands};
}
function rowStatus(r){
  if(r.excluded)return['已排除','off'];if(r.approved)return['已批准','ok'];if(r.stale)return['需重新批准','warn'];
  if(r.duplicate)return['重复待裁定','bad'];if(r.conflict)return['冲突待裁定','bad'];
  if(r.issues.length)return[r.issues[0],RfqUiState.issues(r).every(RfqUiState.isPrice)?'price':'bad'];return['可批准','ready'];
}
const clarificationStates={awaiting_reply:'待答复',received:'收到答复 · 待核对',resolved:'已解决',stale:'目标已变化 · 待重新核对',superseded:'旧目标已明确结束'};
const clarificationTone={awaiting_reply:'bad',received:'warn',resolved:'ok',stale:'bad',superseded:'off'};
function buildQueue(c){
  const s=summarize(c),label=r=>`${r.rfq||'缺询价号'} / ${r.part||'缺件号'}`;
  const groups=[];
  if(s.cands.length)groups.push({key:'cand',title:'修订候选待审',done:false,items:s.cands.map(({b,x})=>({type:'cand',id:b.id+':'+x.id,title:`${x.fields.rfq||'缺询价号'} / ${x.fields.part||'缺件号'}`,sub:`${engineName(b.engine)} · 数量 ${x.fields.quantity||'缺'}`,tone:'price'}))});
  if(c.warnings.length)groups.push({key:'warn',title:'解析警告',done:!s.needsReview,items:s.needsReview?[{type:'warnings',id:'w',title:`${c.warnings.length} 项解析警告`,sub:'对照原件核查完整性后记录结论',tone:'bad'}]:[]});
  groups.push({key:'content',title:'内容核对',done:!s.content.length,items:s.content.map(r=>({type:'row',id:r.id,title:label(r),sub:RfqUiState.issues(r).filter(x=>!RfqUiState.isPrice(x)&&x.code!=='open_clarification').map(x=>x.message).join(' · '),tone:'bad',mono:true}))});
  groups.push({key:'clarify',title:'澄清',done:(c.clarifications||[]).length>0&&!s.openQs.length,items:s.openQs.map(q=>({type:'q',id:q.id,title:`${q.rfq||'缺询价号'} / ${q.part||'缺件号'} · ${fieldNames[q.field]||'重复归属'}`,sub:RfqUiState.questionLabel(q),tone:clarificationTone[q.state]||'bad'}))});
  groups.push({key:'price',title:'核价',done:!s.priced.length,items:s.priced.map(r=>({type:'price',id:r.id,title:label(r),sub:(rowPriceIssue(r)||'')+(RfqUiState.issues(r).some(x=>!RfqUiState.isPrice(x))?' · 先完成内容核对':''),tone:'price',mono:true}))});
  const blocked=s.issues.length||s.needsReview;
  groups.push({key:'approve',title:'批准',done:s.ready,items:s.active.length&&!s.ready?[{type:'approve',id:'a',title:s.stale.length?`${s.stale.length} 行旧批准已失效`:'批准当前版本',sub:blocked?`仍有 ${s.issues.length} 行阻断${s.needsReview?' · 警告未核查':''}`:`工作版本 ${c.revision} · 价表 v${c.price_version}`,tone:blocked?'off':s.stale.length?'warn':'ready'}]:[]});
  groups.push({key:'output',title:'输出',done:false,items:[{type:'output',id:'o',title:s.ready?'输出报价响应':'报价响应（未就绪）',sub:s.ready?`${s.approved.length} 行已批准 · 预览 / HTML / CSV`:'全部批准后才可正式输出',tone:s.ready?'ok':'off'}]});
  return {groups,s};
}
const queueItems=()=>buildQueue(current).groups.flatMap(g=>g.items);
function firstFocus(){const items=queueItems(),live=items.find(i=>i.tone!=='off');return live?{type:live.type,id:live.id}:current.rows.length?{type:'row',id:current.rows[0].id}:{type:'materials',id:''}}
function focusValid(){
  if(!focus||!current)return false;const {type,id}=focus;
  if(type==='row'||type==='price')return current.rows.some(r=>r.id===id);
  if(type==='q')return (current.clarifications||[]).some(q=>q.id===id);
  if(type==='cand'){const [bid,cid]=id.split(':');return (current.candidate_batches||[]).some(b=>b.id===bid&&b.candidates.some(x=>x.id===cid))}
  return true;
}
function setFocus(type,id='',opts={}){
  focus={type,id};if(!opts.keepField)srcField=null;srcFile=null;
  renderQueue();renderWork();renderSource();
  if(narrow())setView('work');
  if(!opts.noScroll)$('work').scrollTo({top:0});
}
function nextFocus(){const items=queueItems().filter(i=>i.tone!=='off'),i=items.findIndex(x=>x.type===focus?.type&&x.id===focus?.id);const n=items[i+1]||items.find(x=>!(x.type===focus?.type&&x.id===focus?.id));return n||null}

/* ---------- render ---------- */
function render(){if(!current)return;renderGates();renderQueue();renderWork();renderSource()}
const gateDefs=[['content','内容'],['clarify','澄清'],['price','核价'],['approve','批准'],['output','输出']];
function renderGates(){
  const {groups,s}=buildQueue(current),by=Object.fromEntries(groups.map(g=>[g.key,g]));
  const count={content:s.content.length+(s.needsReview?1:0),clarify:s.openQs.length,price:s.priced.length,approve:s.ready?0:s.active.length-s.approved.length,output:0};
  $('gates').innerHTML=gateDefs.map(([k,l])=>{const g=by[k],done=k==='output'?s.ready:k==='content'?!count.content:g.done;return `<li><button type="button" data-gate="${k}" class="gate ${done?'done':count[k]?'open':'idle'}"><span>${l}</span><b class="mono">${done?'✓':count[k]||'·'}</b></button></li>`}).join('');
  document.querySelectorAll('[data-gate]').forEach(b=>b.onclick=()=>{queueMode='todo';const g=groups.find(g=>g.key===b.dataset.gate||(b.dataset.gate==='content'&&g.key==='warn'&&g.items.length));const item=g?.items[0];if(item)setFocus(item.type,item.id);else{renderQueue();if(narrow())setView('queue')}document.querySelector(`[data-group="${b.dataset.gate}"]`)?.scrollIntoView({block:'nearest'})});
  $('mqCount').textContent=s.issues.length+s.openQs.length?` ${s.issues.length+s.openQs.length}`:'';
}
const nextVerb={warnings:'核查解析警告',row:'核对询价行',q:'处理澄清',cand:'审阅修订候选',price:'补价格依据',approve:'批准当前版本',output:'输出报价响应'};
function renderNextCard(){
  const {groups,s}=buildQueue(current),live=groups.flatMap(g=>g.items).filter(i=>i.tone!=='off'),n=live[0];
  const here=n&&focus?.type===n.type&&focus?.id===n.id,blocked=s.issues.length+(s.needsReview?1:0);
  $('nextCard').className='next-card'+(s.ready?' done':'');
  $('nextCard').innerHTML=(n?`<span class="eyebrow">下一步</span><b>${esc(nextVerb[n.type]||'处理')}</b><span class="next-what ${n.mono?'mono':''}">${esc(n.title)}</span><small>${esc(n.sub)}</small>${here?'<span class="next-here">正在处理 ↓</span>':`<button type="button" class="btn btn-primary btn-sm" id="nextGo">去处理 →</button>`}${blocked?`<small class="next-block">本单有 ${s.issues.length} 行异常${s.needsReview?'、解析待核查':''}，通过核验后才能批准</small>`:''}`:'<span class="eyebrow">下一步</span><b>没有待处理事项</b>')+`<small class="case-progress">${esc(RfqUiState.progressText(current.progress||{}))}</small>`;
  if($('nextGo'))$('nextGo').onclick=()=>setFocus(n.type,n.id);
}
function renderQueue(){
  renderNextCard();
  document.querySelectorAll('[data-queue]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.queue===queueMode)));
  document.querySelectorAll('[data-focus]').forEach(b=>b.classList.toggle('current',focus?.type===b.dataset.focus));
  if(queueMode==='rows')return renderRowList();
  const {groups}=buildQueue(current),isFocus=i=>focus&&focus.type===i.type&&focus.id===i.id;
  const expiredIds=current.rows.filter(r=>!r.excluded&&r.issue_codes.some(i=>i.code==='expired_due')).map(r=>r.id);
  const seen=new Set(),duplicateIds=[];
  for(const r of current.rows.filter(r=>!r.excluded)){
    const key=JSON.stringify(Object.keys(fieldNames).map(f=>r[f]));
    if(seen.has(key))duplicateIds.push(r.id);else seen.add(key);
  }
  const batchTools=(expiredIds.length?`<button type="button" class="btn btn-sm" id="batchDue">统一修改已过期行的截止日期</button>`:'')+(duplicateIds.length?`<button type="button" class="btn btn-sm" id="batchDuplicates">每组完全重复只保留首行</button>`:'');
  $('queue').innerHTML=(batchTools?`<div class="row-tools">${batchTools}</div>`:'')+groups.map(g=>`<section class="q-group${g.done?' done':''}" data-group="${g.key}"><h3><span>${g.title}</span><small>${g.done?'✓ 已通过':g.items.length}</small></h3>${g.items.map(i=>`<button type="button" class="q-item tone-${i.tone}${isFocus(i)?' current':''}" data-qtype="${i.type}" data-qid="${esc(i.id)}"><b class="${i.mono?'mono':''}">${esc(i.title)}</b><small>${esc(i.sub)}</small></button>`).join('')}</section>`).join('');
  if(expiredIds.length)$('batchDue').onclick=()=>run(async()=>{
    const ids=expiredIds;
    const due=prompt(`将 ${ids.length} 行截止日期改为（YYYY-MM-DD）`);
    if(due===null)return;
    const reason=prompt('填写统一裁定理由');
    if(reason===null)return;
    await request(`/cases/${current.id}/rows`,{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({revision:current.revision,values:{row_ids:ids,due,reason}})
    });
    await openCase(current.id);
  });
  if(duplicateIds.length)$('batchDuplicates').onclick=()=>run(async()=>{
    const ids=duplicateIds;
    const reason=prompt(`将排除 ${ids.length} 行重复项，请填写统一裁定理由`);
    if(reason===null)return;
    await request(`/cases/${current.id}/rows`,{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({revision:current.revision,values:{row_ids:ids,excluded:true,reason}})
    });
    await openCase(current.id);
  });
  document.querySelectorAll('[data-qtype]').forEach(b=>b.onclick=()=>setFocus(b.dataset.qtype,b.dataset.qid));
}
document.querySelectorAll('[data-queue]').forEach(b=>b.onclick=()=>{queueMode=b.dataset.queue;renderQueue()});
document.querySelectorAll('[data-focus]').forEach(b=>b.onclick=()=>setFocus(b.dataset.focus));
const missing=(v,label)=>v?esc(v):`<i class="missing">缺${label}</i>`;
function renderRowList(){
  const c=current,filters={all:'全部',issues:'待处理',approved:'已批准',excluded:'已排除'};
  const q=($('rowSearch')?.value||'').toLowerCase();
  const rows=c.rows.filter(r=>(r.part+' '+r.rfq).toLowerCase().includes(q)&&({all:true,issues:r.issues.length&&!r.excluded,approved:r.approved,excluded:r.excluded}[rowFilter]));
  const hadSearch=$('rowSearch')===document.activeElement;
  $('queue').innerHTML=`<div class="row-tools"><input id="rowSearch" class="search" type="search" placeholder="搜索件号或询价号" value="${esc(q)}"><div class="chips">${Object.entries(filters).map(([k,l])=>`<button type="button" data-rowfilter="${k}" class="${k===rowFilter?'on':''}">${l}</button>`).join('')}</div></div>`+
    (rows.map(r=>{const [label,tone]=rowStatus(r),dirty=rowDrafts.has(draftKey(c.id,r.id)),on=['row','price'].includes(focus?.type)&&focus.id===r.id;return `<button type="button" class="r-item tone-${tone}${on?' current':''}" data-row="${r.id}"><span class="r-key"><small class="mono">${missing(r.rfq,'询价号')}</small><b class="mono">${missing(r.part,'件号')}</b></span><span class="r-qty mono">${missing(r.quantity,'数量')} ${missing(r.unit,'单位')} · ${missing(r.condition,'件状')}</span><span class="r-price mono">${r.price?esc(r.price.currency+' '+r.price.amount)+' → '+esc(r.total):'待报价'}</span><span class="chip tone-${tone}">${esc(label)}</span>${dirty?'<span class="dot-warn" title="有未保存草稿">●</span>':''}</button>`}).join('')||`<p class="hint pad">${c.rows.length?'没有符合筛选的询价行。':'未提取到询价行，请查看原件与解析警告。'}</p>`);
  const s=$('rowSearch');s.oninput=()=>renderRowList();if(hadSearch){s.focus();s.setSelectionRange(s.value.length,s.value.length)}
  document.querySelectorAll('[data-rowfilter]').forEach(b=>b.onclick=()=>{rowFilter=b.dataset.rowfilter;renderRowList()});
  document.querySelectorAll('[data-row]').forEach(b=>b.onclick=()=>setFocus('row',b.dataset.row));
}

/* ---------- source pane ---------- */
function unitNumber(loc){return (String(loc).match(/(\d+)\s*$/)||[])[1]}
function matchUnit(file,src){
  const units=file.units;let i=units.findIndex(u=>u.location===src.location);if(i>=0)return{i,how:'exact'};
  if(Array.isArray(src.raw)){const t=src.raw.join('\t').replace(/\s+$/,'');i=units.findIndex(u=>u.text.replace(/\s+$/,'')===t);if(i>=0)return{i,how:'content'}}
  const n=unitNumber(src.location);if(n){i=units.findIndex(u=>unitNumber(u.location)===n);if(i>=0)return{i,how:'number'}}
  return null;
}
function focusSources(){
  if(!current||!focus)return[];const out=[];
  const add=(src,strong,label)=>{if(src?.file)out.push({...src,strong,label})};
  if(focus.type==='row'||focus.type==='price'){
    const r=current.rows.find(r=>r.id===focus.id);if(!r)return out;
    for(const f of Object.keys(fieldNames))for(const s of r.field_provenance?.[f]?.sources||[])add(s,f===srcField,fieldNames[f]);
    if(!out.length)for(const s of r.sources)add(s,false,'行来源');
  }else if(focus.type==='q'){
    const q=current.clarifications.find(q=>q.id===focus.id);if(!q)return out;
    for(const s of q.sources)add(s,true,'问题依据');
    for(const reply of q.replies)out.push({file:reply.filename,whole:true,label:'答复原件'});
  }else if(focus.type==='cand'){
    const [bid,cid]=focus.id.split(':'),x=current.candidate_batches?.find(b=>b.id===bid)?.candidates.find(x=>x.id===cid);
    for(const [f,s] of Object.entries(x?.field_sources||{}))add(s,f===srcField,fieldNames[f]||f);
  }
  return out;
}
function renderSource(){
  if(!current)return;const marks=focusSources(),files=materials.caseId===current.id?materials.files:[];
  if(materials.caseId!==current.id){$('srcBody').innerHTML='<p class="hint pad">读取原件…</p>';$('srcFiles').innerHTML='';return}
  if(materials.error){$('srcBody').innerHTML=`<p class="msg error pad">原件读取失败：${esc(materials.error)}</p>`;return}
  if(!files.some(f=>f.file===srcFile)){const strong=marks.find(m=>m.strong),pick=strong||marks[0];const main=current.rows[0]?.sources?.[0]?.file;srcFile=(pick&&files.some(f=>f.file===pick.file))?pick.file:files.some(f=>f.file===main)?main:files[0]?.file||null}
  $('srcFiles').innerHTML=files.map(f=>{const n=marks.filter(m=>m.file===f.file).length;return `<button type="button" role="tab" data-srcfile="${esc(f.file)}" aria-selected="${f.file===srcFile}" class="${n?'linked':''}">${esc(f.file)}${n?`<i>${n}</i>`:''}</button>`}).join('');
  document.querySelectorAll('[data-srcfile]').forEach(b=>b.onclick=()=>{srcFile=b.dataset.srcfile;renderSource()});
  const file=files.find(f=>f.file===srcFile);
  $('srcTitle').textContent=file?file.file:'没有原件';
  if(!file){$('srcBody').innerHTML='<p class="hint pad">此工作单没有可显示的原件。</p>';return}
  const hits=new Map();let approx=false,whole=false;
  for(const m of marks.filter(m=>m.file===file.file)){
    if(m.whole){whole=true;continue}
    const hit=matchUnit(file,m);if(!hit)continue;if(hit.how==='number')approx=true;
    const h=hits.get(hit.i)||{strong:false,labels:new Set(),quotes:new Set(),how:hit.how};h.strong||=m.strong;h.labels.add(m.label);if(m.quote)h.quotes.add(m.quote);hits.set(hit.i,h);
  }
  const lineHtml=(u,i)=>{const h=hits.get(i);let text=esc(u.text);if(h)for(const q of h.quotes){const e=esc(q);if(e)text=text.replace(e,`<mark>${e}</mark>`)}return `<div class="src-line${h?' hit':''}${h?.strong?' strong':''}${whole?' whole':''}" data-line="${i}"><span class="loc mono">${esc(u.location)}</span><span class="txt">${text||'<i class="hint">（空行）</i>'}</span>${h?`<span class="tag">${esc([...h.labels].join(' · '))}${h.how==='number'?' · 按行号对应':''}</span>`:''}</div>`};
  $('srcBody').innerHTML=`<p class="src-meta"><span class="mono">SHA-256 ${esc(file.sha256.slice(0,16))}…</span>${approx?' · 部分高亮按行号对应，请核对原文':''}${whole?' · 本文件是此问题的答复原件':''}</p>`+file.units.slice(0,800).map(lineHtml).join('')+(file.units.length>800?'<p class="hint pad">仅显示前 800 段。</p>':'');
  const target=$('srcBody').querySelector('.src-line.strong')||$('srcBody').querySelector('.src-line.hit');
  if(target)target.scrollIntoView({block:'center'});
}
function showSourceField(f){srcField=f;srcFile=null;renderSource();document.querySelectorAll('[data-srcfield]').forEach(b=>b.classList.toggle('on',b.dataset.srcfield===f));if(narrow())setView('source');else if(innerWidth<=1280)openSource()}

/* ---------- layout chrome ---------- */
function openDrawer(){$('drawer').hidden=false;$('scrim').hidden=false;$('caseBtn').setAttribute('aria-expanded','true');$('caseFilter').focus()}
function closeDrawer(){$('drawer').hidden=true;$('scrim').hidden=true;$('caseBtn').setAttribute('aria-expanded','false')}
$('caseBtn').onclick=openDrawer;$('drawerClose').onclick=closeDrawer;$('scrim').onclick=()=>{closeDrawer();closeSource()};
function setView(v){document.body.dataset.view=v;document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.setAttribute('aria-current',String(b.dataset.view===v)));if(v==='source')renderSource();scrollTo({top:0})}
document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
function openSource(){document.body.classList.add('src-open')}
function closeSource(){document.body.classList.remove('src-open')}
$('srcToggle').onclick=()=>document.body.classList.contains('src-open')?closeSource():openSource();
$('srcClose').onclick=()=>{if(narrow())setView('work');else closeSource()};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(!$('drawer').hidden)closeDrawer();closeSource()}});
$('work').addEventListener('input',rememberInput);$('work').addEventListener('change',rememberInput);

/* ---------- row drafts (browser-local recovery) ---------- */
function newEditId(){return globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)}
function rowEditorValues(r){return Object.fromEntries([...Object.keys(fieldNames).map(f=>[f,r[f]||'']),['reason',r.resolution||'']])}
function persistRowDraft(caseId,rowId,d){const key=draftKey(caseId,rowId),edits={},base={},pending=pendingRowValues.get(key)?.values;for(const f of RfqDraftStore.FIELDS){const value=d.values[f]??d.baseValues[f]??'',original=d.baseValues[f]??'';if(value!==original||(pending&&Object.hasOwn(pending,f)&&value!==pending[f])){edits[f]=value;base[f]=original}}if(!Object.keys(edits).length){if(d.persistedEditId)localDrafts.removeIf(caseId,rowId,d.persistedEditId);rowDrafts.delete(key);return}const record={schema:1,caseId,rowId,revision:d.revision,rowRevision:d.rowRevision,priceVersion:d.priceVersion,rfq:d.rfq,part:d.part,editId:d.editId,updatedAt:Date.now(),edits,base};if(localDrafts.put(record,d.persistedEditId))d.persistedEditId=d.editId}
function renderLocalDraftStatus(){
  localDrafts.syncPolicy();const rows=localDrafts.list();$('localDraftEnabled').checked=localDrafts.enabled;
  const unbacked=[...rowDrafts].filter(([key,d])=>{const split=key.indexOf(':');return localDrafts.get(key.slice(0,split),key.slice(split+1))?.editId!==d.editId}).length;
  $('localDraftStatus').textContent=`${localDrafts.enabled?'已开启':'未开启'} · 可恢复 ${rows.length} 份${unbacked?' · '+unbacked+' 份当前修改仅在本页':''}${localDrafts.invalid?' · '+localDrafts.invalid+' 份损坏或不兼容，未自动使用':''}${localDrafts.evicted?' · 已按上限清理最早 '+localDrafts.evicted+' 份':''}${[...new Set([localDrafts.error,localDrafts.policyMessage,kept.error].filter(Boolean))].map(m=>' · '+m).join('')}`;
}
function renderRecoveryList(){const rows=localDrafts.list();$('localDraftList').innerHTML=rows.length?rows.map((r,i)=>`<button type="button" data-recovery-index="${i}" class="${recoverySelection?.editId===r.editId?'current':''}"><b class="mono">${esc(r.rfq)} / ${esc(r.part)}</b><small>尾码 ${esc(tail(r.caseId))} · 基础版本 ${r.revision} · ${esc(new Date(r.updatedAt).toLocaleString())}</small></button>`).join(''):'<p class="hint">没有可恢复草稿。损坏或不兼容记录不会自动使用，可明确清除。</p>';document.querySelectorAll('[data-recovery-index]').forEach(b=>b.onclick=()=>inspectLocalDraft(rows[Number(b.dataset.recoveryIndex)]));renderLocalDraftStatus()}
function eligibleRecovery(record,c){const r=c?.rows.find(r=>r.id===record.rowId);return Boolean(r&&!r.excluded&&r.rfq===record.rfq&&r.part===record.part)}
async function inspectLocalDraft(record){
  const requestId=++recoveryRequest;recoverySelection=record;renderRecoveryList();$('restoreLocalDraft').disabled=true;$('deleteLocalDraft').disabled=false;$('localDraftError').textContent='';$('localDraftCompare').innerHTML='<p class="hint">读取对应工作单当前版本以对照；不会提交草稿。</p>';
  let c=null,error='';try{c=await request('/cases/'+encodeURIComponent(record.caseId))}catch(e){error=e.message}
  if(requestId!==recoveryRequest||recoverySelection?.editId!==record.editId)return;
  const row=c?.rows.find(r=>r.id===record.rowId),eligible=eligibleRecovery(record,c);
  $('localDraftCompare').innerHTML=`<h3 class="mono">${esc(record.rfq)} / ${esc(record.part)}</h3><p class="hint">基础工作版本 ${record.revision} / 行版本 ${record.rowRevision}</p><p class="note ${eligible?'':'bad'}">${!eligible?'目标不存在、已排除或标识变化：只能查看/清除，不恢复到另一行。':c.revision!==record.revision||row.revision!==record.rowRevision||c.price_version!==record.priceVersion?'服务器相关版本已变化。可恢复为旧版草稿供对照，不能直接保存或覆盖。':'目标与基础版本一致。恢复仍不代表已保存或已批准。'}</p>${error?'<p class="msg error">'+esc(error)+'</p>':''}<div class="table-wrap"><table class="grid"><thead><tr><th>字段</th><th>编辑时对照值</th><th>本地未保存值</th><th>服务器当前值</th></tr></thead><tbody>${Object.entries(record.edits).map(([f,v])=>`<tr><td>${esc(fieldNames[f]||'裁定理由')}</td><td>${esc(record.base[f])}</td><td><b>${esc(v)}</b></td><td>${esc(row?(f==='reason'?row.resolution:row[f]):'目标不可核对')}</td></tr>`).join('')}</tbody></table></div>`;
  $('restoreLocalDraft').disabled=!eligible;
}
$('openLocalDrafts').onclick=()=>{recoverySelection=null;recoveryRequest++;$('localDraftCompare').innerHTML='<p class="hint">选择一份草稿进行对照。</p>';$('localDraftError').textContent='';$('restoreLocalDraft').disabled=true;$('deleteLocalDraft').disabled=true;renderRecoveryList();$('localDraftDialog').showModal()};
$('closeLocalDrafts').onclick=$('closeLocalDraftsX').onclick=()=>{recoveryRequest++;$('localDraftDialog').close()};
$('restoreLocalDraft').onclick=()=>run(async()=>{
  const record=recoverySelection;if(!record)return;const cached=localDrafts.get(record.caseId,record.rowId);
  if(cached?.editId!==record.editId){$('localDraftError').textContent='本地记录已变化，请重新选择';renderRecoveryList();return}
  const key=draftKey(record.caseId,record.rowId),existing=rowDrafts.get(key);
  if(existing&&existing.editId!==record.editId){$('localDraftError').textContent='此行已有另一份当前页编辑。请先明确保存/放弃当前页草稿，再恢复这份记录。';return}
  const c=current?.id===record.caseId?current:await openCase(record.caseId);
  if(!c||recoverySelection?.editId!==record.editId||!$('localDraftDialog').open)return;
  if(localDrafts.get(record.caseId,record.rowId)?.editId!==record.editId){$('localDraftError').textContent='本地记录已变化，请重新选择';return}
  if(!eligibleRecovery(record,c)){$('localDraftError').textContent='目标已变化，未恢复到编辑区';return}
  const row=c.rows.find(r=>r.id===record.rowId);
  rowDrafts.set(key,{revision:record.revision,rowRevision:record.rowRevision,priceVersion:record.priceVersion,rfq:record.rfq,part:record.part,baseValues:{...rowEditorValues(row),...record.base},values:{...record.edits},editId:record.editId,persistedEditId:record.editId});
  $('localDraftDialog').close();closeDrawer();setFocus('row',record.rowId);renderLocalDraftStatus();notice('本地草稿已放入对应编辑区，尚未保存；请核对版本与差异后明确保存。');
});
$('deleteLocalDraft').onclick=()=>{const r=recoverySelection;if(!r)return;if(localDrafts.removeIf(r.caseId,r.rowId,r.editId)){const key=draftKey(r.caseId,r.rowId);if(rowDrafts.get(key)?.editId===r.editId)rowDrafts.delete(key);if(current?.id===r.caseId)render();recoverySelection=null;$('localDraftCompare').innerHTML='<p class="hint">此份暂存已清除，服务器数据未改变。</p>';$('restoreLocalDraft').disabled=true;$('deleteLocalDraft').disabled=true}else $('localDraftError').textContent='记录已变化或无法清除，请重新核对';renderRecoveryList()};
$('clearLocalDrafts').onclick=()=>{if(!confirm('清除本浏览器全部暂存草稿？当前页编辑仍保留。'))return;const ok=localDrafts.clear();kept.clearPersisted();renderLocalDraftStatus();notice(ok?'本浏览器暂存已清除；当前页编辑仍保留，继续输入会再次暂存；关闭开关可停止并清除。':'未能确认清除，请查看暂存提示。',!ok)};
$('localDraftEnabled').onchange=()=>{localDrafts.setEnabled($('localDraftEnabled').checked);if(!localDrafts.enabled)kept.clearPersisted();renderLocalDraftStatus()};
$('retryLocalDrafts').onclick=()=>{for(const [key,d] of rowDrafts){const split=key.indexOf(':');persistRowDraft(key.slice(0,split),key.slice(split+1),d)}renderLocalDraftStatus()};
window.addEventListener('storage',e=>{if(e.key===null||e.key?.startsWith(RfqDraftStore.PREFIX)||e.key===RfqDraftStore.SETTINGS){localDrafts.syncPolicy();if(!localDrafts.enabled)kept.clearPersisted();renderLocalDraftStatus();notice(e.key===RfqDraftStore.SETTINGS||e.key===null?(localDrafts.enabled?'本浏览器暂存已明确开启；当前编辑未自动提交，可重试暂存。':localDrafts.policyMessage):'本浏览器其他页面的暂存记录有变化；当前编辑未自动替换，请核对。')}});
window.addEventListener('beforeunload',e=>{if(rowDrafts.size||priceDrafts.size||kept.size){e.preventDefault();e.returnValue='有未保存修改'}});

/* ---------- shared helpers for outputs ---------- */
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function fetchExport(ctx,format,operation='preview'){
  if(apiConfigError)throw Error(apiConfigError);
  const formal=operation==='export';
  const path=formal?`/cases/${ctx.caseId}/exports`:`/cases/${ctx.caseId}/quote-preview?format=${format}&revision=${ctx.revision}`;
  const options=formal?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ctx.revision,values:{format}})}:{};
  let r;try{r=await fetch(API+path,options)}catch{throw Error(formal?'无法确认正式输出是否完成；请刷新并查看实录后决定是否重试。':'预览连接失败，未发出正式导出；请检查API服务后重试。')}
  if(!r.ok){let detail='HTTP '+r.status;try{detail=(await r.json()).detail}catch{}throw Error(detail)}
  return r;
}

/* ---------- intake & boot ---------- */
async function uploadCase(input){const f=input.files[0];if(!f)return;const data=new FormData();data.append('file',f);try{await importCase('/import',{method:'POST',body:data},`已导入 ${f.name}；左侧列出挡住报价的事项，右侧对照原件。`)}finally{input.value=''}}
$('upload').onchange=()=>run(()=>uploadCase($('upload')));$('uploadLanding').onchange=()=>run(()=>uploadCase($('uploadLanding')));
const demo=()=>importCase('/demo',{method:'POST'},'已导入合成演示（重复 / 冲突 / 缺价）。');
$('demo').onclick=$('start').onclick=()=>run(demo);
$('lifecycle').onclick=()=>run(()=>importCase('/lifecycle-demo',{method:'POST'},'合成变更演练：从两条独立询价开始，可报价、撤回价源、澄清后重新批准。'));
$('mailDemo').onclick=()=>run(()=>importCase('/semantic-demo/mail-en',{method:'POST'},'合成邮件已导入：规则提取不到询价行，可让模型提取。'));
$('mailRevision').onclick=()=>run(()=>importCase('/semantic-demo/mail-revision',{method:'POST'},'合成邮件已导入，可让模型提取询价行。'));
$('mailMixed').onclick=()=>run(()=>importCase('/semantic-demo/mail-mixed',{method:'POST'},'合成邮件已导入，可让模型提取询价行。'));
$('proseDemo').onclick=()=>run(()=>importCase('/semantic-demo/prose',{method:'POST'},'合成正文已导入，请审阅修订候选。'));
$('revisionDemo').onclick=()=>run(()=>importCase('/semantic-demo/revision',{method:'POST'},'合成修订已导入，请审阅修订候选。'));
let modelState={};
async function refreshModelState(){const h=modelState=await request('/health');$('mode').className='mode '+(h.requests_enabled?'on':'off');$('modeText').textContent=h.requests_enabled?`真实模型已启用${h.request_count?` · 本轮 ${h.request_count} 次`:''}`:'离线本地 · 模型未启用';$('mode').title='本轮历史连接状态；不代表持续在线。平台未接入。';$('agentTool').hidden=$('landAgent').hidden=$('tourCard').hidden=!h.requests_enabled;$('uploadLandingBtn').classList.toggle('btn-primary',!h.requests_enabled)}
async function boot(){
  try{await refreshModelState()}
  catch(e){$('mode').className='mode down';$('modeText').textContent='本地 API 未连接';notice(e.message,true);return}
  document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.setAttribute('aria-current',String(b.dataset.view===document.body.dataset.view)));
  await refreshList();
  const hashed=location.hash.slice(1);if(/^[a-zA-Z0-9_-]{1,64}$/.test(hashed)&&caseList.some(c=>c.id===hashed))await openCase(hashed);
  try{const list=await request('/official');$('official').closest('details').hidden=!list.length;$('official').innerHTML=list.length?list.map((p,i)=>`<button type="button" class="list-btn" data-official="${i}">${esc(p)}</button>`).join(''):'<p class="hint">未发现本地官方素材。</p>';document.querySelectorAll('[data-official]').forEach(b=>b.onclick=()=>run(()=>importCase('/official/'+b.dataset.official,{method:'POST'},'官方素材仅本地解析；未发送至模型。')))}catch{$('official').innerHTML='<p class="hint">本地官方素材列表读取失败。</p>'}
}
renderLocalDraftStatus();
