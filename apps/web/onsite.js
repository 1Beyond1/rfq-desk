/* Account-scoped synthetic inbox and read-only business references. */
const inboxLabels={new_rfq:'新询价',revision:'回信或修订',other:'非询价',suspicious:'可疑'};
let inboxItems=[],onsiteMode='cases';
const referenceState={kind:'stock',query:'SYN-002',condition:'',unit:'EA',quantity:'6',semantic:true,rerank:false};

function workspaceMode(mode){
  onsiteMode=mode;
  $('onsiteHomePanel').hidden=mode==='cases';
  document.querySelector('#landing .land-cases').hidden=mode!=='cases';
  document.querySelector('#landing .land-create').hidden=mode!=='cases';
  for(const [id,m] of [['workspaceCases','cases'],['workspaceInbox','inbox'],['workspaceReferences','references']])$(id).setAttribute('aria-pressed',String(mode===m));
}
window.resetOnsiteHome=()=>workspaceMode('cases');
$('workspaceCases').onclick=()=>workspaceMode('cases');
$('workspaceInbox').onclick=()=>run(showInbox);
$('workspaceReferences').onclick=()=>{workspaceMode('references');renderReferences($('onsiteHomePanel'))};
$('deskInbox').onclick=()=>{showHome();run(showInbox)};

/* ---------- model stages: make Jev routing and RAG retrieval visible ---------- */
function pct(v){return Math.max(0,Math.min(1,Number(v)||0))}
function scoreBar(score,keyword){
  const n=Number(score);
  if(!Number.isFinite(n))return '';
  const ratio=keyword?Math.min(1,n/5):pct(n);
  const label=keyword?`命中 ${n}`:n.toFixed(3);
  return `<span class="score-bar"><i style="width:${Math.max(3,Math.round(ratio*100))}%"></i></span><span class="score-num">${esc(label)}</span>`;
}
/* 四个固定业务选项的概率条：模型到底在四个类别上各给多少分，一眼能看出来。 */
function jevStage(m){
  const d=m.decision, manual=m.manual;
  const shown=manual||d;
  if(!shown)return `<p class="stage-idle-line">尚未分流 · 点“分流这封邮件”让模型判断，或直接人工确认分类</p>`;
  const head=manual
    ? `<span class="stage-badge manual">人工确认</span><span class="stage-model">${esc(manual.actor)}</span>`
    : `<span class="stage-badge">${esc(d.provider)}</span>${d.model?`<span class="stage-model">${esc(d.model)}</span>`:''}${d.frozen?'<span class="stage-frozen">样本预置</span>':''}`;
  const scores=manual?null:(d.scores&&Object.keys(d.scores).length?d.scores:null);
  const bars=scores?`<ul class="prob-bars">${Object.entries(inboxLabels).map(([k,label])=>{
      const v=pct(scores[k]),win=shown.category===k;
      return `<li class="${win?'win':''}"><span class="pb-label">${esc(label)}</span><span class="pb-track"><i style="width:${(v*100).toFixed(1)}%"></i></span><span class="pb-val">${v.toFixed(3)}</span></li>`;
    }).join('')}</ul>`:'';
  const conf=!manual&&d.confidence!=null?`<span class="stage-conf">置信度 ${(Number(d.confidence)*100).toFixed(1)}%</span>`:'';
  const type=!manual&&d.score_type?`<span class="stage-type">${esc(d.score_type)}</span>`:'';
  const reason=esc(manual?manual.reason:(d.reason||''));
  const fallback=!manual&&d.fallback?.length?`<p class="stage-meta">${d.fallback.map(esc).join('；')}</p>`:'';
  const review=!manual&&d.needs_review?`<span class="stage-need">需人工确认</span>`:'';
  return `<div class="stage">${bars?bars:`<div class="stage-flat"><b>${esc(inboxLabels[shown.category]||shown.category)}</b></div>`}
    <div class="stage-foot"><div class="stage-head">${head}${conf}${review}</div>${reason?`<p class="stage-reason">${reason}</p>`:''}${type?`<p class="stage-meta">${type}</p>`:''}${fallback}${m.triage_warning?`<p class="reference-warning">${esc(m.triage_warning)}</p>`:''}</div></div>`;
}
/* RAG 链路：向量化 → 检索 → 重排，每一步走没走都写清楚。 */
function ragPipeline(result){
  const m=String(result.method||'');
  const semantic=/bge-m3/i.test(m), vector=/向量|COSINE/i.test(m)||semantic, rerank=/rerank/i.test(m), mo=/MatrixOne/i.test(m);
  if(!semantic&&!vector)
    return `<p class="rag-flat"><b>精确匹配</b><span>${esc(result.method||'本地副本')} · 不调用模型</span></p>`;
  const steps=[
    ['bge-m3',semantic?'查询向量化 · 1024 维':'未启用'],
    [mo?'MatrixOne 向量检索':'本地向量副本',mo?'VECF32 · COSINE_SIMILARITY':'余弦相似度 Top 5'],
    ['qwen3-rerank',rerank?'已重排召回结果':'未启用']
  ];
  return `<ol class="rag-pipeline">${steps.map(([name,desc],i)=>`<li class="${(i===0?semantic:i===1?true:rerank)?'on':'off'}"><b>${esc(name)}</b><span>${esc(desc)}</span></li>`).join('')}</ol>`;
}

