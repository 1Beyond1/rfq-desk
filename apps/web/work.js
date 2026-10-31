/* Workbench views: each queue item is handled in place. Nothing here decides business validity; every action goes to the API and the response is re-rendered. */
const W=()=>$('work');
const qsa=sel=>[...W().querySelectorAll(sel)];
const kindLabel=k=>({synthetic:'合成演示',manual:'已授权人工核价',authorized:'已授权价表'}[k]||k||'未标注');
const rowById=id=>current.rows.find(r=>r.id===id);
const label=r=>`${esc(r.rfq||'缺询价号')} / ${esc(r.part||'缺件号')}`;
function setKeep(el,value){el.value=value;kept.set(keepKey(el.dataset.keep),value)}
function busyButton(b,text){if(!b)return()=>{};const old=b.textContent;b.disabled=true;b.textContent=text;return()=>{if(b.isConnected){b.disabled=false;b.textContent=old}}}

function renderWork(){
  if(!current)return;const w=W(),act=document.activeElement;let restore=null;
  if(act&&w.contains(act)&&(act.dataset.keep||act.name))restore={keep:act.dataset.keep,name:act.name,s:act.selectionStart,e:act.selectionEnd};
  (views[focus?.type]||viewMissing)();
  restoreKept(w);
  const scope=current.id+'|'+focusKey()+'|',stale=kept.stale(scope,current).filter(([k])=>!k.endsWith('|p:catalog'));
  if(stale.length){const note=document.createElement('details');note.className='note warn';const summary=document.createElement('summary');summary.textContent='有旧版本未提交填写，保留供对照；确认选项不会自动恢复';note.append(summary);for(const [k,v] of stale){const line=document.createElement('p');line.className='hint';line.textContent=k.split('|').pop()+'：'+(typeof v==='boolean'?'旧确认项，须重新核对':v);note.append(line)}const discard=document.createElement('button');discard.type='button';discard.className='btn btn-sm';discard.textContent='放弃这些旧版填写';discard.onclick=()=>{for(const [k] of stale)kept.delete(k);renderWork()};note.append(discard);w.querySelector('.w-body')?.prepend(note)}
  qsa('[data-refresh-case]').forEach(b=>b.onclick=()=>run(()=>openCase(current.id)));
  const n=nextFocus();qsa('[data-next]').forEach(b=>{if(n)b.onclick=()=>setFocus(n.type,n.id);else b.remove()});
  qsa('[data-goto]').forEach(b=>b.onclick=()=>{const [t,id]=b.dataset.goto.split('|');setFocus(t,id||'')});
  qsa('[data-srcfield]').forEach(b=>b.onclick=()=>showSourceField(b.dataset.srcfield));
  if(restore){const el=restore.keep?w.querySelector(`[data-keep="${CSS.escape(restore.keep)}"]`):w.querySelector(`[name="${CSS.escape(restore.name)}"]`);if(el&&!el.disabled){el.focus({preventScroll:true});try{if(restore.s!=null)el.setSelectionRange(restore.s,restore.e)}catch{}}}
}
function head(gate,title,{sub='',chip='',mono=false}={}){
  const n=nextFocus();
  return `<header class="w-head"><div class="w-title"><span class="eyebrow">${gate}</span><h2 class="${mono?'mono':''}">${title}</h2>${sub?`<p class="w-sub">${sub}</p>`:''}</div><div class="w-head-r">${chip}<button type="button" class="btn btn-sm btn-ghost" data-refresh-case>刷新当前工作单</button>${n?`<button type="button" class="btn btn-sm btn-ghost" data-next>下一项：${esc(n.title)} →</button>`:''}</div></header>`;
}
const views={row:viewRow,price:viewPrice,q:viewQuestion,cand:viewCandidate,warnings:viewWarnings,approve:viewApprove,output:viewOutput,prices:viewCatalog,materials:viewMaterials,clarifications:viewClarifications,log:viewLog};
function viewMissing(){W().innerHTML=head('已处理','此项已不存在或已被处理',{sub:'服务器版本已更新。请从左侧待办选择下一项。'})}

