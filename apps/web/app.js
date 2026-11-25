/* RFQ Desk shell: queue → workbench → source. This file owns view state, request ownership and unsaved input. */
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

let current=null,caseList=[],listLoading=true,listError='',focus=null,queueMode='todo',rowFilter='all',srcField=null,srcFile=null;
let materials={caseId:null,revision:-1,files:[],error:''};
const interaction=new RfqInteraction();
const rowDrafts=new Map(),pendingRowValues=new Map(),priceDrafts=new Map();
let browserStorage=null;try{browserStorage=window.localStorage}catch{}
const authState={required:false,user:null,csrf:null};
let storageNamespace='';
let localDrafts=new RfqDraftStore(null);
let listRequest=0,materialRequest=0,recoverySelection=null,recoveryRequest=0;
const draftKey=(id,row)=>id+':'+row;

/* ---------- unsaved form input ----------
   Any workbench control with data-keep survives re-render, server refreshes and focus switches.
   Keys are per case and per focus; names starting with "g:" are per case only (e.g. the approver). */
let tabStorage=null;try{tabStorage=window.sessionStorage}catch{}
let kept=new RfqFormMemory(null,()=>localDrafts.syncPolicy(),()=>current);
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
  try{r=await accountFetch(path,options)}catch{const e=Error('无法连接 API，请确认服务可用；本次操作结果未知，请刷新后核对。');e.network=true;throw e}
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
  if(error)notice('后台操作失败（详见“操作记录”）：'+message,true);
}
function toggleActivity(open=$('activityPanel').hidden){$('activityPanel').hidden=!open;$('activityBtn').setAttribute('aria-expanded',String(open));if(open){activityCount=0;$('activityCount').hidden=true;if($('accountMenu'))$('accountMenu').open=false}}
$('activityBtn').onclick=e=>{e.stopPropagation();toggleActivity()};
$('activityClear').onclick=()=>{$('taskActivity').innerHTML='';toggleActivity(false)};
document.addEventListener('click',e=>{
  if(!$('activityPanel').hidden&&!e.target.closest('.activity'))toggleActivity(false);
  if($('accountMenu')?.open&&!e.target.closest('.account-menu'))$('accountMenu').open=false;
});