function referenceResult(result){
  const names={part:'件号',alternative:'替代候选',description:'描述',condition:'件状',unit:'单位',quantity:'数量',warehouse:'库位',certificate:'证书状态',date:'历史报价日期',customer:'客户',currency:'币种',amount:'历史单价',valid_until:'历史有效期',lead_time:'交期',conditions:'适用条件',terms:'税费与运费条件',status:'报价状态',text:'条款原文'};
  const rows=result.records||[];
  return `<div class="reference-meta"><b>参考资料</b><span>${esc(result.method)}</span></div>
    ${result.warnings?.length?`<p class="reference-warning">${result.warnings.map(esc).join('；')}</p>`:''}
    ${result.note?`<p class="hint">${esc(result.note)}</p>`:''}
    ${result.eligible_groups?.length?`<p class="reference-stock-summary">${result.eligible_groups.map(g=>esc(`${g.condition} / ${g.unit}：可用 ${g.available}`+(g.shortage!=null?`，本次缺口 ${g.shortage}`:''))).join('；')}</p>`:''}
    ${result.other_conditions?.length?`<p class="reference-warning">同件号其他件状／单位（未计入可用量）：${result.other_conditions.map(o=>esc(`${o.id} ${o.condition} / ${o.unit}：${o.quantity} 件${o.warehouse?' · '+o.warehouse:''}`)).join('；')}</p>`:''}
    ${result.score_type?`<p class="hint">得分含义：${esc(result.score_type)}</p>`:''}
    ${ragPipeline(result)}
    <div class="reference-results">${rows.length?rows.map(r=>{
      const keyword=/关键词/.test(String(result.score_type||''));
      const main={stock:['condition','unit','quantity','warehouse'],quote:['condition','unit','amount','date','customer'],alternative:['alternative','conditions'],rule:['text']}[r.kind]||['condition','unit','quantity'];
      const rest=Object.entries(names).filter(([k])=>!main.includes(k)&&r[k]!==undefined&&r[k]!=='');
      return `<article class="reference-card"><header><b>${esc(r.part||r.description||r.id)}</b><span class="mono">${esc(r.id)}</span>${r.score!=null?scoreBar(r.score,keyword):''}</header>
        ${r.description?`<p class="reference-desc">${esc(r.description)}</p>`:''}
        <p class="reference-main">${main.filter(k=>r[k]!==undefined&&r[k]!=='').map(k=>`<span><i>${names[k]||k}</i>${esc(r[k])}</span>`).join('')}</p>
        ${r.differences?.length?`<p class="reference-warning">${r.differences.map(esc).join('；')}</p>`:''}
        ${rest.length?`<details class="reference-more"><summary>其余字段</summary><dl>${rest.map(([k,label])=>`<dt>${label}</dt><dd>${esc(r[k])}</dd>`).join('')}</dl></details>`:''}
        <footer>出处：${esc(r.source)}</footer></article>`}).join(''):`<p class="list-empty">${result.other_conditions?.length?'没有符合本次件状／单位的库存记录；上面的其他件状只作参考，不能直接替代。':'本次没有匹配的参考记录。请核对件号、条件或检索方式。'}</p>`}</div>`;
}