/* ---------- row: content review ---------- */
const fieldByLabel=Object.fromEntries(Object.entries(fieldNames).map(([k,v])=>[v,k]));
function issueBlock(x,r,info={}){
  const qs=(current.clarifications||[]).filter(q=>q.row_id===r.id);
  const openFor=f=>qs.find(q=>q.field===f&&openQuestion(q));
  const register=f=>{const q=f&&openFor(f);return q?`<button type="button" class="btn btn-sm" data-goto="q|${q.id}">处理已登记澄清 ${esc(q.id)}</button>`:'<button type="button" class="btn btn-sm" data-register>登记澄清问题</button>'};
  let tone='bad',help='',acts='';
  const code=info.code;
  if(RfqUiState.isPrice(info)){tone='price';help=code==='ambiguous_price'?'同一件号/单位/件状同时有多条有效价源，需撤回或调整其中之一。':'没有提供唯一有效价格依据前保持待报价，不能批准。';acts=`<button type="button" class="btn btn-sm" data-goto="price|${r.id}">去核价</button>`}
  else if(code==='missing_field'){const f=info.field||fieldByLabel[x.slice(2)],name=fieldNames[f]||x.slice(2);help=`原件没有提供${name}。需要对方确认就登记本行澄清；已有书面依据可在下方直接填写并写明依据。未知缩写不自行解释。`;acts=register(f)+(f?`<button type="button" class="btn btn-sm btn-ghost" data-edit="${f}">直接填写${esc(name)}</button>`:'')}
  else if(code==='unconfirmed_value'){help='导入时保留了需要人工确认的原值。核对右侧原件后在下方写明依据保存，或登记澄清。';acts=register()}
  else if(code==='duplicate_row'){help='同一询价同一件号出现完全相同的行。确认是重复后排除其中一行；系统不会自动合并。';acts=`<button type="button" class="btn btn-sm" data-exclude>排除此行</button>`}
  else if(code==='conflicting_row'){help='同一询价同一件号的字段不一致，不能自动合计或取最新。依据原件裁定，或登记澄清请对方确认。';acts=register()}
  else if(code==='invalid_quantity')help='数量不是有效正数。依据原件改正并写明依据，或登记澄清。';
  else if(code==='expired_due')help='截止日期早于今天，需要确认是否延期后再报价。';
  else if(code==='invalid_due')help='截止日期无法识别为日期，请按原件确认后改为 YYYY-MM-DD。';
  else if(code==='requirements_review')help='有特殊要求尚未核验。核验后在“裁定依据”写明结论并保存。';
  else if(code==='open_clarification'){const id=info.question_id||x.split('/').pop().trim();help='已登记的澄清尚未解决。收到答复不等于解决，需逐项核对回填。';acts=`<button type="button" class="btn btn-sm" data-goto="q|${esc(id)}">处理澄清 ${esc(id)}</button>`}
  return `<div class="issue tone-${tone}"><div><b>${esc(x)}</b><p>${help}</p></div>${acts?`<div class="issue-acts">${acts}</div>`:''}</div>`;
}
function viewRow(){
  const r=rowById(focus.id);if(!r)return viewMissing();
  const [st,tone]=rowStatus(r),qs=(current.clarifications||[]).filter(q=>q.row_id===r.id);
  const rows=Object.entries(fieldNames).map(([f,l])=>{
    const hasRaw=r.raw_fields&&f in r.raw_fields,raw=hasRaw?r.raw_fields[f]:null,changed=hasRaw?raw!==r[f]:Boolean(r[f]);
    const p=r.field_provenance?.[f]||{kind:'row'},hasValue=Boolean(r[f]||(hasRaw&&raw)),src=hasValue?(p.sources?.[0]||r.sources?.[0]):null;
    return `<tr class="${changed?'changed':''}${!r[f]&&['rfq','part','quantity','unit','condition'].includes(f)?' empty':''}"><th>${l}</th><td><input name="${f}" value="${esc(r[f])}" class="${monoFields.has(f)?'mono':''}" aria-label="${l}"></td><td class="raw mono">${hasRaw?(raw===''?'<i class="hint">空</i>':esc(raw)):'<i class="hint">原文未提供</i>'}</td><td>${src?`<button type="button" class="src-link${srcField===f?' on':''}" data-srcfield="${f}" title="${esc(src.file+' / '+src.location+(src.quote?' / 「'+src.quote+'」':''))}">${esc(src.file)}<small>${esc(src.location)}${p.inherited_from?' · 继承 v'+p.inherited_from.row_revision:''}</small></button>`:'<span class="hint">—</span>'}</td><td class="ev" data-ev="${f}"><span class="hint">核验中…</span></td></tr>`}).join('');
  W().innerHTML=head(r.excluded?'询价行 · 已排除':'询价行 · 内容核对',missing(r.part,'件号'),{mono:true,sub:`RFQ <b class="mono">${missing(r.rfq,'询价号')}</b> · 数量 <b class="mono">${missing(r.quantity,'数量')} ${missing(r.unit,'单位')}</b> · 件状 <b class="mono">${missing(r.condition,'件状')}</b> · 行版本 ${r.revision}`,chip:`<span class="chip tone-${tone}">${esc(st)}</span>`})+
  `<div class="w-body">
    ${r.issues.length?`<section class="issues">${RfqUiState.issues(r).map(x=>issueBlock(x.message,r,x)).join('')}</section>`:`<p class="note ok">${r.excluded?'此行已排除，不参与批准与输出。':'没有未解决业务异常。'}</p>`}
    ${r.stale?'<p class="note warn">旧批准已失效：输入、价源、澄清或业务日期已变化，需重新批准当前版本。</p>':''}
    <form id="rowForm" class="card">
      <div class="card-head"><h3>字段核对与人工裁定</h3><span class="hint">点“出处”在右侧原件中定位；改动后需填写依据并保存。</span></div>
      <div class="table-wrap flat"><table class="ftable"><thead><tr><th>字段</th><th>当前值</th><th>原值</th><th>出处</th><th>核验</th></tr></thead><tbody>${rows}</tbody></table></div>
      <label class="reason">裁定依据 / 人工确认说明<textarea name="reason" required rows="2" placeholder="依据哪份原件或谁确认；不对未知缩写作解释">${esc(r.resolution)}</textarea></label>
      <div class="btn-row"><button type="submit" class="btn btn-primary">保存裁定</button><button type="button" class="btn" data-exclude>${r.excluded?'恢复此行':'排除此行'}</button></div>
      <p class="msg" id="evidenceNote"></p>
    </form>
    <div class="split">
      <section class="card"><div class="card-head"><h3>价格依据</h3></div>${r.price?`<p class="big mono">${esc(r.price.currency)} ${esc(r.price.amount)} <small>× ${esc(r.quantity)} = ${esc(r.total)}</small></p><p class="hint">${esc(kindLabel(r.price.kind))} · ${esc(r.price.source)}<br>交期 ${esc(r.price.lead_time)} · 有效 ${esc(r.price.valid_from)} 至 ${esc(r.price.valid_until)}</p>`:r.excluded?'<p class="hint">已排除行不核价。</p>':`<p class="hint">${esc(rowPriceIssue(r)||'无价格依据')}</p>`}${r.excluded?'':`<button type="button" class="btn btn-sm" data-goto="price|${r.id}">${r.price?'查看核价':'去核价'}</button>`}</section>
      <section class="card"><div class="card-head"><h3>本行澄清</h3></div>${qs.length?qs.map(q=>`<button type="button" class="link-row" data-goto="q|${q.id}"><span class="chip tone-${clarificationTone[q.state]}">${esc(RfqUiState.questionLabel(q))}</span> ${esc(fieldNames[q.field]||'重复归属')} <small class="mono">${esc(q.id)}</small></button>`).join(''):'<p class="hint">没有登记澄清。</p>'}</section>
    </div>
    <details class="more"><summary>原始值与完整来源</summary>${r.sources.map(s=>`<p class="hint">${esc(s.file)} · ${esc(s.location)} · <span class="mono">SHA-256 ${esc(s.sha256)}</span></p><pre class="pre">${esc(JSON.stringify(s.raw??s.quote,null,2))}</pre>`).join('')}<p class="hint">提取时字段原值</p><pre class="pre">${esc(JSON.stringify(r.raw_fields,null,2))}</pre></details>
  </div>`;
  restoreRowDraft(r);loadEvidence(r);
  qsa('[data-register]').forEach(b=>b.onclick=()=>run(()=>registerClarifications(r.id)));
  qsa('[data-edit]').forEach(b=>b.onclick=()=>{const el=$('rowForm').elements[b.dataset.edit];el.focus();el.select()});
  qsa('[data-exclude]').forEach(b=>b.onclick=()=>run(()=>{const draft=rowDrafts.get(draftKey(current.id,r.id));if(draft&&Object.entries(draft.values).some(([f,v])=>f in fieldNames&&v!==r[f]))throw Error('本行字段有未保存修改，请先保存或放弃，再改变排除状态');if(!$('rowForm').elements.reason.value.trim()){$('rowForm').elements.reason.focus();throw Error('请先在“裁定依据”写明排除或恢复的理由')}return saveRow(r,{excluded:!r.excluded,reason:$('rowForm').elements.reason.value})}));
  $('rowForm').onsubmit=e=>{e.preventDefault();run(()=>saveRow(r,Object.fromEntries(new FormData(e.target))))};
}
const evidenceCache=new Map();let evidenceRequest=0;
async function loadEvidence(r){
  const key=current.id+'|'+r.id+'|'+current.revision,fill=data=>{
    $('evidenceNote').className='msg '+(data.integrity_ok?'':'error');
    $('evidenceNote').textContent=data.integrity_ok?'原始文件与已记录字段核验通过；人工更正单独标识，不冒充原文。':'原始证据核验失败：请核查文件或定位，当前证据不能支持批准。';
    for(const [f,v] of Object.entries(data.fields)){const cell=W().querySelector(`[data-ev="${f}"]`);if(!cell)continue;
      cell.innerHTML=(v.inherited_from?`<span class="chip">继承 v${esc(v.inherited_from.row_revision)}</span>`:'')+(v.supported?'<span class="chip tone-ok">原文支持</span>':v.human_role_reviewed?'<span class="chip tone-warn">人工确认归属</span>':`<span class="chip tone-bad" title="${esc((v.reasons||[]).join(' / '))}">语义未核实</span>`)+(v.manual?'<span class="chip tone-warn">人工更正值</span>':'')}
    qsa('[data-ev]').forEach(cell=>{if(!(cell.dataset.ev in data.fields))cell.innerHTML='<span class="hint">—</span>'});
  };
  if(evidenceCache.has(key))return fill(evidenceCache.get(key));
  const ctx=interaction.capture(current),requestId=++evidenceRequest;
  try{const data=await request(`/cases/${ctx.caseId}/evidence/${r.id}`);evidenceCache.set(key,data);if(requestId===evidenceRequest&&interaction.active(ctx,current)&&current.revision===ctx.revision&&focus?.id===r.id&&$('rowForm'))fill(data)}
  catch(e){if(requestId===evidenceRequest&&$('evidenceNote')){$('evidenceNote').className='msg error';$('evidenceNote').textContent='证据核验读取失败：'+e.message}}
}
function restoreRowDraft(r){
  const key=draftKey(current.id,r.id),draft=rowDrafts.get(key),form=$('rowForm');
  if(draft){
    for(const [k,v] of Object.entries(draft.values))if(form.elements[k])form.elements[k].value=v;
    const warning=document.createElement('div');warning.id='draftStatus';warning.className='note '+(draft.revision===current.revision?'warn':'bad');
    warning.textContent=draft.revision===current.revision?'未保存草稿已恢复到编辑区；切换不会丢失，保存前不生效。':'版本冲突：服务器已更新。旧草稿保留供对照，不能直接覆盖；核对后放弃旧草稿再重新编辑。';
    if(draft.revision!==current.revision){const compare=document.createElement('details');const s=document.createElement('summary');s.textContent='对照服务器当前字段（未覆盖草稿）';compare.append(s);const p=document.createElement('p');p.textContent=Object.entries(fieldNames).map(([f,l])=>l+'：'+r[f]).join('；')+'；已保存理由：'+r.resolution;compare.append(p);warning.append(compare)}
    form.prepend(warning);
    const discard=document.createElement('button');discard.type='button';discard.className='btn btn-ghost';discard.textContent='放弃本行草稿';discard.id='discardDraft';
    discard.onclick=()=>{const d=rowDrafts.get(key);if(d)localDrafts.removeIf(current.id,r.id,d.editId);rowDrafts.delete(key);render();renderLocalDraftStatus()};
    form.querySelector('.btn-row').append(discard);
  }
  const submit=form.querySelector('[type=submit]');submit.disabled=interaction.busy(current.id,'row:'+r.id);if(submit.disabled)submit.textContent='保存中…';
  form.oninput=()=>{
    const existing=rowDrafts.get(key),baseValues=existing?.baseValues||rowEditorValues(r);
    const d={revision:existing?.revision??current.revision,rowRevision:existing?.rowRevision??r.revision,priceVersion:existing?.priceVersion??current.price_version,rfq:existing?.rfq??r.rfq,part:existing?.part??r.part,baseValues,values:Object.fromEntries(new FormData(form)),editId:newEditId(),persistedEditId:existing?.persistedEditId||null};
    rowDrafts.set(key,d);persistRowDraft(current.id,r.id,d);
    if(!existing&&queueMode==='rows')renderQueue();
    renderLocalDraftStatus();
  };
}
async function saveRow(r,values){
  const ctx=interaction.capture(current),key=draftKey(ctx.caseId,r.id),draft=rowDrafts.get(key);ctx.rowId=r.id;ctx.revision=draft?.revision??ctx.revision;
  if(ctx.revision!==current.revision||(draft&&(draft.rowRevision!==r.revision||draft.priceVersion!==current.price_version||draft.rfq!==r.rfq||draft.part!==r.part))){notice('旧草稿与当前工作版本冲突，请对照并放弃旧草稿后重新编辑。',true);return}
  const task=interaction.begin(ctx,'row:'+r.id);pendingRowValues.set(key,{taskId:task.taskId,values});
  const button=$('rowForm')?.querySelector('[type=submit]');if(button){button.disabled=true;button.textContent='保存中…'}
  try{
    const c=await request(`/cases/${ctx.caseId}/rows/${r.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ctx.revision,values})});
    RfqInteraction.clearSubmitted(rowDrafts,key,draft);if(draft?.editId)localDrafts.removeIf(ctx.caseId,r.id,draft.editId);renderLocalDraftStatus();
    const continued=rowDrafts.has(key);applyResponse(c,ctx,continued?'已提交的版本已保存；等待中新增输入仍为草稿，请核对新版本。':'裁定已保存；相关批准已由服务端重新核验。');
  }catch(e){
    if(e.status===409){try{const c=await request('/cases/'+ctx.caseId);if(interaction.canApply(ctx,current,c)){show(c);notice('服务器已更新，旧草稿保留。请核对当前版本后重新编辑。',true)}else activity(ctx,'保存冲突，未提交草稿已保留，请打开对应工作单核对',true)}catch(fetchError){activity(ctx,'保存冲突且刷新失败：'+fetchError.message,true);if(interaction.active(ctx,current))notice('保存冲突，草稿保留；刷新失败，请重试打开此工作单。',true)}}
    else if(interaction.active(ctx,current))notice('保存失败，草稿保留：'+e.message,true);else activity(ctx,'保存失败，草稿保留：'+e.message,true);
  }finally{
    if(pendingRowValues.get(key)?.taskId===task.taskId)pendingRowValues.delete(key);interaction.finish(task);
    if(interaction.active(ctx,current)&&focus?.id===r.id){const b=$('rowForm')?.querySelector('[type=submit]');if(b){b.disabled=false;b.textContent='保存裁定'}}
  }
}

/* ---------- price: one row ---------- */
const sameKey=(p,r)=>p.part===r.part&&p.unit===r.unit&&p.condition===r.condition;
const validNow=p=>p.valid_from<=today()&&today()<=p.valid_until;
function priceFields(prefix,lock){
  return `<div class="fields">
    <label>件号<input data-keep="${prefix}part" class="mono" ${lock?`value="${esc(lock.part)}" readonly`:''}></label>
    <label>单位<input data-keep="${prefix}unit" class="mono" ${lock?`value="${esc(lock.unit)}" readonly`:''}></label>
    <label>件状<input data-keep="${prefix}condition" class="mono" ${lock?`value="${esc(lock.condition)}" readonly`:''}></label>
    <label>币种<select data-keep="${prefix}currency"><option>USD</option><option>CNY</option><option>EUR</option></select></label>
    <label>单价<input data-keep="${prefix}amount" inputmode="decimal" class="mono" placeholder="如 13 或 12.35"></label>
    <label>交期<input data-keep="${prefix}lead_time" placeholder="据来源填写"></label>
    <label>生效日期<input data-keep="${prefix}valid_from" type="date" value="${today()}"></label>
    <label>失效日期<input data-keep="${prefix}valid_until" type="date"></label>
    <label>来源类型<select data-keep="${prefix}kind"><option value="">请选择</option><option value="synthetic">合成演示（synthetic）</option><option value="manual">已授权人工核价（manual）</option><option value="authorized">已授权价表（authorized）</option></select></label>
    <label class="span3">来源 / 授权依据<input data-keep="${prefix}source" placeholder="来源文档编号、位置或授权说明"></label>
  </div>`;
}
const priceKeyList=['part','unit','condition','currency','amount','lead_time','valid_from','valid_until','source','kind'];
function readPrice(prefix){
  const p=Object.fromEntries(priceKeyList.map(k=>[k,(W().querySelector(`[data-keep="${prefix}${k}"]`)?.value||'').trim()]));
  const empty=priceKeyList.filter(k=>!p[k]);
  if(empty.length)throw Error('请填齐全部价格依据字段（缺 '+empty.length+' 项）');
  if(!/^\d+(\.\d+)?$/.test(p.amount))throw Error('单价须为非负十进制数字，例如 13 或 12.35');
  if(p.valid_until<p.valid_from)throw Error('失效日期早于生效日期');
  return p;
}
function viewPrice(){
  const r=rowById(focus.id);if(!r)return viewMissing();
  const keyOk=Boolean(r.part&&r.unit&&r.condition),matches=current.prices.filter(p=>sameKey(p,r)),catalogDraft=priceDrafts.has(current.id);
  W().innerHTML=head('核价',label(r),{mono:true,sub:`匹配键 件号 <b class="mono">${missing(r.part,'件号')}</b> + 单位 <b class="mono">${missing(r.unit,'单位')}</b> + 件状 <b class="mono">${missing(r.condition,'件状')}</b> · 数量 <b class="mono">${esc(r.quantity)}</b>`,chip:r.price?'<span class="chip tone-ok">已有唯一有效依据</span>':`<span class="chip tone-price">${esc(rowPriceIssue(r)||'待报价')}</span>`})+
  `<div class="w-body">
    ${r.price?`<p class="note ok">当前依据：<b class="mono">${esc(r.price.currency)} ${esc(r.price.amount)}</b> × ${esc(r.quantity)} = <b class="mono">${esc(r.total)}</b>（金额由服务端按 Decimal 计算）。</p>`:''}
    ${!keyOk?`<p class="note bad">单位或件状缺失，无法按键匹配价格。先在内容核对或澄清中补齐。<button type="button" class="btn btn-sm" data-goto="row|${r.id}">回到内容核对</button></p>`:''}
    <section class="card"><div class="card-head"><h3>同键价源 · ${matches.length} 条</h3><span class="hint">只有一条在有效期内时才可批准</span></div>
      ${matches.length?matches.map(p=>`<div class="psrc ${validNow(p)?'':'expired'}"><b class="mono">${esc(p.currency)} ${esc(p.amount)}</b><span>${esc(p.valid_from)} → ${esc(p.valid_until)} ${validNow(p)?'<span class="chip tone-ok">有效</span>':'<span class="chip tone-bad">不在有效期</span>'}</span><span class="hint">${esc(kindLabel(p.kind))} · ${esc(p.source)}${p.evidence?' · '+esc(p.evidence.file+' / '+p.evidence.location):''}</span></div>`).join(''):'<p class="hint">价表中没有同键价源。</p>'}
      ${matches.filter(validNow).length>1?'<p class="note bad">多条同时有效：请在价格依据总表撤回或调整其中之一。</p>':''}
    </section>
    <section class="card"><div class="card-head"><h3>录入有来源的价格依据</h3><span class="hint">内容变更才形成价表新版本；仅相关批准重新核验</span></div>
      ${catalogDraft?'<p class="note warn">价格依据总表有待保存修改。请先在总表保存或放弃，避免两份价表互相覆盖。</p>':''}
      <fieldset ${!keyOk||catalogDraft?'disabled':''}>${priceFields('p:',r)}</fieldset>
      <p class="msg" id="priceMsg"></p>
      <div class="btn-row"><button type="button" class="btn btn-primary" id="savePrice" ${!keyOk||catalogDraft?'disabled':''}>保存为价表新版本</button>
        <label class="btn file-btn"><span>或导入 CSV / XLSX 价目原件</span><input type="file" accept=".csv,.xlsx" id="priceFileInline"></label>
        <button type="button" class="btn btn-ghost" data-goto="prices|">打开价格依据总表</button></div>
    </section>
  </div>`;
  $('priceFileInline').onchange=e=>run(()=>startPriceImport(e.target));
  $('savePrice').onclick=()=>run(async()=>{
    const p=readPrice('p:'),snap=snapshotKept(W()),done=busyButton($('savePrice'),'保存中…');
    try{if(await change('prices',{prices:[...current.prices,p]},RfqUiState.priceNotice))releaseKept(snap)}finally{done()}
  });
}

/* ---------- price catalog ---------- */
function viewCatalog(){
  const c=current,d=priceDrafts.get(c.id),list=d?d.list:c.prices,stale=d&&d.ctx.revision!==c.revision;
  const cards=list.map((p,i)=>{const mark=d?.marks[i],matches=c.rows.filter(r=>!r.excluded&&sameKey(p,r));return `<div class="pcard${mark?' marked':''}"><div class="pc-key"><b class="mono">${esc(p.part)}</b><span class="mono hint">${esc(p.unit)} · ${esc(p.condition)}</span></div><b class="pc-amt mono">${esc(p.currency)} ${esc(p.amount)}</b><div class="pc-meta">${esc(p.valid_from)} → ${esc(p.valid_until)}${validNow(p)?'':' <span class="chip tone-bad">不在有效期</span>'} · 交期 ${esc(p.lead_time)}<br>${esc(p.source)}${p.evidence?'<br><span class="hint">'+esc(p.evidence.file+' / '+p.evidence.location)+'</span>':''}</div><div class="pc-tags"><span class="chip ${p.kind==='synthetic'?'tone-warn':''}">${esc(kindLabel(p.kind))}</span>${mark?`<span class="chip tone-price">${mark==='new'?'待新增':'待修改'}</span>`:''}${d?'':`<span class="chip">${matches.length?'匹配 '+matches.length+' 行':'未匹配询价行'}</span>`}</div><div class="pc-acts"><button type="button" class="btn btn-sm" data-pedit="${i}">编辑</button><button type="button" class="btn btn-sm btn-ghost" data-pwithdraw="${i}">撤回</button></div></div>`}).join('')+(d?.removed||[]).map(p=>`<div class="pcard removed"><div class="pc-key"><b class="mono">${esc(p.part)}</b><span class="mono hint">${esc(p.unit)} · ${esc(p.condition)}</span></div><b class="pc-amt mono">${esc(p.currency)} ${esc(p.amount)}</b><div class="pc-meta">${esc(p.source)}</div><div class="pc-tags"><span class="chip tone-bad">待撤回</span></div></div>`).join('');
  W().innerHTML=head('价格依据总表',`价表 v${c.price_version}`,{sub:'仅按件号 + 单位 + 件状 + 有效期匹配；同时多条有效会阻止批准。保存新版本后相关旧批准失效。'})+
  `<div class="w-body">
    <div class="btn-row"><label class="btn file-btn"><span>导入 CSV / XLSX 价目原件</span><input id="priceUpload" type="file" accept=".csv,.xlsx"></label><span class="hint">规范合成模板：<a href="templates/synthetic-prices.csv" download>CSV</a> · <a href="templates/synthetic-prices.xlsx" download>XLSX</a></span><button type="button" class="btn btn-ghost" id="loadPrices">加载合成演示价表</button></div>
    ${d?`<div class="draftbar ${stale?'bad':''}"><div><b>待保存价表 · ${d.marks.filter(Boolean).length+d.removed.length} 项修改</b><p class="hint">${stale?`基于工作版本 ${d.ctx.revision}，服务器已到 ${c.revision}，不能直接保存。核对当前价表后放弃，再重新加入（下方填写保留）。`:'尚未生效；保存后形成新价表版本。'}</p></div><div class="btn-row"><button type="button" class="btn btn-primary" id="savePrices" ${stale?'disabled':''}>保存价表新版本</button><button type="button" class="btn btn-ghost" id="discardPrices">放弃待保存修改</button></div></div>`:''}
    <div class="catalog"><div class="plist">${cards||'<p class="empty">当前没有价格依据。没有依据的询价行保持待报价，不能批准。</p>'}</div>
    <section class="card"><div class="card-head"><h3>新增或修改价源</h3></div>
      <label>编辑对象<select data-keep="c:choice" id="priceChoice"><option value="new">新增价源</option>${list.map((p,i)=>`<option value="${i}">修改 #${i+1} ${esc(p.part)} / ${esc(p.unit)} / ${esc(p.condition)} · ${esc(p.currency)} ${esc(p.amount)}</option>`).join('')}</select></label>
      ${priceFields('c:')}
      <p class="msg" id="manualStatus"></p>
      <div class="btn-row"><button type="button" class="btn" id="appendManual">加入待保存价表</button></div>
      <details class="more"><summary>高级：完整价表 JSON</summary><textarea id="priceJson" data-keep="c:json" rows="10" spellcheck="false" class="mono">${esc(JSON.stringify(list,null,2))}</textarea><button type="button" class="btn btn-sm" id="applyPriceJson">以此 JSON 作为待保存价表</button></details>
    </section></div>
  </div>`;
  if(![...$('priceChoice').options].some(o=>o.value===kept.get(keepKey('c:choice'))))kept.delete(keepKey('c:choice'));
  $('priceUpload').onchange=e=>run(()=>startPriceImport(e.target));
  $('loadPrices').onclick=()=>run(async()=>{if(priceDrafts.has(c.id))throw Error('有待保存价表修改，请先保存或放弃');await change('demo-prices',{},(after,before)=>RfqUiState.priceNotice(after,before)+' 本次为明确合成价表，缺价行仍需人工核价。')});
  if(d){$('savePrices').onclick=()=>run(savePrices);$('discardPrices').onclick=()=>{if(confirm('放弃待保存的价表修改？已生效价表不变。')){clearPriceDraft(c.id);render()}}}
  const fill=i=>{const p=list[i];for(const k of priceKeyList)setKeep(W().querySelector(`[data-keep="c:${k}"]`),p[k]??'');$('manualStatus').textContent=p.evidence?'注意：修改后作为新录入价源，不再沿用原价目原件定位，请填写新的来源依据。':''};
  $('priceChoice').onchange=()=>{if($('priceChoice').value!=='new')fill(Number($('priceChoice').value))};
  qsa('[data-pedit]').forEach(b=>b.onclick=()=>{setKeep($('priceChoice'),b.dataset.pedit);fill(Number(b.dataset.pedit));W().querySelector('[data-keep="c:amount"]').focus()});
  qsa('[data-pwithdraw]').forEach(b=>b.onclick=()=>{const d=ensurePriceDraft(),i=Number(b.dataset.pwithdraw),[p]=d.list.splice(i,1),[mark]=d.marks.splice(i,1);if(mark!=='new')d.removed.push(p);d.editVersion++;if(!d.marks.some(Boolean)&&!d.removed.length)clearPriceDraft(c.id);else persistPriceDraft(c.id,d);kept.delete(keepKey('c:choice'));render();notice('已加入待撤回；保存价表新版本后相关旧批准失效。')});
  $('appendManual').onclick=()=>run(()=>{
    const p=readPrice('c:'),d=ensurePriceDraft(),choice=$('priceChoice').value;
    if(choice==='new'){d.list.push(p);d.marks.push('new')}else{const i=Number(choice);d.list[i]=p;d.marks[i]=d.marks[i]==='new'?'new':'edit'}
    d.editVersion++;persistPriceDraft(current.id,d);render();notice('已加入待保存价表；点击“保存价表新版本”后才生效。');
  });
  $('applyPriceJson').onclick=()=>run(()=>{let list;try{list=JSON.parse($('priceJson').value)}catch{throw Error('JSON 格式错误，未改变待保存价表')}if(!Array.isArray(list))throw Error('完整价表须为数组');const d=ensurePriceDraft();d.list=list;d.marks=list.map(()=>'edit');d.removed=[];d.editVersion++;persistPriceDraft(current.id,d);render();notice('已用 JSON 替换待保存价表；保存后由服务端校验。')});
}
const priceDraftKey=id=>id+'|prices:|p:catalog';
function persistPriceDraft(id,d){kept.set(priceDraftKey(id),JSON.stringify({revision:d.ctx.revision,priceVersion:d.priceVersion,list:d.list,marks:d.marks,removed:d.removed,editVersion:d.editVersion}))}
function clearPriceDraft(id){priceDrafts.delete(id);kept.delete(priceDraftKey(id))}
function restorePriceDraft(c){
  if(priceDrafts.has(c.id))return;
  const raw=kept.get(priceDraftKey(c.id));if(!raw)return;
  try{const d=JSON.parse(raw);if(!Number.isSafeInteger(d.revision)||d.revision<1||!Number.isSafeInteger(d.priceVersion)||!Number.isSafeInteger(d.editVersion)||!Array.isArray(d.list)||!Array.isArray(d.marks)||!Array.isArray(d.removed)||d.list.length!==d.marks.length)throw Error();priceDrafts.set(c.id,{...d,ctx:{...interaction.capture(c),revision:d.revision}})}catch{kept.error='价表草稿暂存不兼容，未恢复；请核对当前价表并重新填写'}
}
function ensurePriceDraft(){let d=priceDrafts.get(current.id);if(!d){d={ctx:interaction.capture(current),priceVersion:current.price_version,list:structuredClone(current.prices),marks:current.prices.map(()=>null),removed:[],editVersion:0};priceDrafts.set(current.id,d)}return d}
async function savePrices(){
  const owner=priceDrafts.get(current.id);if(!owner)return;const editVersion=owner.editVersion;
  // A draft keeps its business base, not an obsolete navigation epoch. Capture
  // ownership for this explicit click; change() still rejects a later switch.
  const ctx=interaction.capture(current);
  if(owner.ctx.caseId!==ctx.caseId||owner.ctx.revision!==ctx.revision)throw Error('待保存价表基于旧工作版本，不能覆盖当前价表；请放弃后重新加入');
  const done=busyButton($('savePrices'),'保存中…');
  try{const applied=await change('prices',{prices:owner.list},RfqUiState.priceNotice,ctx);
    if(applied&&priceDrafts.get(owner.ctx.caseId)===owner){if(owner.editVersion===editVersion)clearPriceDraft(owner.ctx.caseId);else{persistPriceDraft(owner.ctx.caseId,owner);notice('已提交价表已处理；等待期间新增修改仍保留为草稿，请核对当前版本后再保存。',true)}}
  }finally{done();if(current?.id===owner.ctx.caseId)render()}
}
let intake=null,pricePreviewRequest=0;
async function startPriceImport(input){
  const f=input.files[0];if(!f)return;
  const ctx=interaction.capture(current),requestId=++pricePreviewRequest,data=new FormData();data.append('revision',ctx.revision);data.append('file',f);let result;
  try{result=await request(`/cases/${ctx.caseId}/prices/import/preview`,{method:'POST',body:data})}catch(e){input.value='';if(interaction.active(ctx,current)&&requestId===pricePreviewRequest)throw e;activity(ctx,'价目预览失败：'+e.message,true);return}
  input.value='';
  if(!interaction.active(ctx,current)||current.revision!==ctx.revision||requestId!==pricePreviewRequest){activity(ctx,'价目预览已生成但未应用到当前页面，请回原工作单重新选择原件审阅');return}
  intake={...result,ctx,editVersion:0};$('importMode').value='append';$('importReplaceConfirm').checked=false;
  $('importSummary').textContent=`${intake.filename} · ${intake.rows.length} 行 · ${intake.errors.length} 项错误。预览尚未改变价目；确认接纳后才生效。`;
  $('importRows').innerHTML=intake.rows.map(r=>`<tr><td class="mono">${esc(r.location)}</td><td class="mono">${esc(r.price.part)} / ${esc(r.price.unit)} / ${esc(r.price.condition)}</td><td class="mono">${esc(r.price.amount)} ${esc(r.price.currency)}</td><td>${esc(r.price.valid_from)} 至 ${esc(r.price.valid_until)}<br><small>${esc(r.price.source)}</small></td><td>${r.errors.length?`<span class="msg error">${r.errors.map(esc).join('<br>')}</span>`:'字段有效；请核对授权及生效范围'}</td></tr>`).join('');
  $('acceptPrices').disabled=Boolean(intake.errors.length);$('importError').textContent=intake.errors.length?intake.errors.join('；'):'';$('priceImport').showModal();
}
$('priceImport').addEventListener('input',()=>{if(intake)intake.editVersion++});
$('cancelImport').onclick=$('cancelImportX').onclick=()=>$('priceImport').close();
$('acceptPrices').onclick=async()=>{
  const owner=intake,editVersion=owner.editVersion;
  try{
    if(priceDrafts.has(owner.ctx.caseId))throw Error('价格依据总表有待保存修改，请先保存或放弃，再接纳价目原件');
    if($('importMode').value==='replace'&&!$('importReplaceConfirm').checked)throw Error('请勾选明确替换全部价目的确认');
    if(await change('prices/import/accept',{preview_id:owner.id,mode:$('importMode').value,actor:$('importActor').value,reason:$('importReason').value},'价目原件已审阅接纳；来源按表/行绑定，相关批准重新核验。',owner.ctx)&&intake===owner){if(owner.editVersion===editVersion)$('priceImport').close();else notice('已提交的价目审阅已完成；等待期间新增填写未保存，请核对新版本。')}
  }catch(e){if(owner===intake&&interaction.active(owner.ctx,current))$('importError').textContent=e.message;else activity(owner.ctx,'价目接纳失败：'+e.message,true)}
};

/* ---------- clarification timeline ---------- */
async function registerClarifications(rowId){const ctx=interaction.capture(current);const applied=await change('clarifications/register',{row_id:rowId},(after)=>after.revision===ctx.revision?'本行没有新增澄清问题；版本与已有记录未改变。':'仅已登记本行待确认项；其他询价行未登记，尚未发送或解决。',ctx);if(applied&&interaction.active(ctx,current)&&focus?.type==='row'&&focus.id===rowId){const q=(current.clarifications||[]).find(q=>q.row_id===rowId&&openQuestion(q));if(q)setFocus('q',q.id)}}
async function downloadDraft(){
  const ctx=interaction.capture(current),result=await request(`/cases/${ctx.caseId}/draft`);
  if(!interaction.active(ctx,current)||current.revision!==ctx.revision||result.revision!==ctx.revision){activity(ctx,'草稿版本变化，请回对应工作单重新下载');return}
  download(new Blob([result.text],{type:'text/plain;charset=utf-8'}),`clarification-${ctx.caseId}-r${ctx.revision}.txt`);notice('已下载本地澄清草稿；没有发送邮件，问题状态未改变。','ok');
}
async function previewDraft(){const ctx=interaction.capture(current),result=await request(`/cases/${ctx.caseId}/draft`);if(!interaction.active(ctx,current)||current.revision!==ctx.revision)return;$('previewText').textContent=result.text;$('preview').showModal()}
$('closePreview').onclick=()=>$('preview').close();
async function appendOriginal(input){
  const file=input.files[0];if(!file)return;const ctx=interaction.capture(current),task=interaction.begin(ctx,'appendMaterial'),data=new FormData();data.append('revision',ctx.revision);data.append('file',file);
  try{const c=await request(`/cases/${ctx.caseId}/materials`,{method:'POST',body:data});applyResponse(c,ctx,`原件 ${file.name} 已追加，正式行未改变。`)}
  catch(e){if(interaction.active(ctx,current))throw e;activity(ctx,'追加原件失败：'+e.message,true)}finally{input.value='';interaction.finish(task)}
}
async function proposeCandidates(mode){
  const consent=mode==='model'&&modelState.requests_enabled&&confirm('将把本工作单原件的文字发送给模型服务，提取结果仍需你逐条核对。不要发送不能外传的材料。继续吗？');
  if(mode==='model'&&modelState.requests_enabled&&!consent)return;
  const ctx=interaction.capture(current),task=interaction.begin(ctx,'propose');
  try{const response=await request(`/cases/${ctx.caseId}/candidates/propose`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:ctx.revision,values:{mode,remote_consent:consent}})});
    const x=response.extraction;applyResponse(response.case,ctx,`候选状态：${x.status}；模型请求 ${x.requests||0} 次。${x.rejected_candidates?`另有 ${x.rejected_candidates} 条因缺件号或不合规被忽略。`:''}${x.dropped_fields?`${x.dropped_fields} 个字段的值不在原文中，已丢弃。`:''}正式行尚未改变，需逐条审阅。`)}
  catch(e){if(interaction.active(ctx,current))throw e;activity(ctx,'候选提取失败：'+e.message,true)}finally{interaction.finish(task);if(mode==='model')await refreshModelState()}
}
function step(n,state,title,body){return `<li class="step ${state}"><span class="step-n">${state==='done'?'✓':n}</span><div class="step-body"><h3>${title}</h3>${body}</div></li>`}
function viewQuestion(){
  const q=current.clarifications.find(q=>q.id===focus.id);if(!q)return viewMissing();
  const row=rowById(q.row_id),closed=['resolved','superseded'].includes(q.state),field=fieldNames[q.field]||q.field;
  const fileNames=materials.caseId===current.id?materials.files.map(f=>f.file):[];
  const linked=new Set(q.replies.map(r=>r.filename)),unlinked=fileNames.filter(f=>!linked.has(f));
  const fresh=(current.candidate_batches||[]).filter(b=>b.expected_revision===current.revision);
  const replyBlocks=q.replies.map(reply=>{
    const old=reply.outdated||reply.row_revision!==row?.revision&&!reply.applications.length;
    const cands=fresh.flatMap(b=>b.candidates.filter(c=>c.status==='pending'&&Object.values(c.field_sources).every(s=>s.file===reply.filename&&s.sha256===reply.sha256)).map(c=>({b,c})));
    return {reply,old,cands,pending:!old&&!reply.applications.length};
  });
  const pendingReplies=replyBlocks.filter(x=>x.pending);
  const candHtml=({b,c},reply)=>{
    const answer=c.fields[q.field],src=c.field_sources[q.field],k=`k:${c.id}:`,confirmField=['unit','condition'].includes(q.field);
    return `<div class="cand-review" data-cand="${b.id}:${c.id}" data-reply="${reply.id}">
      <div class="diff"><div><span class="hint">当前${field}</span><b class="mono">${row?.[q.field]?esc(row[q.field]):'<i class="missing">空</i>'}</b></div><span class="arrow">→</span><div><span class="hint">答复中的${field}</span><b class="mono">${answer?esc(answer):'<i class="missing">未回答</i>'}</b></div></div>
      <p class="hint">${src?`出处 ${esc(src.file)} · ${esc(src.location)} ·「<span class="mono">${esc(src.quote)}</span>」`:'答复没有提供此字段的原文引用。'}只回填此字段，其他字段继承原值与出处。</p>
      ${answer?'':`<p class="note bad">答复没有回答${field}，不能回填，问题保持未解决。可拒绝此候选并继续等待答复。</p>`}
      <div class="fields two"><label>核对人<input data-keep="${k}actor"></label><label>依据<input data-keep="${k}reason" placeholder="核对了哪份答复、哪一行"></label></div>
      <div class="checks"><label><input type="checkbox" data-keep="${k}assoc">已核对答复属于同一询价 ${esc(q.rfq)} / ${esc(q.part)}，并确认采用此值</label>${confirmField?`<label><input type="checkbox" data-keep="${k}confirm">已确认${field}原值（未知缩写不释义）</label>`:''}<label><input type="checkbox" data-keep="${k}resolve">已核对实际字段变化，同时解决此澄清</label></div>
      <p class="msg error" data-cand-error></p>
      <div class="btn-row"><button type="button" class="btn btn-primary" data-cand-accept ${answer?'':'disabled'}>接纳并回填${field}</button><button type="button" class="btn" data-cand-reject>拒绝此候选</button></div>
    </div>`;
  };
  const s3=q.replies.length?'done':closed?'skip':'current';
  const s4=closed?'done':pendingReplies.length?'current':'wait';
  W().innerHTML=head('澄清 · '+esc(q.id),`<span class="mono">${esc(q.rfq||'缺询价号')} / ${esc(q.part||'缺件号')}</span> · ${esc(field)}`,{sub:esc(q.question),chip:`<span class="chip tone-${clarificationTone[q.state]}">${esc(RfqUiState.questionLabel(q))}</span>`})+
  `<div class="w-body"><p class="note">系统不发送邮件。<b>下载草稿或收到答复都不等于解决</b>；只有核对后回填并明确解决，或核实人工裁定后结束，这项才放行。</p>
  <ol class="timeline">
    ${step(1,'done','已登记问题',`<p>开始时原值「<span class="mono">${esc(q.basis.value)||'空'}</span>」· 工作版本 ${q.start_revision} / 行版本 ${q.start_row_revision} · 当前行版本 ${row?.revision??'缺失'}</p><p class="hint">${q.sources.map(s=>esc(s.file+' / '+s.location)).join('；')}</p><button type="button" class="btn btn-sm btn-ghost" data-goto="row|${q.row_id}">查看原询价行</button>`)}
    ${step(2,closed||q.replies.length?'done':'info','发出澄清（由你在系统外发送）',`<p class="hint">草稿汇总本单全部待答问题；下载不改变状态。</p><div class="btn-row"><button type="button" class="btn btn-sm" id="dlDraft">下载澄清草稿 TXT</button><button type="button" class="btn btn-sm btn-ghost" id="pvDraft">预览</button></div>`)}
    ${step(3,s3,'登记答复原件',`${replyBlocks.length?`<ul class="replies">${replyBlocks.map(({reply,old})=>`<li><b>${esc(reply.filename)}</b> <span class="chip ${old?'tone-off':reply.applications.length?'tone-ok':'tone-warn'}">${old?'旧版本，仅保留记录':esc(RfqUiState.replyLabel(reply))}</span><small class="hint"> 针对行版本 ${reply.row_revision} · ${esc(reply.received_at)} · ${esc(reply.actor)}：${esc(reply.reason)}</small>${(reply.reviews||[]).length?`<details><summary>审阅记录（不代表澄清已解决）</summary>${reply.reviews.map(r=>`<p class="hint">${esc(r.time)} · ${esc(r.actor)} · ${esc(RfqUiState.replyLabel({review_status:r.status}))}：${esc(r.reason)}</p>`).join('')}</details>`:''}</li>`).join('')}</ul>`:''}
      ${closed?'':`<div class="sub-card"><p class="hint">先把答复文件追加到本工作单，再登记为本问题的答复。登记只记录收到，不改字段、不解决。</p>
        <div class="btn-row"><label class="btn btn-sm file-btn"><span>追加答复原件</span><input type="file" accept=".txt,.eml,.pdf" id="replyUpload"></label></div>
        <div class="fields two"><label>答复原件<select data-keep="r:file" id="replyFile">${unlinked.length?unlinked.map(f=>`<option value="${esc(f)}">${esc(f)}</option>`).join(''):'<option value="">（没有未登记的原件，请先追加）</option>'}</select></label><label>答复针对行版本<input data-keep="r:rev" type="number" min="1" step="1" value="${row?.revision||q.start_row_revision}"></label><label>核对人<input data-keep="r:actor"></label><label>依据<input data-keep="r:reason" placeholder="核对了文件名、询价号、件号与行版本"></label></div>
        <p class="msg error" id="replyError"></p><button type="button" class="btn btn-sm" id="saveReply" ${unlinked.length?'':'disabled'}>登记为本问题的答复</button></div>`}`)}
    ${step(4,s4,'核对答复并回填',closed?'<p class="hint">本项已结束。</p>':pendingReplies.length?pendingReplies.map(x=>`<div class="sub-card"><p><b>${esc(x.reply.filename)}</b></p>${x.cands.length?x.cands.map(c=>candHtml(c,x.reply)).join(''):['no_answer','reviewed_rejected'].includes(x.reply.review_status)?`<p class="note warn">${esc(RfqUiState.replyLabel(x.reply))}。正式行未因此改变，问题仍未解决。请追加能明确回答${esc(field)}的新答复，或依据其他书面材料人工裁定。</p><details><summary>需要重新核对同份答复？</summary><p class="hint">新候选须重新审阅，历史结论仍保留，不会自动解决。</p><button type="button" class="btn btn-sm" data-propose>重新生成离线标签候选</button></details>`:`<p class="hint">尚无当前版本可审阅候选。离线规则只识别“Unit: EA”这类冒号标签，自然语言须人工核对。</p><button type="button" class="btn btn-sm" data-propose>从答复生成离线标签候选</button>`}</div>`).join(''):'<p class="hint">登记答复后在这里逐项核对。</p>')}
    ${step(5,closed?'done':'wait','结论',closed?q.resolutions.map(r=>`<p>${esc(r.time)} · ${esc(r.method)} · ${esc(r.actor)}：${esc(r.reason)} · 行版本 ${r.row_revision}</p>`).join('')+(q.supersession?`<p>原目标结束依据：${esc(q.supersession.actor)} / ${esc(q.supersession.reason)}</p>`:''):`<p class="hint">如果已在询价行依据其他书面材料人工裁定，可核实后直接结束本项。</p><div class="fields two"><label>核对人<input data-keep="m:actor"></label><label>核实依据<input data-keep="m:reason"></label></div><p class="msg error" id="manualError"></p><button type="button" class="btn btn-sm btn-ghost" id="manualResolve">核实人工裁定并解决</button>`)}
  </ol></div>`;
  $('dlDraft').onclick=()=>run(downloadDraft);$('pvDraft').onclick=()=>run(previewDraft);
  if($('replyUpload'))$('replyUpload').onchange=e=>run(async()=>{const name=e.target.files[0]?.name;await appendOriginal(e.target);if(name&&focus?.id===q.id){kept.set(keepKey('r:file'),name);await refreshMaterials(current);renderWork()}});
  if($('saveReply'))$('saveReply').onclick=()=>run(async()=>{
    const snap=snapshotKept(W()),val=k=>W().querySelector(`[data-keep="${k}"]`).value,done=busyButton($('saveReply'),'登记中…');$('replyError').textContent='';
    try{if(await change(`clarifications/${q.id}/replies`,{filename:val('r:file'),reply_row_revision:Number(val('r:rev')),actor:val('r:actor'),reason:val('r:reason')},'答复已登记，尚未回填或解决；请核对答复。'))releaseKept(snap)}
    catch(e){if($('replyError'))$('replyError').textContent=e.message;else throw e}finally{done()}
  });
  qsa('[data-propose]').forEach(b=>b.onclick=()=>run(()=>proposeCandidates('offline')));
  qsa('.cand-review').forEach(box=>{
    const [bid,cid]=box.dataset.cand.split(':'),reply=q.replies.find(r=>r.id===box.dataset.reply),k=`k:${cid}:`;
    const v=n=>box.querySelector(`[data-keep="${k}${n}"]`),err=box.querySelector('[data-cand-error]');
    const submit=action=>run(async()=>{
      const snap=snapshotKept(box),c=current.candidate_batches.find(b=>b.id===bid).candidates.find(x=>x.id===cid);
      const values={action,mode:'partial',fields:action==='accept'?{[q.field]:c.fields[q.field]}:{},actor:v('actor').value,reason:v('reason').value,target_row_id:q.row_id,confirm_association:v('assoc').checked,confirm_reassignment:false,confirmed_fields:v('confirm')?.checked?[q.field]:[],clarification_id:q.id,reply_id:reply.id,resolve_clarification:v('resolve').checked,base_revision:current.revision,base_row_revision:row?.revision,update_fields:action==='accept'?[q.field]:[],clear_fields:[],clear_reason:''};
      err.textContent='';const done=busyButton(box.querySelector(action==='accept'?'[data-cand-accept]':'[data-cand-reject]'),'提交中…');
      try{if(await change(`candidates/${bid}/${cid}/review`,values,action==='accept'?`已回填${field}${values.resolve_clarification?'并解决此澄清':'；澄清尚未解决'}。`:'候选已拒绝，正式行未改变，问题保持未解决。'))releaseKept(snap)}
      catch(e){if(err.isConnected)err.textContent=e.message;else throw e}finally{done()}
    });
    box.querySelector('[data-cand-accept]').onclick=()=>submit('accept');
    box.querySelector('[data-cand-reject]').onclick=()=>{if(!v('reason').value.trim()){err.textContent='请在“依据”写明拒绝理由';v('reason').focus();return}submit('reject')};
  });
  if($('manualResolve'))$('manualResolve').onclick=()=>run(async()=>{
    const reassigned=row&&['rfq','part'].some(f=>f!==q.field&&row[f]!==q[f]),snap=snapshotKept(W()),val=k=>W().querySelector(`[data-keep="${k}"]`).value;$('manualError').textContent='';
    if(reassigned&&!confirm('询价号或件号已变化：将核实重新归属并结束旧目标项，继续？'))return;
    try{if(await change(`clarifications/${q.id}/resolve`,{method:reassigned?'superseded':'manual',base_row_revision:row?.revision,actor:val('m:actor'),reason:val('m:reason')},'已记录人工核实结论。'))releaseKept(snap)}
    catch(e){if($('manualError'))$('manualError').textContent=e.message;else throw e}
  });
}
function viewClarifications(){
  const list=current.clarifications||[],open=list.filter(openQuestion);
  W().innerHTML=head('澄清总览',`${list.length} 项 · ${open.length} 项未解决`,{sub:'登记 → 下载草稿 → 追加并登记答复 → 核对回填 → 明确解决。系统不发送邮件。'})+
  `<div class="w-body"><div class="btn-row"><button type="button" class="btn" id="regAll">登记当前待确认项</button><button type="button" class="btn" id="dlDraft">下载澄清草稿 TXT</button><button type="button" class="btn btn-ghost" id="pvDraft">预览草稿</button><label class="btn file-btn"><span>追加答复原件</span><input type="file" accept=".txt,.eml,.pdf" id="replyUploadAll"></label><button type="button" class="btn" id="proposeAll">生成离线标签候选</button></div>
  <div class="qgrid">${list.map(q=>`<button type="button" class="qcard tone-${clarificationTone[q.state]}" data-goto="q|${q.id}"><span class="chip tone-${clarificationTone[q.state]}">${esc(RfqUiState.questionLabel(q))}</span><b class="mono">${esc(q.rfq||'缺询价号')} / ${esc(q.part||'缺件号')}</b><span>${esc(fieldNames[q.field]||'重复归属')} · ${esc(q.question)}</span><small class="hint mono">${esc(q.id)} · 答复 ${q.replies.length}</small></button>`).join('')||'<p class="empty">尚无澄清记录。先在询价行登记缺字段、冲突或待确认项。</p>'}</div></div>`;
  $('regAll').onclick=()=>run(()=>change('clarifications/register',{},'已登记当前待确认项；尚未发送，也未解决。'));
  $('dlDraft').onclick=()=>run(downloadDraft);$('pvDraft').onclick=()=>run(previewDraft);
  $('replyUploadAll').onchange=e=>run(()=>appendOriginal(e.target));$('proposeAll').onclick=()=>run(()=>proposeCandidates('offline'));
}

/* ---------- general candidate review ---------- */
function viewCandidate(){
  const [bid,cid]=focus.id.split(':'),b=(current.candidate_batches||[]).find(b=>b.id===bid),c=b?.candidates.find(x=>x.id===cid);if(!c)return viewMissing();
  const fresh=b.expected_revision===current.revision&&c.status==='pending';
  const mode=kept.get(keepKey('mode'))||'full',target=kept.get(keepKey('target'))??'',base=current.rows.find(r=>r.id===target),partial=mode==='partial';
  const fields=Object.entries(fieldNames).map(([f,l])=>{const op=kept.get(keepKey('op:'+f))||'inherit',enabled=!partial||op==='update',src=c.field_sources[f];return `<div class="cf"><label>${l}${partial?`<select data-keep="op:${f}" data-op="${f}" ${['rfq','part'].includes(f)?'disabled':''}><option value="inherit">继承基础值</option>${f in c.fields&&!['rfq','part'].includes(f)?'<option value="update">更新本次值</option>':''}${!['rfq','part'].includes(f)?'<option value="clear">明确清空</option>':''}</select>`:''}<input data-keep="f:${f}" data-field="${f}" value="${esc(c.fields[f]||'')}" class="mono" ${enabled?'':'disabled'}></label>${partial?`<small>基础「<span class="mono">${esc(base?.[f]??'请选择目标行')}</span>」</small>`:''}<small>${src?`<button type="button" class="src-link" data-srcfield="${f}">${esc(src.file)} · ${esc(src.location)}</button>「<span class="mono">${esc(src.quote)}</span>」`:'没有本次引用'}</small></div>`}).join('');
  W().innerHTML=head('修订候选 · '+esc(engineName(b.engine)),label({rfq:c.fields.rfq,part:c.fields.part}),{mono:true,sub:`候选不是正式询价，原文片段只证明文字存在，业务归属和修订关系须人工核对。`,chip:`<span class="chip ${fresh?'tone-price':'tone-off'}">${fresh?'待审阅':c.status!=='pending'?c.status:'旧批次，须重新生成'}</span>`})+
  `<div class="w-body">${fresh?'':'<p class="note bad">此候选不能再接纳：已处理或工作版本已变化，请重新生成候选。</p>'}
  <fieldset class="card" ${fresh?'':'disabled'}>
    <div class="fields two"><label>操作<select data-keep="mode" id="candMode"><option value="full">整行新建 / 替换（原语义）</option><option value="partial">局部修订（逐字段选择）</option></select></label><label>目标正式行<select data-keep="target" id="candTarget"><option value="">新增正式行</option>${current.rows.map(r=>`<option value="${r.id}">${esc(r.rfq)} / ${esc(r.part)} / 数量 ${esc(r.quantity)} / 行版本 ${r.revision}</option>`).join('')}</select></label></div>
    <p class="hint">${partial?'未选字段继承所选基础行及其原出处。更新须有本次引用；清空须单独理由。询价号与件号必须一致。':'整行替换保留原语义：候选未提供的字段默认为空。'}</p>
    <div class="cfields">${fields}</div>
    <div class="fields two"><label>明确清空理由（仅清空时必填）<input data-keep="clear"></label><label>核对人<input data-keep="actor"></label><label class="span2">裁定理由<textarea data-keep="reason" rows="2"></textarea></label></div>
    <div class="checks"><label><input type="checkbox" data-keep="assoc">已核对字段属于同一询价，并确认本次采用的修订</label><label><input type="checkbox" data-keep="reassign">若替换不同询价/件号，确认重新归属</label><label><input type="checkbox" data-keep="cunit">已确认单位原值（未知缩写不释义）</label><label><input type="checkbox" data-keep="ccond">已确认件状原值（未知缩写不释义）</label></div>
    <p class="msg error" id="candError"></p>
    <div class="btn-row"><button type="button" class="btn btn-primary" id="candAccept">显式接纳为正式行</button><button type="button" class="btn" id="candAcceptBatch">接纳本批所有无争议候选</button><button type="button" class="btn" id="candReject">拒绝候选</button></div>
  </fieldset></div>`;
  const rerender=()=>renderWork();$('candMode').onchange=$('candTarget').onchange=rerender;qsa('[data-op]').forEach(s=>s.onchange=rerender);
  const val=k=>W().querySelector(`[data-keep="${k}"]`),submit=action=>run(async()=>{
    const snap=snapshotKept(W()),m=val('mode').value,tgt=val('target').value,baseRow=current.rows.find(r=>r.id===tgt),ops=qsa('[data-op]');
    const values={action,mode:m,fields:Object.fromEntries(qsa('[data-field]').filter(e=>!e.disabled).map(e=>[e.dataset.field,e.value])),actor:val('actor').value,reason:val('reason').value,target_row_id:tgt,confirm_association:val('assoc').checked,confirm_reassignment:val('reassign').checked,confirmed_fields:[val('cunit').checked?'unit':null,val('ccond').checked?'condition':null].filter(Boolean)};
    if(m==='partial')Object.assign(values,{base_revision:current.revision,base_row_revision:baseRow?.revision,update_fields:ops.filter(e=>e.value==='update').map(e=>e.dataset.op),clear_fields:ops.filter(e=>e.value==='clear').map(e=>e.dataset.op),clear_reason:val('clear').value});
    $('candError').textContent='';
    try{if(await change(`candidates/${bid}/${cid}/review`,values,action==='accept'?'已显式接纳；请核查受影响批准、继承出处与价源。':'候选已拒绝，正式行未改变。'))releaseKept(snap)}
    catch(e){if($('candError'))$('candError').textContent=e.message;else throw e}
  });
  $('candAccept').onclick=()=>submit('accept');
  $('candAcceptBatch').onclick=()=>run(async()=>{
    const snap=snapshotKept(W());$('candError').textContent='';
    try{if(await change(`candidates/${bid}/accept-batch`,{actor:val('actor').value,reason:val('reason').value,confirm_association:val('assoc').checked},'已接纳无争议候选；同一行有多个值或数量待修正的，仍需逐条处理。'))releaseKept(snap)}
    catch(e){if($('candError'))$('candError').textContent=e.message;else throw e}
  });
  $('candReject').onclick=()=>{if(!val('reason').value.trim()){$('candError').textContent='请在“裁定理由”写明拒绝理由';return}submit('reject')};
}

/* ---------- materials ---------- */
function viewMaterials(){
  const batches=(current.candidate_batches||[]).slice().reverse(),files=materials.caseId===current.id?materials.files:[];
  W().innerHTML=head('原件与修订候选',`${files.length} 份原件 · ${batches.length} 个候选批次`,{sub:modelState.requests_enabled?'模型只提出候选：每个值都引用原文，由你逐条核对后才进入正式行。':'追加的修订原件不会自动生效；离线标签规则不代表真实模型。'})+
  `<div class="w-body"><div class="btn-row"><label class="btn file-btn"><span>追加修订原件（不自动生效）</span><input id="appendMaterial" type="file" accept=".txt,.eml,.pdf"></label><button type="button" class="btn" id="offlineCandidates">生成离线标签候选</button><button type="button" class="btn btn-ghost" id="modelCandidates">检查模型提取配置</button></div>
  <section class="card"><div class="card-head"><h3>原件</h3><span class="hint">在右侧原件栏逐行查看</span></div>${files.map(f=>`<button type="button" class="link-row" data-openfile="${esc(f.file)}"><b>${esc(f.file)}</b> <small class="hint">${f.units.length} 段 · SHA-256 ${esc(f.sha256.slice(0,12))}…</small></button>`).join('')||'<p class="hint">读取中或没有原件。</p>'}</section>
  <section class="card"><div class="card-head"><h3>候选批次</h3></div>${batches.map(b=>{const fresh=b.expected_revision===current.revision;return `<div class="batch"><p><span class="chip ${fresh?'tone-ready':'tone-off'}">${fresh?'当前版本':'旧批次，须重新生成'}</span> ${esc(engineName(b.engine))}</p>${b.candidates.map(x=>`<button type="button" class="link-row" data-goto="cand|${b.id}:${x.id}"><b class="mono">${esc(x.fields.rfq||'缺询价号')} / ${esc(x.fields.part||'缺件号')}</b> <small>数量 ${esc(x.fields.quantity||'缺')} · ${x.status==='pending'?'待审阅':esc(x.status)}</small></button>`).join('')||'<p class="hint">本批没有候选。</p>'}</div>`}).join('')||'<p class="hint">尚无候选批次。</p>'}</section></div>`;
  $('appendMaterial').onchange=e=>run(()=>appendOriginal(e.target));
  $('modelCandidates').textContent=modelState.requests_enabled?'让模型提取询价行':'检查模型提取配置';
  $('offlineCandidates').onclick=()=>run(()=>proposeCandidates('offline'));$('modelCandidates').onclick=()=>run(()=>proposeCandidates('model'));
  qsa('[data-openfile]').forEach(b=>b.onclick=()=>{srcFile=b.dataset.openfile;renderSource();if(narrow())setView('source');else if(innerWidth<=1280)openSource()});
}

/* ---------- warnings ---------- */
function viewWarnings(){
  const c=current;
  W().innerHTML=head('解析警告',`${c.warnings.length} 项`,{sub:'对照右侧原件确认没有遗漏后记录结论；未记录前不能批准。',chip:c.review_note?'<span class="chip tone-ok">已记录核查</span>':'<span class="chip tone-bad">未核查</span>'})+
  `<div class="w-body"><ul class="warn-list">${c.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>${modelState.requests_enabled?'<div class="btn-row"><button type="button" class="btn btn-primary" id="warnModel">让模型提取询价行</button></div>':''}<section class="card"><label>人工核查结论<textarea data-keep="note" rows="3" placeholder="例如：已逐行对照附件第1页，未发现遗漏">${esc(c.review_note||'')}</textarea></label><p class="msg error" id="noteError"></p><button type="button" class="btn btn-primary" id="review">记录人工核查</button></section></div>`;
  if(modelState.requests_enabled)$('warnModel').onclick=()=>run(()=>proposeCandidates('model'));
  $('review').onclick=()=>run(async()=>{const snap=snapshotKept(W());try{if(await change('review',{note:W().querySelector('[data-keep="note"]').value},'已记录解析警告核查说明。'))releaseKept(snap)}catch(e){$('noteError').textContent=e.message}});
}

/* ---------- approval & output ---------- */
function viewApprove(){
  const c=current,s=summarize(c),blocked=!s.active.length||s.issues.length>0||s.needsReview||s.dirty>0||priceDrafts.has(c.id);
  const checks=[
    [!s.content.length&&!s.needsReview,'内容核对',s.content.length?`${s.content.length} 行待核对`:s.needsReview?'解析警告未核查':'通过','content'],
    [!s.openQs.length,'澄清',(c.clarifications||[]).length?(s.openQs.length?`${s.openQs.length} 项未解决`:'全部结束'):'未登记','clarify'],
    [!s.priced.length,'唯一有效价格依据',s.priced.length?`${s.priced.length} 行缺少或有多个有效价源`:'全部具备','price'],
    [!s.dirty&&!priceDrafts.has(c.id),'本页未保存修改',s.dirty||priceDrafts.has(c.id)?`${s.dirty} 份行草稿${priceDrafts.has(c.id)?' · 价表待保存':''}，批准前先保存或放弃`:'无',''],
  ];
  W().innerHTML=head('批准',s.ready?'当前版本已批准':s.stale.length?`${s.stale.length} 行旧批准已失效`:'批准当前版本',{sub:`批准绑定：工作版本 <b class="mono">${c.revision}</b> · 价表 <b class="mono">v${c.price_version}</b> · 当前输入、价源与澄清状态。之后任何变化都会使批准失效。`})+
  `<div class="w-body"><ul class="checks-list">${checks.map(([ok,l,t,g])=>`<li class="${ok?'ok':'bad'}"><span class="tick">${ok?'✓':'!'}</span><b>${l}</b><span>${esc(t)}</span>${!ok&&g?`<button type="button" class="btn btn-sm btn-ghost" data-gate-jump="${g}">处理</button>`:''}</li>`).join('')}</ul>
  <div class="table-wrap"><table class="grid"><thead><tr><th>询价号</th><th>件号</th><th>数量</th><th>件状</th><th>单价</th><th>小计</th><th>价源</th><th>批准</th></tr></thead><tbody>${s.active.map(r=>`<tr><td class="mono">${missing(r.rfq,'询价号')}</td><td class="mono">${missing(r.part,'件号')}</td><td class="mono">${esc(r.quantity)} ${missing(r.unit,'单位')}</td><td class="mono">${missing(r.condition,'件状')}</td><td class="mono">${r.price?esc(r.price.currency+' '+r.price.amount):'—'}</td><td class="mono">${esc(r.total||'—')}</td><td>${r.price?`<span class="chip ${r.price.kind==='synthetic'?'tone-warn':''}">${esc(kindLabel(r.price.kind))}</span>`:'<span class="chip tone-price">待报价</span>'}</td><td>${r.approved?`<span class="chip tone-ok">${esc(r.approval.actor)} · ${esc(r.approval.date)}</span>`:r.stale?'<span class="chip tone-warn">旧批准失效</span>':r.issues.length?`<span class="chip tone-bad">${r.issues.length} 项阻断</span>`:'<span class="chip tone-ready">待批准</span>'}</td></tr>`).join('')||'<tr><td colspan="8">没有有效询价行</td></tr>'}</tbody></table></div>
  <section class="card approve-box"><label>批准人<input data-keep="g:actor" id="actor" autocomplete="name" placeholder="批准人姓名"></label><button type="button" class="btn btn-primary" id="approve" ${blocked||s.ready?'disabled':''}>${s.ready?'已批准当前版本':s.stale.length?'重新批准当前版本':'批准当前版本'}</button>
  <p class="msg ${blocked?'error':''}" id="readiness">${blocked?(s.dirty||priceDrafts.has(c.id)?'本单有未保存行或价表草稿，请先保存或放弃；尚未批准。':s.active.length?`${s.issues.length} 行仍有阻断${s.needsReview?'，解析警告未核查':''}；全部通过核验后才能批准。`:'没有有效询价行。'):s.ready?'可前往输出报价响应。':'核验已通过，填写批准人后可批准。'}</p>${s.ready?'<button type="button" class="btn" data-goto="output|o">前往输出 →</button>':''}</section></div>`;
  qsa('[data-gate-jump]').forEach(b=>b.onclick=()=>document.querySelector(`[data-gate="${b.dataset.gateJump}"]`)?.click());
  $('approve').onclick=()=>run(async()=>{
    if([...rowDrafts.keys()].some(k=>k.startsWith(current.id+':')))throw Error('本单有未保存行草稿，请先保存或放弃再批准');
    if(priceDrafts.has(current.id))throw Error('价格依据总表有待保存修改，请先保存或放弃再批准');
    const actor=$('actor').value;if(!actor.trim()){$('actor').focus();throw Error('请填写批准人')}
    const done=busyButton($('approve'),'批准中…');
    try{if(await change('approve',{actor},'当前版本已批准；之后变更相关输入或价格需重新批准。'))setFocus('output','o')}finally{done()}
  });
}
const quoteSnapshots=new Map();
function viewOutput(){
  const c=current,s=summarize(c),snap=quoteSnapshots.get(c.id),fresh=snap&&snap.revision===c.revision;
  W().innerHTML=head('输出',s.ready?'报价响应':'报价响应未就绪',{sub:s.ready?`只输出当前已批准的工作版本 <b class="mono">${c.revision}</b> / 价表 <b class="mono">v${c.price_version}</b>；导出时服务端再次核验版本与有效期，金额以服务端为准。`:'当前版本未全部批准，正式输出被阻止。'})+
  `<div class="w-body">${s.ready?`<div class="btn-row"><button type="button" class="btn btn-primary" id="quotePreview">${fresh?'重新生成预览':'生成报价响应预览'}</button><button type="button" class="btn" id="downloadHtml" ${fresh?'':'disabled'}>下载此版 HTML</button><button type="button" class="btn" id="printHtml" ${fresh?'':'disabled'}>打印</button><button type="button" class="btn" id="exportCsv">导出 CSV</button></div>
    ${fresh?`<p class="note">预览绑定工作版本 ${snap.revision} / 价表 v${snap.priceVersion}，生成于 ${esc(snap.at)}。之后任何变更需重新生成；预览不写入正式输出实录。</p><iframe id="quoteFrame" class="quote" title="报价响应预览"></iframe>`:'<p class="hint">点击生成后由服务端核验并渲染报价响应。</p>'}`:
    `<p class="note bad">${s.stale.length?`${s.stale.length} 行旧批准已失效（输入、价源或日期变化）。`:''}${s.issues.length?`${s.issues.length} 行仍有阻断。`:''}旧批准或历史版本不能导出当前值。</p><button type="button" class="btn" data-goto="approve|a">前往批准</button>`}</div>`;
  if(!s.ready)return;
  if(fresh)$('quoteFrame').srcdoc=snap.html;
  $('quotePreview').onclick=()=>run(async()=>{const ctx=interaction.capture(current),pv=current.price_version,done=busyButton($('quotePreview'),'核验中…');try{const html=await (await fetchExport(ctx,'html')).text();if(!interaction.active(ctx,current)||current.revision!==ctx.revision){activity(ctx,'报价响应已核验，未打开到其他工作单；请回原单重新预览');return}quoteSnapshots.set(ctx.caseId,{html,revision:ctx.revision,priceVersion:pv,at:new Date().toLocaleTimeString()});renderWork();notice(`已生成工作版本 ${ctx.revision} 的纯预览；未写入正式输出事件。`,'ok')}catch(e){if(interaction.active(ctx,current))throw e;activity(ctx,'报价响应失败：'+e.message,true)}finally{done()}});
  const formal=(format,button,print=false)=>run(async()=>{
    const ctx=interaction.capture(current),task=interaction.begin(ctx,'export:'+format),done=busyButton(button,'重新核验并输出…');
    try{const response=await fetchExport(ctx,format,'export');
      if(!interaction.active(ctx,current)||current.revision!==ctx.revision){activity(ctx,'正式输出已由服务端核验并记录；未在其他工作单下载或打印，请回原单查看实录。');return}
      const blob=await response.blob();
      if(!interaction.active(ctx,current)||current.revision!==ctx.revision){activity(ctx,'输出文件已取得，页面已切换或版本已变化，未自动下载或打印。');return}
      if(print){const frame=$('quoteFrame');if(!frame)return;const loaded=new Promise(resolve=>frame.addEventListener('load',resolve,{once:true}));frame.srcdoc=await blob.text();await loaded;if(!interaction.active(ctx,current)||current.revision!==ctx.revision||!frame.isConnected)return;frame.contentWindow.print();notice('已重新核验并登记打印输出；请在打印窗口确认，系统不能确认纸张结果。','ok')}
      else{download(blob,`quote-${ctx.caseId}-r${ctx.revision}.${format}`);notice(`已正式导出工作版本 ${ctx.revision} 的 ${format.toUpperCase()}；已记录输出事件。`,'ok')}
      refreshList();
    }catch(e){if(interaction.active(ctx,current))throw e;activity(ctx,'正式输出失败或结果未知：'+e.message,true)}finally{interaction.finish(task);done()}
  });
  if(fresh){$('downloadHtml').onclick=()=>formal('html',$('downloadHtml'));$('printHtml').onclick=()=>formal('html',$('printHtml'),true)}
  $('exportCsv').onclick=()=>formal('csv',$('exportCsv'));
}

/* ---------- log ---------- */
const eventNames={import:'导入原件',material_append:'追加原件',parse_review:'解析警告核查',resolve:'行裁定',price_update:'价表新版本',price_import_review:'价目原件审阅',approve:'批准',export:'正式输出',candidate_accept:'接纳候选',candidate_partial_accept:'局部接纳候选',candidate_reject:'拒绝候选',clarification_register:'登记澄清',clarification_receive:'登记答复',clarification_apply:'答复回填',clarification_resolve:'澄清解决',clarification_superseded:'澄清旧目标结束'};
function eventSummary(e){const d=e.detail||{};if(e.action==='approve')return `批准人 ${d.actor} · 工作版本 ${d.revision}`;if(e.action==='export')return `${d.format} · 工作版本 ${d.revision}`;if(e.action==='price_update')return `价表 v${d.version} · 影响 ${(d.affected||[]).length} 行`;return Object.keys(d).slice(0,4).join(' · ')||'详情'}
function viewLog(){
  W().innerHTML=head('版本与决策记录',`${current.events.length} 条`,{sub:'按时间倒序，记录来自服务端。'})+`<div class="w-body"><div class="events">${current.events.slice().reverse().map(e=>`<div class="event"><span class="mono hint">${esc(String(e.time).replace('T',' ').slice(0,19))}</span><span class="chip">${esc(eventNames[e.action]||e.action)}</span><details><summary>${esc(eventSummary(e))}</summary><pre class="pre">${esc(JSON.stringify(e.detail,null,2))}</pre></details></div>`).join('')||'<p class="empty">暂无记录。</p>'}</div></div>`;
}

run(boot);