/* ---------- navigation & server round trips ---------- */
function applyResponse(c,ctx,message){const applied=interaction.canApply(ctx,current,c);if(applied){show(c);if(message)notice(message,'ok')}else activity({...ctx,caseId:c.id,title:c.title},message||'后台已完成，请打开对应工作单核查');refreshList();return applied}
async function openCase(id){
  const ctx=interaction.navigate(id);
  try{const c=await request('/cases/'+encodeURIComponent(id));if(interaction.canDisplayNavigation(ctx,current,c)){show(c);notice('已打开 '+c.title+'（尾码 '+tail(c.id)+'），请核对当前版本。');closeDrawer();return c}}
  catch(e){if(interaction.navigationActive(ctx)){interaction.navigate(current?.id||null);notice('无法打开工作单 '+tail(id)+'：'+e.message,true)}}
}
async function refreshList(){
  const requestId=++listRequest;listLoading=true;listError='';renderCaseLists();
  try{const list=await request('/cases');if(requestId!==listRequest)return false;caseList=list;return true}
  catch(e){if(requestId===listRequest){listError=e.message;notice('工作单列表读取失败：'+e.message,true)}return false}
  finally{if(requestId===listRequest){listLoading=false;renderCaseLists()}}
}
let caseStatusFilter='all';
const caseStatusDefs=[['all','全部'],['cand','待审候选'],['clarify','待核对澄清'],['price','待核价'],['approve','待批准'],['output','可输出'],['archived','已归档']];
function matchesCaseStatus(c,status='all'){
  if(status==='archived')return Boolean(c.archived);
  if(c.archived)return false;
  if(status==='all')return true;
  if(status==='cand')return Number(c.pending_candidates||0)>0;
  if(status==='clarify')return Number(c.open_clarifications||0)>0||Number(c.all_open_clarifications||0)>0;
  if(status==='price')return Number(c.issue_rows||0)>0;
  const approvedAll=typeof c.case_approved==='boolean'?c.case_approved:Boolean(c.active&&c.approved===c.active);
  const ready=Boolean(Number(c.active||0)>0&&approvedAll&&!Number(c.issue_rows||0)&&!Number(c.pending_candidates||0)&&!c.pending_parse_review&&!Number(c.open_clarifications||0));
  if(status==='output')return ready;
  if(status==='approve')return Number(c.active||0)>0&&!ready&&!Number(c.issue_rows||0)&&!Number(c.pending_candidates||0)&&!c.pending_parse_review&&!Number(c.open_clarifications||0);
  return true;
}
function caseTodo(c){
  if(c.archived)return '已归档';
  if(c.pending_candidates)return `${c.pending_candidates} 条候选待审`;
  if(c.pending_parse_review)return '核查解析警告';
  if(c.open_clarifications)return `${c.open_clarifications} 项澄清未解决`;
  if(c.issue_rows)return `${c.issue_rows} 行待核对或核价`;
  const approvedAll=typeof c.case_approved==='boolean'?c.case_approved:Boolean(c.active&&c.approved===c.active);
  if(c.active&&approvedAll)return '报价可输出';
  if(c.active)return '等待人工批准';
  return '核对询价原件';
}
function caseButtons(filter,cls,status='all'){
  const q=filter.trim().toLowerCase();
  if(listLoading)return '<div class="list-empty loading-empty"><b>正在读取工作单…</b></div>';
  if(listError)return `<div class="list-empty"><b>工作单读取失败</b><p>${esc(listError)}</p><button type="button" class="btn" data-retry-cases>重新读取</button></div>`;
  const filtered=caseList.filter(c=>{
    const textOk=(c.title+' '+c.id).toLowerCase().includes(q);
    if(!textOk)return false;
    if(cls==='case-item')return q?true:!c.archived;
    return matchesCaseStatus(c,status);
  });
  return filtered.map(c=>{
    const pending=Number(c.issue_rows||0)+Number(c.open_clarifications||0)+Number(c.pending_candidates||0)+(c.pending_parse_review?1:0);
    const btn=`<button type="button" role="listitem" data-case="${esc(c.id)}" class="${cls}${c.id===current?.id?' current':''}${c.archived?' is-archived':''}"><span class="case-main"><b title="${esc(c.title)}">${esc(c.title)}</b><span class="case-meta"><span>尾码 ${esc(tail(c.id))}</span>${c.archived?'<span class="chip tone-off">已归档</span>':pending?`<span class="case-pending">${pending} 项待处理</span>`:'<span>无待处理事项</span>'}</span></span><span class="case-state"><b>${esc(caseTodo(c))}</b><small>${esc(c.archived?'已归档，可随时恢复':RfqUiState.nextStep(c))}</small></span><span class="case-version"><span>r${c.revision}</span><span>${Number(c.active||0)} 行 · ${Number(c.approved||0)} 已批准</span></span></button>`;
    if(cls==='case-card'){
      return `<div class="case-row${c.id===current?.id?' current':''}${c.archived?' is-archived':''}">${btn}<div class="case-row-acts"><button type="button" class="btn btn-sm btn-ghost" data-archive-case="${esc(c.id)}" title="${c.archived?'取消归档':'归档工作单'}">${c.archived?'恢复':'归档'}</button><button type="button" class="btn btn-sm btn-ghost danger-link" data-delete-case="${esc(c.id)}" title="删除工作单">删除</button></div></div>`;
    }
    return btn;
  }).join('')||`<div class="list-empty"><b>${q?'没有符合筛选的工作单':status==='archived'?'没有已归档的工作单':status!=='all'?'该状态下暂无工作单':'还没有工作单'}</b><p>${q?'换一个文件名或编号试试。':status==='archived'?'归档的工作单会出现在这里。':status!=='all'?'可切换到「全部」查看其他工作单。':'从本页右上角导入询价文件开始。'}</p></div>`;
}
function renderCaseStatusBar(){
  const bar=$('caseStatusBar');
  if(!bar)return;
  bar.innerHTML=caseStatusDefs.map(([k,label])=>{
    const count=caseList.filter(c=>matchesCaseStatus(c,k)).length;
    return `<button type="button" role="tab" aria-selected="${caseStatusFilter===k}" class="case-status-chip${caseStatusFilter===k?' on':''}" data-case-status="${k}">${label}${count?` <small>${count}</small>`:''}</button>`;
  }).join('');
  document.querySelectorAll('[data-case-status]').forEach(b=>b.onclick=()=>{caseStatusFilter=b.dataset.caseStatus;renderCaseLists()});
}
function renderCaseLists(){
  renderCaseStatusBar();
  $('cases').innerHTML=caseButtons($('caseFilter').value,'case-item');
  $('landingCases').innerHTML=caseButtons($('landingFilter').value,'case-card',caseStatusFilter);
  document.querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>run(()=>openCase(b.dataset.case)));
  document.querySelectorAll('[data-retry-cases]').forEach(b=>b.onclick=()=>run(refreshList));
  document.querySelectorAll('[data-archive-case]').forEach(b=>b.onclick=e=>{e.stopPropagation();const item=caseList.find(x=>x.id===b.dataset.archiveCase);if(item&&typeof toggleCaseArchive==='function')run(()=>toggleCaseArchive(item))});
  document.querySelectorAll('[data-delete-case]').forEach(b=>b.onclick=e=>{e.stopPropagation();const item=caseList.find(x=>x.id===b.dataset.deleteCase);if(item&&typeof deleteCaseWithConfirm==='function')run(()=>deleteCaseWithConfirm(item))});
}
$('caseFilter').oninput=$('landingFilter').oninput=renderCaseLists;
window.rfqMatchesCaseStatus=matchesCaseStatus;
window.resetCaseFilter=()=>{caseStatusFilter='all'};
async function toggleCaseArchive(item){
  if(!item)return;
  const nextArchived=!item.archived;
  const ok=await RfqDialog.confirm({
    title:nextArchived?'归档工作单':'取消归档工作单',
    body:nextArchived
      ?`将「${item.title}」移入已归档列表。所有版本、价格依据与审计记录完整保留，可随时切到「已归档」恢复。`
      :`将「${item.title}」恢复到默认工作单列表，继续处理。`,
    ok:nextArchived?'确认归档':'取消归档'
  });
  if(!ok)return;
  const c=await request(`/cases/${encodeURIComponent(item.id)}/archive`,{
    method:'PATCH',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({revision:item.revision,values:{archived:nextArchived}})
  });
  if(current?.id===c.id)show(c);
  await refreshList();
  notice(nextArchived?`已归档工作单「${c.title}」。`:`已取消归档「${c.title}」。`,'ok');
}
async function deleteCaseWithConfirm(item){
  if(!item)return;
  const ok=await RfqDialog.confirm({
    title:'永久删除工作单',
    body:`确认永久删除工作单「${item.title}」（尾码 ${tail(item.id)}）？此操作会移除该工作单及其上传原件与历史记录，无法恢复。`,
    ok:'确认删除',
    tone:'danger'
  });
  if(!ok)return;
  await request(`/cases/${encodeURIComponent(item.id)}`,{method:'DELETE'});
  for(const k of [...rowDrafts.keys()])if(k.startsWith(item.id+':'))rowDrafts.delete(k);
  for(const k of [...kept.keys()])if(k.startsWith(item.id+'|'))kept.delete(k);
  if(typeof localDrafts!=='undefined'&&localDrafts?.list){
    for(const r of localDrafts.list())if(r.caseId===item.id)localDrafts.removeIf(r.caseId,r.rowId,r.editId);
    renderLocalDraftStatus();
  }
  priceDrafts.delete(item.id);
  const wasCurrent=current?.id===item.id;
  if(wasCurrent){
    showCases();
    notice(`已删除工作单「${item.title}」。`,'ok');
  }else{
    await refreshList();
    notice(`已删除工作单「${item.title}」。`,'ok');
  }
}