function renderReferences(root){
  root.innerHTML=`<div class="onsite-panel-title"><span class="eyebrow">只读参考 · 不修改正式询价或价表</span><h2>库存与历史参考</h2><p>件号明确时精确查询；只有描述时找候选件号。替代关系与历史价格须人工核对。</p></div>
    <form id="referenceForm" class="reference-form">
      <label>查询内容<select name="kind">${Object.entries({stock:'库存精确查询',parts:'描述或模糊件号',quote:'历史报价',alternative:'替代关系',rule:'业务规则'}).map(([k,v])=>`<option value="${k}" ${referenceState.kind===k?'selected':''}>${v}</option>`).join('')}</select></label>
      <label class="reference-query">件号或检索词<input name="query" required maxlength="300" value="${esc(referenceState.query)}" placeholder="如 SYN-002 或液压油滤芯"></label>
      <label>件状<input name="condition" maxlength="30" value="${esc(referenceState.condition)}" placeholder="留空看全部"></label>
      <label>单位<input name="unit" maxlength="30" value="${esc(referenceState.unit)}"></label>
      <label>需求数量<input name="quantity" maxlength="30" value="${esc(referenceState.quantity)}"></label>
      <div class="reference-options"><label><input name="semantic" type="checkbox" ${referenceState.semantic?'checked':''}>描述与规则使用语义检索</label><label><input name="rerank" type="checkbox" ${referenceState.rerank?'checked':''}>精排召回结果</label><label><input name="consent" type="checkbox">同意将本次检索词发送给模型（语义检索时需要）</label></div>
      <button type="submit" class="btn btn-primary">查询参考资料</button>
    </form><p class="hint">精确查询不调用模型。语义检索与精排使用模型；不可用时显示实际回退方式。</p><div id="referenceOutput" aria-live="polite"></div>`;
  root.querySelector('#referenceForm').onsubmit=e=>{e.preventDefault();const form=e.currentTarget,data=new FormData(form),output=root.querySelector('#referenceOutput');
    const body={kind:data.get('kind'),query:data.get('query').trim(),condition:data.get('condition').trim(),unit:data.get('unit').trim(),quantity:data.get('quantity').trim(),semantic:data.has('semantic'),rerank:data.has('rerank'),consent:data.has('consent')};
    Object.assign(referenceState,body);output.innerHTML='<p class="list-empty">正在查询参考资料…</p>';const done=busyButton(form.querySelector('button[type=submit]'),'查询中…');
    run(async()=>{try{const result=await request('/references/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(output.isConnected)output.innerHTML=referenceResult(result)}catch(error){if(output.isConnected)output.innerHTML=`<p class="reference-warning">${esc(error.message)}，可调整后重试。</p>`;throw error}finally{done()}});
  };
}
views.references=()=>{W().innerHTML='<div class="w-body" id="deskReferences"></div>';renderReferences($('deskReferences'))};
window.renderAgentReferences=turn=>turn.references?.length?`<details class="agent-reference-evidence"><summary>本轮查询依据 · ${turn.references.length} 项</summary>${turn.references.map(item=>`<section><h3>${esc(agentToolNames[item.tool]||item.tool)}</h3>${referenceResult(item.result)}</section>`).join('')}</details>`:'';

async function showInbox(){
  workspaceMode('inbox');$('onsiteHomePanel').innerHTML='<p class="list-empty">读取收件箱…</p>';
  const [messages,cases]=await Promise.all([request('/inbox'),request('/cases')]);
  inboxItems=messages;caseList=cases;if(onsiteMode==='inbox')renderInbox();
}
function renderInbox(){
  const root=$('onsiteHomePanel');
  const head=`<div class="onsite-panel-title"><span class="eyebrow">账号隔离 · 询价邮件</span><h2>询价收件箱</h2><p>样例保留真实Jev预置判定，可按需重新判断。实际模型和回退来源会显示在结果中。不确定或可疑邮件先交人工；修订需明确选择原工作单。</p><button type="button" class="btn" id="seedInbox">${inboxItems.length?'刷新样例':'载入 12 封样例'}</button></div>`;
  root.innerHTML=head+`<div class="inbox-list">${inboxItems.length?inboxItems.map(m=>{
    const effective=m.manual||m.decision,category=effective?.category;
    const blocked=!effective||!m.manual&&m.decision.needs_review||!['new_rfq','revision'].includes(category);
    const state=m.case_id?'linked':effective?'judged':'idle';
    return `<article class="inbox-card ${state}" data-mail="${esc(m.id)}">
      <header><div><h3>${esc(m.subject)}</h3><p class="hint">${esc(m.sender)} · 第${m.revision}版</p></div><b class="inbox-tag">${esc(inboxLabels[category]||'待分流')}</b></header>
      ${jevStage(m)}
      <div class="btn-row inbox-acts">
        ${m.case_id?`<button type="button" class="btn btn-primary" data-open-linked="${esc(m.id)}">打开已关联工作单</button>`
          :!effective?`<button type="button" class="btn btn-primary" data-triage-mail="${esc(m.id)}">分流这封邮件</button>`
          :m.decision?.frozen?`<button type="button" class="btn btn-ghost" data-triage-mail="${esc(m.id)}" data-force="1">让 Jev 重新判断一遍</button>`
          :`<button type="button" class="btn btn-ghost" data-triage-mail="${esc(m.id)}" disabled>已记录分流</button>`}
      </div>
      ${m.case_id||!effective?'':`<form data-open-mail="${esc(m.id)}" class="inbox-open">${category==='revision'?`<label>关联原工作单<select name="case_id" required><option value="">请明确选择</option>${caseList.map(c=>`<option value="${esc(c.id)}">${esc(c.title)} · ${esc(tail(c.id))}</option>`).join('')}</select></label>`:''}<button type="submit" class="btn ${!blocked?'btn-primary':''}" ${blocked?'disabled':''}>${category==='revision'?'保存为原工作单的修订原件':'交给询价工作单'}</button></form>`}
      ${!m.case_id?`<details class="inbox-review"><summary>人工确认或改判</summary><form data-review-mail="${esc(m.id)}"><label>分类<select name="category">${Object.entries(inboxLabels).map(([k,v])=>`<option value="${k}" ${category===k?'selected':''}>${v}</option>`).join('')}</select></label><label>判断依据<textarea name="reason" required minlength="5" maxlength="500" rows="2" placeholder="说明邮件意图，以及为什么应交给该流程"></textarea></label><button type="submit" class="btn">记录人工判断</button></form></details>`:''}
      <details class="inbox-source"><summary>邮件原文${m.events?.length?'与处理记录':''}</summary><pre>${esc(m.preview)}</pre>${m.events?.length?`<ol class="hint">${m.events.map(e=>`<li>${esc(e.at)} · ${esc(e.actor)} · ${esc(({triage:'模型/规则分流',manual_route:'人工确认分类',open_work_order:'关联工作单'})[e.action]||e.action)}${e.reason?' · '+esc(e.reason):''}</li>`).join('')}</ol>`:''}</details>
    </article>`;
  }).join(''):'<p class="list-empty">载入预置邮件后，可以体验分流与人工改判。</p>'}</div>`;
  $('seedInbox').onclick=()=>run(async()=>{const done=busyButton($('seedInbox'),'载入中…');try{await request('/inbox/samples',{method:'POST'});await showInbox()}finally{done()}});
  root.querySelectorAll('[data-open-linked]').forEach(b=>{const m=inboxItems.find(x=>x.id===b.dataset.openLinked);b.onclick=()=>run(()=>openCase(m.case_id))});
  root.querySelectorAll('[data-triage-mail]:not([disabled])').forEach(b=>b.onclick=()=>run(async()=>{const m=inboxItems.find(m=>m.id===b.dataset.triageMail),done=busyButton(b,'分流中…');try{await request(`/inbox/${m.id}/triage`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:m.revision,force:b.dataset.force==='1'})});await showInbox()}finally{done()}}));
  root.querySelectorAll('[data-review-mail]').forEach(form=>form.onsubmit=e=>{e.preventDefault();run(async()=>{const m=inboxItems.find(m=>m.id===form.dataset.reviewMail),data=new FormData(form);await request(`/inbox/${m.id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:m.revision,category:data.get('category'),reason:data.get('reason')})});await showInbox()})});
  root.querySelectorAll('[data-open-mail]').forEach(form=>form.onsubmit=e=>{e.preventDefault();run(async()=>{const m=inboxItems.find(m=>m.id===form.dataset.openMail),data=new FormData(form);const result=await request(`/inbox/${m.id}/open`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:m.revision,case_id:data.get('case_id')||''})});await openCase(result.case_id);if(current?.id===result.case_id&&modelState.requests_enabled)setFocus('agent');
  // 进工作单时问一句，不强制把导览接上。
  try{window.rfqSpotlight?.maybeInviteCase?.(result.case_id)}catch{}
})});
}