function showHome(){
  // 工作区首页：Agent 说话，列表与收件箱都在入口里。
  if(window.resetOnsiteHome)window.resetOnsiteHome();
  window.rfqSpotlight?.dismiss?.();
  interaction.navigate(null);current=null;focus=null;srcField=null;srcFile=null;closeSource();closeDrawer();
  $('agentHome').hidden=false;$('landing').hidden=true;$('desk').hidden=true;
  $('mobileNav').hidden=true;$('srcToggle').hidden=true;$('refreshCase').hidden=true;
  if($('drawerRefreshCase'))$('drawerRefreshCase').hidden=true;
  $('caseEyebrow').textContent='工作区';$('title').textContent='工作区';$('title').removeAttribute('title');$('version').textContent='';notice('');
  history.replaceState(null,'',location.pathname+location.search);document.title='RFQ Desk · 询报价工作台';
  if(window.renderAgentHome)window.renderAgentHome();
  renderCaseLists();run(refreshList);
}
function showCases(){
  // 工作单列表（原 landing）：从首页入口进来。
  if(window.resetOnsiteHome)window.resetOnsiteHome();
  window.rfqSpotlight?.dismiss?.();
  interaction.navigate(null);current=null;focus=null;srcField=null;srcFile=null;closeSource();closeDrawer();
  $('agentHome').hidden=true;$('landing').hidden=false;$('desk').hidden=true;
  $('mobileNav').hidden=true;$('srcToggle').hidden=true;$('refreshCase').hidden=true;
  if($('drawerRefreshCase'))$('drawerRefreshCase').hidden=true;
  $('caseEyebrow').textContent='我的工作区';$('title').textContent='我的工作单';$('title').removeAttribute('title');$('version').textContent='';notice('');
  history.replaceState(null,'',location.pathname+location.search);document.title='RFQ Desk · 询报价工作台';
  renderCaseLists();run(refreshList);
}
window.showHome=showHome;
window.showCases=showCases;
$('homeBtn').onclick=showHome;
const refreshCurrentCase=()=>{if(current){closeDrawer();run(()=>openCase(current.id))}};
$('refreshCase').onclick=refreshCurrentCase;
if($('drawerRefreshCase'))$('drawerRefreshCase').onclick=refreshCurrentCase;
if($('queueRefreshCase'))$('queueRefreshCase').onclick=refreshCurrentCase;
function show(c){
  const switched=current?.id!==c.id;
  current=c;
  restorePriceDraft(c);
  if(switched){focus=null;srcField=null;srcFile=null;queueMode='todo';rowFilter='all';window.rfqSpotlight?.onCaseSwitch?.(c.id)}
  $('agentHome').hidden=true;$('landing').hidden=true;$('desk').hidden=false;$('mobileNav').hidden=false;$('srcToggle').hidden=false;$('refreshCase').hidden=false;
  if($('drawerRefreshCase'))$('drawerRefreshCase').hidden=false;
  const desk=$('desk');desk.dataset.caseId=c.id;desk.dataset.revision=c.revision;desk.dataset.priceVersion=c.price_version;
  $('caseEyebrow').textContent=(c.archived?'工作单 · 已归档 · 尾码 ':'工作单 · 尾码 ')+tail(c.id);$('title').textContent=c.title;$('title').title=c.title;
  $('version').innerHTML=`第 <b class="mono" id="revNo">${c.revision}</b> 版<span>价表 <b class="mono">v${c.price_version}</b></span>`;
  document.title=c.title+' · RFQ Desk';
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
  const needsReview=Boolean(c.warnings.length&&!c.review_note);
  const openQs=(c.clarifications||[]).filter(q=>openQuestion(q)&&active.some(r=>r.id===q.row_id)),stale=active.filter(r=>r.stale);
  const dirty=[...rowDrafts.keys()].filter(k=>k.startsWith(c.id+':')).length;
  const cands=freshCandidates(c).filter(p=>!replyCandidate(c,p));
  const pendingCands=Number(c.progress?.pending_candidates||0);
  const serverCaseApproved=typeof c.case_approved==='boolean'?c.case_approved:(typeof c.progress?.case_approved==='boolean'?c.progress.case_approved:null);
  const rowsApproved=Boolean(active.length&&active.every(r=>r.approved));
  const ready=Boolean(rowsApproved&&!needsReview&&!cands.length&&!pendingCands&&(serverCaseApproved===null?true:serverCaseApproved));
  const needsReapprove=Boolean(!ready&&rowsApproved&&serverCaseApproved===false);
  return {active,issues,approved,content,structural,priced,ready,needsReapprove,needsReview,openQs,stale,dirty,cands,pendingCands};
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
  groups.push({key:'output',title:'输出',done:false,items:[{type:'output',id:'o',title:s.ready?'输出报价响应':'报价响应（未就绪）',sub:s.ready?`${s.approved.length} 行已批准 · 预览 / HTML / CSV / XLSX`:'全部批准后才可正式输出',tone:s.ready?'ok':'off'}]});
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
function scrollDeskTop(){
  if(document.body.classList.contains('coach-docked')){
    const desk=$('desk');if(desk)desk.scrollTop=0;
  }else{
    scrollTo({top:0});
  }
}
function syncMobileNavActive(){
  const v=document.body.dataset.view;
  const agentActive=focus?.type==='agent'&&v==='work';
  document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.setAttribute('aria-current',String(!agentActive&&b.dataset.view===v)));
  const ma=$('mAgent');
  if(ma){ma.classList.toggle('on',agentActive);ma.setAttribute('aria-current',String(agentActive))}
}
function setFocus(type,id='',opts={}){
  focus={type,id};if(!opts.keepField)srcField=null;srcFile=null;
  renderGates();renderQueue();renderWork();renderSource();
  if(narrow())setView('work',{noScroll:opts.noScroll});
  else syncMobileNavActive();
  if(!opts.noScroll){$('work').scrollTo({top:0});if(narrow())scrollDeskTop()}
}
function nextFocus(){const items=queueItems().filter(i=>i.tone!=='off'),i=items.findIndex(x=>x.type===focus?.type&&x.id===focus?.id);const n=items[i+1]||items.find(x=>!(x.type===focus?.type&&x.id===focus?.id));return n||null}

/* ---------- render ---------- */
function render(){if(!current)return;renderGates();renderQueue();renderWork();renderSource()}
const gateDefs=[['content','核对'],['clarify','澄清'],['price','核价'],['approve','批准'],['output','报价单']];
function renderGates(){
  const {groups,s}=buildQueue(current),by=Object.fromEntries(groups.map(g=>[g.key,g]));
  const count={content:s.content.length+s.cands.length+(s.needsReview?1:0),clarify:s.openQs.length,price:s.priced.length,approve:s.ready?0:s.active.length?Math.max(1,s.active.length-s.approved.length):0,output:0};
  const active={warnings:'content',row:'content',cand:'content',materials:'content',q:'clarify',clarifications:'clarify',prices:'price',price:'price',approve:'approve',output:'output'}[focus?.type];
  $('gates').innerHTML=gateDefs.map(([k,l])=>{const g=by[k],done=k==='output'?s.ready:k==='content'?Boolean(s.active.length&&!count.content):k==='price'?Boolean(s.active.length&&g.done):g.done;return `<li><button type="button" data-gate="${k}" aria-current="${k===active?'page':'false'}" class="gate ${done?'done':count[k]?'open':'idle'}"><span>${l}</span>${done||count[k]?`<b>${done?'✓':count[k]}</b>`:''}</button></li>`}).join('');
  document.querySelectorAll('[data-gate]').forEach(b=>b.onclick=()=>{
    queueMode='todo';const key=b.dataset.gate,g=groups.find(g=>g.key===key||(key==='content'&&g.key==='warn'&&g.items.length)),item=g?.items[0];
    if(item)setFocus(item.type,item.id);
    else if(key==='content'){const row=current.rows.find(r=>!r.excluded);setFocus(row?'row':'materials',row?.id||'')}
    else{const target={clarify:['clarifications',''],price:['prices',''],approve:['approve','a'],output:['output','o']}[key];setFocus(...target)}
    document.querySelector(`[data-group="${key}"]`)?.scrollIntoView({block:'nearest'});
  });
  $('mqCount').textContent=s.issues.length+s.openQs.length?` ${s.issues.length+s.openQs.length}`:'';
}
const nextVerb={warnings:'核查解析警告',row:'核对询价行',q:'处理澄清',cand:'审阅修订候选',price:'补价格依据',approve:'批准当前版本',output:'输出报价响应'};
function renderNextCard(){
  const {groups,s}=buildQueue(current),live=groups.flatMap(g=>g.items).filter(i=>i.tone!=='off'),n=live[0];
  const here=n&&focus?.type===n.type&&focus?.id===n.id;
  $('nextCard').className='next-card'+(s.ready?' done':'');
  const verb=n&&(nextVerb[n.type]||'处理');
  $('nextCard').innerHTML=n?`<span class="next-label">${here?'当前事项':'下一步'}</span><b>${esc(verb)}</b>${n.title!==verb?`<span class="next-what" title="${esc(n.title)}">${esc(n.title)}</span>`:''}${!here?'<button type="button" class="text-btn" id="nextGo">打开此项 →</button>':''}`:'<span class="next-label">当前状态</span><b>没有待处理事项</b>';
  if($('nextGo'))$('nextGo').onclick=()=>setFocus(n.type,n.id);
}
function renderQueue(){
  renderNextCard();
  document.querySelectorAll('[data-queue]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.queue===queueMode)));
  document.querySelectorAll('[data-focus]').forEach(b=>b.classList.toggle('current',focus?.type===b.dataset.focus));
  if(queueMode==='rows')return renderRowList();
  const {groups}=buildQueue(current),isFocus=i=>focus&&focus.type===i.type&&focus.id===i.id;
  const expiredIds=current.rows.filter(r=>!r.excluded&&r.issue_codes.some(i=>i.code==='expired_due')).map(r=>r.id);
  const missingCondIds=current.rows.filter(r=>!r.excluded&&!String(r.condition||'').trim()).map(r=>r.id);
  const seen=new Set(),duplicateIds=[];
  for(const r of current.rows.filter(r=>!r.excluded)){
    const key=JSON.stringify(Object.keys(fieldNames).map(f=>r[f]));
    if(seen.has(key))duplicateIds.push(r.id);else seen.add(key);
  }
  const batchTools=(expiredIds.length?`<button type="button" class="btn btn-sm" id="batchDue">统一修改已过期行的截止日期</button>`:'')+(missingCondIds.length?`<button type="button" class="btn btn-sm" id="batchCondition">统一补充缺品相/件状行 (${missingCondIds.length})</button>`:'')+(duplicateIds.length?`<button type="button" class="btn btn-sm" id="batchDuplicates">每组完全重复只保留首行</button>`:'');
  $('queue').innerHTML=(batchTools?`<div class="row-tools">${batchTools}</div>`:'')+groups.filter(g=>g.items.length).map(g=>`<section class="q-group${g.done?' done':''}" data-group="${g.key}"><h3><span>${g.title}</span><small>${g.items.length}</small></h3>${g.items.map(i=>`<button type="button" class="q-item tone-${i.tone}${isFocus(i)?' current':''}" data-qtype="${i.type}" data-qid="${esc(i.id)}"><b class="${i.mono?'mono':''}">${esc(i.title)}</b><small>${esc(i.sub)}</small></button>`).join('')}</section>`).join('');
  if(expiredIds.length)$('batchDue').onclick=()=>run(async()=>{
    const btn=$('batchDue'),ids=expiredIds,ctx=interaction.capture(current);
    const answer=await RfqDialog.ask({title:'统一修改截止日期',body:`将对 ${ids.length} 行已过期行写入同一新截止日期，并记录本次裁定理由。`,ok:'保存裁定',fields:[
      {name:'due',label:'新截止日期（YYYY-MM-DD）',placeholder:'2026-12-31',maxlength:10,required:true,pattern:'^\\d{4}-\\d{2}-\\d{2}$',patternError:'请按 YYYY-MM-DD 填写'},
      {name:'reason',label:'统一裁定理由',type:'textarea',maxlength:500,required:true,missing:'请填写统一裁定理由'}
    ]});
    if(!answer)return;
    if(!interaction.active(ctx,current)){activity(ctx,'页面已切换，未发送旧操作',true);return}
    const task=interaction.begin(ctx,'batch-due'),done=typeof busyButton==='function'?busyButton(btn,'保存中…'):()=>{};
    try{
      const c=await request(`/cases/${ctx.caseId}/rows`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({revision:ctx.revision,values:{row_ids:ids,due:answer.due,reason:answer.reason}})
      });
      applyResponse(c,ctx,`已统一更新 ${ids.length} 行的截止日期。`);
    }catch(e){
      if(interaction.active(ctx,current))throw e;
      activity(ctx,'批量修改截止日期失败：'+e.message,true);
    }finally{interaction.finish(task);done()}
  });
  if(missingCondIds.length)$('batchCondition').onclick=()=>run(async()=>{
    const btn=$('batchCondition'),ids=missingCondIds,ctx=interaction.capture(current);
    const answer=await RfqDialog.ask({title:'统一补充品相 / 件状',body:`将为 ${ids.length} 行缺少品相/件状的询价行填入统一状态码（如 NEW、STD、全新、FN 等），并记录人工裁定理由。`,ok:'保存裁定',fields:[
      {name:'condition',label:'统一品相 / 件状',placeholder:'如 NEW / STD / 全新 / FN',maxlength:80,required:true,missing:'请填写统一品相或件状'},
      {name:'reason',label:'统一裁定理由',type:'textarea',maxlength:500,required:true,missing:'请填写统一裁定理由'}
    ]});
    if(!answer)return;
    if(!interaction.active(ctx,current)){activity(ctx,'页面已切换，未发送旧操作',true);return}
    const task=interaction.begin(ctx,'batch-condition'),done=typeof busyButton==='function'?busyButton(btn,'保存中…'):()=>{};
    try{
      const c=await request(`/cases/${ctx.caseId}/rows`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({revision:ctx.revision,values:{row_ids:ids,condition:answer.condition.trim(),reason:answer.reason}})
      });
      applyResponse(c,ctx,`已统一补充 ${ids.length} 行的品相/件状。`);
    }catch(e){
      if(interaction.active(ctx,current))throw e;
      activity(ctx,'批量补充品相/件状失败：'+e.message,true);
    }finally{interaction.finish(task);done()}
  });
  if(duplicateIds.length)$('batchDuplicates').onclick=()=>run(async()=>{
    const btn=$('batchDuplicates'),ids=duplicateIds,ctx=interaction.capture(current);
    const answer=await RfqDialog.ask({title:'排除完全重复行',body:`将排除 ${ids.length} 行与首行完全重复的记录，原件与首次出现行不变。`,ok:'排除重复行',fields:[
      {name:'reason',label:'统一裁定理由',type:'textarea',maxlength:500,required:true}
    ]});
    if(!answer)return;
    if(!interaction.active(ctx,current)){activity(ctx,'页面已切换，未发送旧操作',true);return}
    const task=interaction.begin(ctx,'batch-duplicates'),done=typeof busyButton==='function'?busyButton(btn,'排除中…'):()=>{};
    try{
      const c=await request(`/cases/${ctx.caseId}/rows`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({revision:ctx.revision,values:{row_ids:ids,excluded:true,reason:answer.reason}})
      });
      applyResponse(c,ctx,`已排除 ${ids.length} 行完全重复记录。`);
    }catch(e){
      if(interaction.active(ctx,current))throw e;
      activity(ctx,'批量排除重复行失败：'+e.message,true);
    }finally{interaction.finish(task);done()}
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
// "MIME text / row 4" reads as "第 4 行"; sheet and page names are kept when the source has them.
function srcShort(loc){const s=String(loc||''),page=s.match(/page\s*(\d+)/i),row=s.match(/(?:row|line)\s*(\d+)\s*$/i),sheet=s.match(/sheet\s+([^/]+?)\s*\//i);return [sheet?.[1],page&&`第 ${page[1]} 页`,row&&`第 ${row[1]} 行`].filter(Boolean).join(' · ')||s}
function srcGutter(loc){const s=String(loc||''),n=(s.match(/(\d+)\s*$/)||[])[1],page=s.match(/page\s*(\d+)/i);if(!n)return s;return (page?'P'+page[1]+' ':'')+(/row\s*\d+\s*$/i.test(s)?'表 ':'')+n}
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
    for(const f of Object.keys(fieldNames)){
      if(srcField&&f!==srcField)continue;
      const hasRaw=r.raw_fields&&f in r.raw_fields,hasValue=Boolean(r[f]||(hasRaw&&r.raw_fields[f]));if(!hasValue)continue;
      const specific=r.field_provenance?.[f]?.sources||[],sources=specific.length?specific:(r.sources||[]);
      for(const s of sources)add(s,f===srcField,fieldNames[f]+(specific.length?'':' · 行级'));
    }
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
function highlightSourceText(raw,quotes){
  const str=String(raw??'');
  if(!quotes||!quotes.size&&!quotes.length)return esc(str);
  const terms=[...new Set([...quotes].map(q=>String(q??'')).filter(Boolean))].sort((a,b)=>b.length-a.length);
  if(!terms.length)return esc(str);
  const ranges=[];
  const overlaps=(s,e)=>ranges.some(([rs,re])=>s<re&&e>rs);
  for(const term of terms){
    let pos=0;
    while(pos<=str.length-term.length){
      const idx=str.indexOf(term,pos);
      if(idx<0)break;
      const end=idx+term.length;
      if(!overlaps(idx,end)){ranges.push([idx,end]);break}
      pos=idx+1;
    }
  }
  if(!ranges.length)return esc(str);
  ranges.sort((a,b)=>a[0]-b[0]);
  let out='',cursor=0;
  for(const [s,e] of ranges){
    if(s>cursor)out+=esc(str.slice(cursor,s));
    out+=`<mark>${esc(str.slice(s,e))}</mark>`;
    cursor=e;
  }
  if(cursor<str.length)out+=esc(str.slice(cursor));
  return out;
}
window.rfqHighlightSourceText=highlightSourceText;
function renderSource(){
  if(!current)return;const marks=focusSources(),files=materials.caseId===current.id?materials.files:[];
  if(materials.caseId!==current.id){$('srcBody').innerHTML='<p class="hint pad">读取原件…</p>';$('srcFiles').innerHTML='';return}
  if(materials.error){$('srcBody').innerHTML=`<p class="msg error pad">原件读取失败：${esc(materials.error)}</p>`;return}
  if(!files.some(f=>f.file===srcFile)){const strong=marks.find(m=>m.strong),pick=strong||marks[0];const main=current.rows[0]?.sources?.[0]?.file;srcFile=(pick&&files.some(f=>f.file===pick.file))?pick.file:files.some(f=>f.file===main)?main:files[0]?.file||null}
  $('srcFiles').hidden=files.length<2;$('srcFiles').innerHTML=files.map(f=>{const n=marks.filter(m=>m.file===f.file).length;return `<button type="button" role="tab" data-srcfile="${esc(f.file)}" aria-selected="${f.file===srcFile}" class="${n?'linked':''}" title="${esc(f.file)}"><span>${esc(f.file)}</span>${n?`<i aria-label="${n} 处关联">${n}</i>`:''}</button>`}).join('');
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
  const lineHtml=(u,i)=>{const h=hits.get(i);const text=h?highlightSourceText(u.text,h.quotes):esc(u.text);return `<div class="src-line${h?' hit':''}${h?.strong?' strong':''}${whole?' whole':''}" data-line="${i}"><span class="loc mono" title="${esc(u.location)}">${esc(srcGutter(u.location))}</span><span class="txt">${text||'<i class="hint">（空行）</i>'}</span>${h?`<span class="tag">${esc([...h.labels].join(' · '))}${h.how==='number'?' · 按行号对应':''}</span>`:''}</div>`};
  $('srcBody').innerHTML=`<p class="src-meta"><span class="mono">SHA-256 ${esc(file.sha256.slice(0,16))}…</span>${approx?' · 部分高亮按行号对应，请核对原文':''}${whole?' · 本文件是此问题的答复原件':''}</p>`+file.units.slice(0,800).map(lineHtml).join('')+(file.units.length>800?'<p class="hint pad">仅显示前 800 段。</p>':'');
  const target=$('srcBody').querySelector('.src-line.strong')||$('srcBody').querySelector('.src-line.hit');
  if(target)target.scrollIntoView({block:'center'});
}
function showSourceField(f){srcField=f;srcFile=null;renderSource();document.querySelectorAll('[data-srcfield]').forEach(b=>b.classList.toggle('on',b.dataset.srcfield===f));if(narrow())setView('source');else if(innerWidth<=1180)openSource()}

/* ---------- layout chrome ---------- */
function openDrawer(){toggleActivity(false);if($('accountMenu'))$('accountMenu').open=false;$('drawer').hidden=false;$('scrim').hidden=false;$('caseBtn').setAttribute('aria-expanded','true');$('caseFilter').focus()}
function closeDrawer(){$('drawer').hidden=true;$('scrim').hidden=true;$('caseBtn').setAttribute('aria-expanded','false')}
$('caseBtn').onclick=openDrawer;$('drawerClose').onclick=closeDrawer;$('scrim').onclick=()=>{closeDrawer();closeSource()};
function setView(v,opts={}){
  document.body.dataset.view=v;
  syncMobileNavActive();
  if(v==='source')renderSource();
  if(!opts.noScroll)scrollDeskTop();
}
document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.onclick=()=>{
  if(b.dataset.view==='work'&&focus?.type==='agent'&&current){
    const f=firstFocus();if(f){setFocus(f.type,f.id);return}
  }
  setView(b.dataset.view);
});
function openSource(){document.body.classList.add('src-open')}
function closeSource(){document.body.classList.remove('src-open')}
$('srcToggle').onclick=()=>document.body.classList.contains('src-open')?closeSource():openSource();
$('srcClose').onclick=()=>{if(narrow())setView('work');else closeSource()};
function isEditableTarget(el){
  if(!el)return false;
  const tag=String(el.tagName||'').toUpperCase();
  return tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||Boolean(el.isContentEditable);
}
function visibleSearchInput(){
  if(!$('drawer')?.hidden&&$('caseFilter'))return $('caseFilter');
  if(!$('landing')?.hidden){
    if(!$('onsiteHomePanel')?.hidden){
      return $('inboxSearch')||document.querySelector('#onsiteHomePanel input[name="query"]');
    }
    return $('landingFilter');
  }
  if(!$('desk')?.hidden&&current){
    if(queueMode!=='rows'){queueMode='rows';renderQueue()}
    return $('rowSearch');
  }
  if(!$('agentHome')?.hidden)return $('ahInput');
  return null;
}
function handleWorkbenchShortcut(e){
  if(document.body.dataset.auth!=='ready')return false;
  if(e.ctrlKey||e.metaKey)return false;
  if(document.querySelector('dialog[open]'))return false;
  if(isEditableTarget(e.target)||isEditableTarget(document.activeElement))return false;
  if(e.altKey&&(e.key==='s'||e.key==='S'||e.code==='KeyS')){
    if(!current||$('desk')?.hidden)return false;
    e.preventDefault();
    if(narrow())setView(document.body.dataset.view==='source'?'work':'source');
    else document.body.classList.contains('src-open')?closeSource():openSource();
    return true;
  }
  if(e.altKey)return false;
  if((e.key==='['||e.key===']')&&current&&!$('desk')?.hidden){
    const items=queueItems().filter(i=>i.tone!=='off');
    if(!items.length)return false;
    e.preventDefault();
    const idx=items.findIndex(x=>x.type===focus?.type&&x.id===focus?.id);
    const target=e.key===']'
      ?(idx>=0?items[(idx+1)%items.length]:items[0])
      :(idx>=0?items[(idx-1+items.length)%items.length]:items[items.length-1]);
    setFocus(target.type,target.id);
    return true;
  }
  if(e.key==='/'){
    const input=visibleSearchInput();
    if(!input)return false;
    e.preventDefault();
    input.focus();
    input.select?.();
    return true;
  }
  if(e.key==='?'){
    e.preventDefault();
    RfqDialog.alert({
      title:'工作台快捷键',
      body:[
        '[  切换到上一项待办',
        ']  切换到下一项待办',
        'Alt + S  展开 / 收起原件对照抽屉',
        '/  聚焦当前页面搜索框',
        'Esc  关闭弹窗、抽屉或退出引导',
        '?  打开此快捷键一览表',
        '',
        '提示：在输入框、文本框或弹窗打开时，快捷键自动静默。'
      ].join('\n'),
      ok:'知道了'
    });
    return true;
  }
  return false;
}
window.rfqHandleShortcut=handleWorkbenchShortcut;
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(document.querySelector('dialog[open]')){e._rfqOverlayEscape=true;return}
    if(!$('drawer').hidden){closeDrawer();e._rfqOverlayEscape=true;return}
    if(!$('activityPanel').hidden){toggleActivity(false);e._rfqOverlayEscape=true;return}
    if($('accountMenu')?.open){$('accountMenu').open=false;e._rfqOverlayEscape=true;return}
    if(document.body.classList.contains('src-open')){closeSource();e._rfqOverlayEscape=true}
    return;
  }
  handleWorkbenchShortcut(e);
});
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
$('clearLocalDrafts').onclick=()=>run(async()=>{
  if(!await RfqDialog.confirm({title:'清除本机暂存',body:'清除本浏览器全部暂存草稿。当前页尚未保存的编辑仍保留，重新输入会再次暂存。',ok:'清除暂存',tone:'danger'}))return;
  const ok=localDrafts.clear();kept.clearPersisted();renderLocalDraftStatus();notice(ok?'本浏览器暂存已清除；当前页编辑仍保留，继续输入会再次暂存；关闭开关可停止并清除。':'未能确认清除，请查看暂存提示。',!ok);
});
$('localDraftEnabled').onchange=()=>{localDrafts.setEnabled($('localDraftEnabled').checked);if(!localDrafts.enabled)kept.clearPersisted();renderLocalDraftStatus()};
$('retryLocalDrafts').onclick=()=>{for(const [key,d] of rowDrafts){const split=key.indexOf(':');persistRowDraft(key.slice(0,split),key.slice(split+1),d)}renderLocalDraftStatus()};
window.addEventListener('storage',e=>{const key=storageNamespace&&e.key?.startsWith(storageNamespace)?e.key.slice(storageNamespace.length):e.key;if(key===null||key?.startsWith(RfqDraftStore.PREFIX)||key===RfqDraftStore.SETTINGS){localDrafts.syncPolicy();if(!localDrafts.enabled)kept.clearPersisted();renderLocalDraftStatus();notice(key===RfqDraftStore.SETTINGS||key===null?(localDrafts.enabled?'本浏览器暂存已明确开启；当前编辑未自动提交，可重试暂存。':localDrafts.policyMessage):'本浏览器其他页面的暂存记录有变化；当前编辑未自动替换，请核对。')}});
window.addEventListener('beforeunload',e=>{if(rowDrafts.size||priceDrafts.size||kept.size){e.preventDefault();e.returnValue='有未保存修改'}});

/* ---------- shared helpers for outputs ---------- */
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
async function fetchExport(ctx,format,operation='preview'){
  if(apiConfigError)throw Error(apiConfigError);
  const formal=operation==='export';
  const path=formal?`/cases/${ctx.caseId}/exports`:`/cases/${ctx.caseId}/quote-preview?format=${format}&revision=${ctx.revision}`;
  const options=formal?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ctx.revision,values:{format}})}:{};
  let r;try{r=await accountFetch(path,options)}catch{throw Error(formal?'无法确认正式输出是否完成；请刷新并查看实录后决定是否重试。':'预览连接失败，未发出正式导出；请检查API服务后重试。')}
  if(!r.ok){let detail='HTTP '+r.status;try{detail=(await r.json()).detail}catch{}throw Error(detail)}
  return r;
}

/* ---------- intake & boot ---------- */
async function uploadCase(input){const f=input.files[0];if(!f)return;const data=new FormData();data.append('file',f);try{await importCase('/import',{method:'POST',body:data},`已导入 ${f.name}；左侧列出挡住报价的事项，右侧对照原件。`)}finally{input.value=''}}
$('upload').onchange=()=>run(()=>uploadCase($('upload')));$('uploadLanding').onchange=()=>run(()=>uploadCase($('uploadLanding')));$('uploadSide').onchange=()=>run(()=>uploadCase($('uploadSide')));
const demo=()=>importCase('/demo',{method:'POST'},'已导入样例：重复 / 冲突 / 缺价。');
$('demo').onclick=$('start').onclick=()=>run(demo);
$('lifecycle').onclick=()=>run(()=>importCase('/lifecycle-demo',{method:'POST'},'变更演练：从两条独立询价开始，可报价、撤回价源、澄清后重新批准。'));
$('mailDemo').onclick=()=>run(()=>importCase('/semantic-demo/prose',{method:'POST'},'离线标签样例已导入：可在「原件与修订候选」生成离线标签候选并审阅。'));
$('mailRevision').onclick=()=>run(()=>importCase('/semantic-demo/mail-revision',{method:'POST'},'邮件已导入，可让模型提取询价行。'));
$('mailMixed').onclick=()=>run(()=>importCase('/semantic-demo/mail-mixed',{method:'POST'},'邮件已导入，可让模型提取询价行。'));
$('proseDemo').onclick=()=>run(()=>importCase('/semantic-demo/prose',{method:'POST'},'正文已导入，请审阅修订候选。'));
$('revisionDemo').onclick=()=>run(()=>importCase('/semantic-demo/revision',{method:'POST'},'修订已导入，请审阅修订候选。'));
let modelState={};
async function refreshModelState(){
  const h=modelState=await request('/health'),enabled=Boolean(h.requests_enabled),isDemo=authState.user?.role==='demo';
  $('mode').className='mode '+(enabled?'on':'off');$('modeText').textContent=enabled?'AI 已启用':'离线模式';
  $('mode').title=enabled?'AI 可处理邮件；结果仍需人工核对。':'模型未启用，可先导入文件并使用本地解析。';
  $('agentEntry').hidden=$('landAgent').hidden=false;$('tourCard').hidden=false;$('tourStart').disabled=false;
  if($('tourTitle'))$('tourTitle').textContent=enabled?'跟着引导体验一次 · 约 3 分钟':'离线工单引导体验 · 约 2 分钟';
  if($('tourDesc'))$('tourDesc').textContent=enabled?'询价 Agent 读一封客户邮件，你来核对、核价、批准和导出。':'导入合成询价单，跟着聚光灯走完核对、核价、批准和导出（无需联网模型）。';
  $('tourStart').textContent=enabled?'开始引导体验':'开始离线引导体验';
  $('agentMailSend').disabled=!enabled||isDemo;
  if($('agentMail'))$('agentMail').disabled=isDemo;
  $('mailServiceHint').textContent=isDemo?'访客体验使用合成材料；粘贴新建工作单请登录正式账号。':enabled?'提取结果由你确认后，再进入正式询价。':'当前为离线模式，请先使用“导入询价文件”。';
  document.querySelectorAll('[data-agent-sample]').forEach(b=>b.disabled=!enabled);
  if(isDemo){
    document.querySelectorAll('input[type=file]').forEach(el=>{
      el.disabled=true;
      const lbl=el.closest('label');
      if(lbl){lbl.classList.add('is-disabled');lbl.setAttribute('aria-disabled','true');lbl.setAttribute('title','访客体验使用合成材料；导入自有文件请登录正式账号')}
    });
    const ahImp=document.querySelector('[data-ah-go="import"]');
    if(ahImp){ahImp.classList.add('is-demo-disabled');ahImp.setAttribute('aria-disabled','true');ahImp.setAttribute('title','访客体验使用合成材料；导入自有文件请登录正式账号')}
  }
}
document.addEventListener('click',e=>{
  const lbl=e.target.closest?.('.file-btn.is-disabled');
  if(lbl&&authState.user?.role==='demo'){
    e.preventDefault();
    notice('访客体验使用合成材料；导入自有文件请登录正式账号。');
  }
});
async function boot(){
  if(!await initializeAccount())return;
  try{await refreshModelState()}
  catch(e){$('mode').className='mode down';$('modeText').textContent='API 未连接';listLoading=false;$('landingCases').innerHTML=`<div class="list-empty"><b>工作单读取失败</b><p>${esc(e.message)}</p><button type="button" class="btn" id="retryBoot">重新连接</button></div>`;$('retryBoot').onclick=()=>run(boot);notice(e.message,true);return}
  document.querySelectorAll('#mobileNav [data-view]').forEach(b=>b.setAttribute('aria-current',String(b.dataset.view===document.body.dataset.view)));
  try{if(!await refreshList())return}
  catch(e){listLoading=false;$('landingCases').innerHTML=`<div class="list-empty"><b>工作单读取失败</b><p>${esc(e.message)}</p><button type="button" class="btn" id="retryBoot">重新读取</button></div>`;$('retryBoot').onclick=()=>run(boot);notice(e.message,true);return}
  const hashed=location.hash.slice(1);
  if(/^[a-zA-Z0-9_-]{1,64}$/.test(hashed)&&caseList.some(c=>c.id===hashed))await openCase(hashed);
  else showHome();
  try{const list=await request('/official');$('official').closest('details').hidden=!list.length;$('official').innerHTML=list.length?list.map((p,i)=>`<button type="button" class="list-btn" data-official="${i}">${esc(p)}</button>`).join(''):'<p class="hint">未发现本地受保护原件。</p>';document.querySelectorAll('[data-official]').forEach(b=>b.onclick=()=>run(()=>importCase('/official/'+b.dataset.official,{method:'POST'},'受保护原件仅本地解析；未发送至模型。')))}catch{$('official').innerHTML='<p class="hint">本地受保护原件列表读取失败。</p>'}
}
renderLocalDraftStatus();
