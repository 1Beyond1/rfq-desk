/* Agent-first spotlight tour for the judge trial: the page dims, the one thing to look at or click lights up, and a
   bubble beside it explains why. Action steps move on by themselves once the work order shows they were done.
   It reads the page's own state (current, focus, agentChat). */
(()=>{
const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
const visible=el=>!!el&&el.getClientRects().length>0;
const rows=()=>(current?.rows||[]).filter(r=>!r.excluded);
const TASK='请处理这封询价邮件：提取询价行并对照原文，查有效价格，缺信息就起草给客户的澄清邮件，最后告诉我下一步。';
// The page records a fresh export in its own guide state before the work order is reloaded.
const exported=c=>!!c&&(c.events?.some(e=>e.action==='export'&&e.detail?.revision===c.revision)||window.rfqLastExport?.caseId===c.id&&window.rfqLastExport.revision===c.revision);
const toAgent=()=>{if(focus?.type!=='agent')setFocus('agent');setTimeout(()=>{const i=document.getElementById('agentInput');if(i&&!i.value&&!agentChat.turns.length){i.value=TASK;agentChat.text=TASK}},150)};

const STEPS=[
 {kind:'look',target:()=>[q('.queue'),q('.work'),q('.source')],title:'先看布局：三栏各管一段',
  mobileBody:'手机上用底部的“事项 / 处理 / 原件”切换视图，或点“Agent”提问。上方是可滚动的操作区，下方说明不会盖住原件或按钮。',
  body:'左栏是这张单要处理的事项，中间是核对、裁定与核价，右侧是邮件原件。任何结论都要回到右侧原件核对，所以我们把它一直留在旁边。'},
 {kind:'act',enter:toAgent,target:()=>[q('#agentInput'),q('#agentForm button[type=submit]')],title:'把客户邮件交给询价 Agent',
  body:'这张工作单里是一封客户询价邮件（右侧“原件”可展开查看），任务已经替你写好。点“发送”：Agent 会自己决定调用哪些工具——读原件、提取询价行、查价、查规则、起草澄清——再告诉你结论。',
  done:()=>agentChat.busy||agentChat.turns.length>0},
 {kind:'act',waiting:()=>agentChat.busy,target:()=>q('#agentPending')||q('#agentLog'),title:'Agent 正在自主调用工具',
  body:'下方实时显示它已经做了哪些步骤，通常 10–30 秒。候选和草稿都要经你确认才生效。',
  done:()=>!agentChat.busy&&agentChat.turns.length>0},
 {kind:'look',target:()=>qa('#agentLog .ag-tl').at(-1)?.closest('.ag-card'),title:'看它这一轮做了什么',
  body:'每一行是它真实调用的一个工具和得到的结果：提取了几条候选、价格查到没有、要不要向客户澄清。工具由模型自己选，结果由程序给出。'},
 {kind:'look',target:()=>qa('#agentLog .agent-msg.bot .agent-text').at(-1),title:'它的结论',
  body:'结论里说清提取到哪几行、价格情况、还缺什么信息，以及下一步该由你做什么。下方“回答模型”是实际响应的模型服务。'},
 {kind:'look',skip:()=>!visible(qa('#agentLog .agent-draft').at(-1)),target:()=>qa('#agentLog .agent-draft').at(-1),title:'缺信息时，它起草澄清邮件',
  body:'这封邮件是草稿，发不发、发给谁由你决定。'},
 {kind:'act',target:()=>q('#agentNext')||q('#queue'),title:'打开它提出的候选',
  body:'点“下一步”去审阅候选。Agent 提取的询价行还不是正式数据，要你核对后才生效。',
  done:()=>focus?.type==='cand'||!current?.progress?.pending_candidates&&rows().length>0},
 {kind:'look',skip:()=>!current?.progress?.pending_candidates,enter:()=>{if(focus?.type!=='cand'){const f=firstFocus();if(f?.type==='cand')setFocus(f.type,f.id)}},target:()=>q('#work .cfields'),title:'每个值都带原文出处',
  body:'询价号、件号、数量、单位、件状旁边都标着来自邮件第几行的哪段原文。点出处可以在右侧原件里高亮核对。'},
 {kind:'act',skip:()=>!current?.progress?.pending_candidates,fill:()=>{
  const r=q('#work [data-keep="reason"]');
  if(r&&!r.value){r.value='已对照邮件原文核对';r.dispatchEvent(new Event('input',{bubbles:true}))}
  const a=q('#work [data-keep="actor"]');
  if(a&&!a.value){a.value='评委体验';a.dispatchEvent(new Event('input',{bubbles:true}))}
  const c=q('#work .checks input[type=checkbox]');
  if(c&&!c.checked)c.click();
},target:()=>[q('#work [data-keep="reason"]')||q('#work .checks'),q('#candAcceptBatch')],title:'核对后，由你接纳',
  body:'理由和勾选已经替你填好，你只要对照右侧原件确认，然后点“接纳本批所有无争议候选”。接纳后它们才成为正式询价行。',
  done:()=>!current?.progress?.pending_candidates&&rows().length>0},
 {kind:'act',skip:()=>!current?.progress?.pending_parse_review,enter:()=>setFocus('warnings','w'),fill:()=>{const t=q('#work textarea[data-keep$="reason"],#work textarea');if(t&&!t.value){t.value='已逐行核对原件，没有漏项';t.dispatchEvent(new Event('input',{bubbles:true}))}},target:()=>[q('#work textarea'),q('#review')],title:'确认原件没有漏项',
  body:'结论已经替你写好，对照右侧原件看一眼，点“记录人工核查结论”即可。',
  done:()=>!current?.progress?.pending_parse_review},
 {kind:'act',enter:()=>{const r=rows().find(r=>!r.price);if(r)setFocus('price',r.id)},target:()=>q('#loadPricesInline')||q('#loadPrices'),title:'补上价格依据',
  body:'Agent 查价时已指出缺少有效价格。这里只接受有来源、在有效期内的价格；本次演示可直接载入预置价表。',
  done:()=>rows().length>0&&rows().every(r=>r.price)},
 {kind:'act',enter:()=>{setFocus('approve','a');setTimeout(()=>{const a=q('#actor');if(a&&!a.value){a.value='评委体验';a.dispatchEvent(new Event('input',{bubbles:true}))}},160)},target:()=>[q('#actor'),q('#approve')],title:'检查后，由你批准',
  body:'批准人绑定当前登录身份。批准把这一版询价、价格和澄清状态锁定，同时在 MatrixOne 存一个快照；之后任何改动都会让批准失效。',
  done:()=>rows().length>0&&rows().every(r=>r.approved)},
 {kind:'act',enter:()=>setFocus('output','o'),target:()=>q('#quotePreview'),title:'生成报价响应预览',
  body:'服务器会按批准的版本重新核验后渲染报价响应。核对询价号和金额。',
  done:()=>visible(q('#quoteFrame'))},
 {kind:'act',target:()=>q('#exportCsv'),title:'导出这一版',
  body:'点“导出 CSV”。正式输出由服务器再次核验并记录，下载的文件绑定当前批准版本。',
  done:()=>exported(current)},
 {kind:'look',target:()=>[q('#agentEntry'),q('#mAgent')],title:'体验完成',
  body:'Agent 读邮件、提候选、查价、起草澄清；你核对、接纳、核价、批准、导出。之后可以随时从这里回到 Agent 继续问它，比如“批准后改过什么”。',next:'完成'},
];

const HOME_STEPS=[
 {kind:'look',target:()=>[q('.ah-hero'),q('.ah-log'),q('.ah-ask')],title:'先看一眼布局：从上到下三块',
  body:'最上面是标题和四个入口（收件箱 / 工作单 / 库存与历史 / 导入文件）；中间四张卡是今天的待办数字，卡片可以直接点进去；下面是 Agent 对话和一键提问的输入框。后面几步就按这个顺序走。'},
 {kind:'look',target:()=>document.querySelector('#ahLog .ah-briefline')||document.querySelector('#ahStats'),title:'数字和一句建议',
  body:'上面四张卡是当前账号真实的待办：多少封待分流、多少封 Jev 拿不准、已经初筛了多少。下面这句是系统按这些数字给的建议，没有调用模型。'},
 {kind:'act',waiting:()=>!!window.ahState?.busy,target:()=>[()=>document.querySelector('#ahInput'),()=>document.querySelector('#ahSend')].map(f=>f()).filter(Boolean),
  enter:()=>{const i=document.querySelector('#ahInput');if(i&&!i.value){i.value='有什么要我审的？';i.focus()}},
  title:'把问题交给它，看它怎么查',
  body:'问题已经替你填好了，点“发送”。它会去查待办再逐条回答，数字和上面的卡片一致。',
  done:()=>window.ahState&&window.ahState.turns.some(t=>!t.pending&&(t.tools||[]).includes('pending_overview'))},
 {kind:'act',waiting:()=>!!window.ahState?.busy,target:()=>[()=>document.querySelector('#ahInput'),()=>document.querySelector('#ahSend')].map(f=>f()).filter(Boolean),
  enter:()=>{const i=document.querySelector('#ahInput');if(i){i.value='液压系统那个密封圈还有多少库存？';i.focus()}},
  title:'只给描述，也能找件号',
  body:'这次只给一句人话，不给件号。它会先做向量检索，列出候选件号、相似度和库位；选哪一个由你定。',
  done:()=>window.ahState&&window.ahState.turns.some(t=>(t.tools||[]).includes('search_parts'))},
 {kind:'act',target:()=>document.querySelector('[data-ah-go="inbox"]'),title:'去收件箱处理真正的询价',
  body:'上面几步是“先看一眼”。真正的处理在收件箱：挑一封询价，让 Jev 分流，再交给工作单。',
  done:()=>!document.getElementById('landing').hidden},
];

const KEY='rfq-spotlight';
let state=null;try{state=JSON.parse(sessionStorage.getItem(KEY)||'null')}catch{}
const save=()=>{try{state?sessionStorage.setItem(KEY,JSON.stringify(state)):sessionStorage.removeItem(KEY)}catch{}};
const root=document.createElement('div');root.className='coach';root.hidden=true;
root.innerHTML='<div class="coach-hole"></div><div class="coach-bubble" role="dialog" aria-live="polite"><div class="coach-copy"><div class="coach-count"></div><h3 class="coach-title"></h3><p class="coach-body"></p></div><div class="coach-actions"><button type="button" class="btn btn-primary btn-sm coach-next">下一步</button><button type="button" class="text-btn coach-skip">跳过这一步</button><button type="button" class="text-btn coach-collapse">先收起</button><button type="button" class="text-btn coach-end">结束引导</button></div></div>';
document.body.append(root);

// 邀请卡：进入工作区先问一句，不强制开始。
const invite=document.createElement('div');
invite.className='coach-invite';invite.hidden=true;
invite.innerHTML='<div class="ci-head"><b>要跟着走一遍吗</b><span>4 步 · 约 1 分钟</span></div><p class="ci-body">看它怎么汇总待办、怎么用一句描述找到件号，再进收件箱处理询价。</p><div class="ci-acts"><button type="button" class="btn btn-primary btn-sm" data-ci-start>开始</button><button type="button" class="text-btn" data-ci-later>暂不用</button></div>';
document.body.append(invite);

// 药丸：收起或暂不之后仍然留在右下角，随时能回来。
const pill=document.createElement('button');
pill.type='button';pill.className='coach-reopen';pill.hidden=true;
document.body.append(pill);

const hole=root.querySelector('.coach-hole'),bubble=root.querySelector('.coach-bubble');
let entered=-1,lastScroll=-1,stepAt=Date.now(),waitAt=null;
const mobileGuide=()=>matchMedia('(max-width:900px)').matches;
const mainView=()=>['agentHome','landing','desk'].map(id=>document.getElementById(id)).find(el=>el&&!el.hidden);
let docked=false;
function syncMobileDock(){
 const activeCase=state&&(!state.caseId||(typeof current!=='undefined'&&current?.id===state.caseId));
 const next=mobileGuide()&&document.body.dataset.auth==='ready'&&!!(activeCase||!invite.hidden||!pill.hidden);
 const view=mainView(),previousScroll=docked?(view?.scrollTop||0):scrollY;
 const h=Math.min(innerHeight,window.visualViewport?.height||innerHeight);
 document.body.style.setProperty('--coach-viewport-height',Math.round(h)+'px');
 document.body.classList.toggle('coach-docked',next);
 if(next!==docked){
  docked=next;
  if(next){window.scrollTo(0,0);if(view)view.scrollTop=previousScroll}
  else window.scrollTo(0,previousScroll);
 }
}

function targets(step){return [step.target()].flat().filter(visible)}
function place(step){
 const els=targets(step);
 if(mobileGuide()){
  // Reserve real layout space; never float a phone-sized bubble over the app.
  hole.hidden=true;bubble.style.cssText='';
  if(els.length&&lastScroll!==state.step){
   lastScroll=state.step;
   requestAnimationFrame(()=>{if(state)els[0].scrollIntoView({block:'center',inline:'nearest',behavior:'instant'})});
  }
  return;
 }
 if(!els.length){hole.hidden=true;bubble.style.cssText='left:50%;top:40%;transform:translate(-50%,-50%);width:'+Math.min(360,innerWidth-24)+'px';return}
 const rs=els.map(e=>e.getBoundingClientRect()),pad=8;
 const r={left:Math.min(...rs.map(x=>x.left))-pad,top:Math.min(...rs.map(x=>x.top))-pad,right:Math.max(...rs.map(x=>x.right))+pad,bottom:Math.max(...rs.map(x=>x.bottom))+pad};
 const W=innerWidth,H=innerHeight,bw=Math.min(340,W-24),bh=bubble.offsetHeight||190,gap=14;
 // 整屏概览步骤（三栏一起亮）不画遮罩，否则整个页面压暗、气泡也找不到地方停。
 const wide=(r.right-r.left)*(r.bottom-r.top)>W*H*0.55;
 if(wide){
   hole.hidden=true;
   bubble.style.cssText='left:'+(W-bw-18)+'px;top:'+(H-bh-18)+'px;width:'+bw+'px';
   return;
 }
 hole.hidden=false;Object.assign(hole.style,{left:r.left+'px',top:r.top+'px',width:(r.right-r.left)+'px',height:(r.bottom-r.top)+'px'});
 // Prefer spots that keep the original document panel visible, since the visitor checks values against it.
 // 首页把内容收在 900px 里，两侧有空白：气泡优先停在右边空白，绝不压住对话。
 const wrap=document.querySelector('.ah-wrap');
 if(wrap&&visible(wrap)&&!state.caseId){
  const wr=wrap.getBoundingClientRect(),room=Math.round(W-wr.right);
  // 侧栏窄一点也放，气泡按空间收窄，绝不横跨到对话区。
  if(room>196){
   const tw=Math.min(room-16,320);
   bubble.style.cssText=`left:${Math.round(wr.right+8)}px;top:${Math.round(Math.max(12,Math.min(H-bh-12,(H-bh)/2)))}px;width:${tw}px`;
   const r2=els.map(e=>e.getBoundingClientRect()),pad2=8;
   const u={left:Math.min(...r2.map(x=>x.left))-pad2,top:Math.min(...r2.map(x=>x.top))-pad2,right:Math.max(...r2.map(x=>x.right))+pad2,bottom:Math.max(...r2.map(x=>x.bottom))+pad2};
   Object.assign(hole.style,{left:u.left+'px',top:u.top+'px',width:(u.right-u.left)+'px',height:(u.bottom-u.top)+'px'});
   return;
  }
 }
 const src=document.querySelector('.source')?.getBoundingClientRect(),clamp=(x,y)=>[Math.max(12,Math.min(x,W-bw-12)),Math.max(12,Math.min(y,H-bh-12))];
 const over=(x,y,b)=>!!b&&b.right>b.left&&x<b.right&&x+bw>b.left&&y<b.bottom&&y+bh>b.top;
 const spots=[[r.left,r.bottom+gap],[r.left,r.top-gap-bh],[r.right+gap,r.top],[r.left-gap-bw,r.top],[r.right-bw,r.bottom+gap],[r.right-bw,r.top-gap-bh],[W-bw-12,12],[W-bw-12,H-bh-12],[12,H-bh-12]].map(([x,y])=>clamp(x,y));
 // Never cover what the visitor has to click: first keep clear of the whole lit area, then at least of each lit element.
 const ok=spots.filter(([x,y])=>!over(x,y,r)),clear=spots.filter(([x,y])=>!rs.some(b=>over(x,y,b)));
 const [left,top]=ok.find(([x,y])=>!over(x,y,src))||ok[0]||clear[0]||spots[0];
 bubble.style.cssText=`left:${left}px;top:${top}px;width:${bw}px`;
 if(lastScroll!==state.step){lastScroll=state.step;
  const go=()=>{try{
    els[0].scrollIntoView({block:'center',inline:'nearest',behavior:'smooth'});
    const box=els[0].getBoundingClientRect();
    if(box.top<80||box.bottom>innerHeight-90)els[0].scrollIntoView({block:'nearest',behavior:'smooth'});
  }catch{}};
  go();setTimeout(go,220);setTimeout(go,700);setTimeout(go,1400);
 }
}
function end(completed=false){if(state)try{sessionStorage.setItem(state.caseId?'rfq-case-tour-'+(completed?'done':'declined'):'rfq-home-tour-'+(completed?'done':'declined'),'1')}catch{};state=null;save();root.hidden=true;pill.hidden=true;document.body.classList.remove('coaching')}
function go(i){state={...state,step:i,skipped:0};entered=-1;lastScroll=-1;save()}
root.querySelector('.coach-next').onclick=()=>{if(state.step+1>=steps().length)end(true);else go(state.step+1)};
root.querySelector('.coach-skip').onclick=()=>{
  // 第 1 步之后的内容都取自 Agent 的真实轮次；没有轮次时跳过去会被 tick 立刻退回，按钮等于失效。
  if(state.step===0&&!agentChat.turns.length&&!agentChat.busy){end();notice('引导要先发出这封邮件才能继续。随时可以从「操作引导」重新开始。');return}
  go(state.step+1);
};
root.querySelector('.coach-end').onclick=end;
// 评委想自己点两下再回来时，收起比“结束引导”更合适。
const reopen=pill;
root.querySelector('.coach-collapse').onclick=()=>{state={...state,min:true};save();tick()};
reopen.onclick=()=>{if(!state)state={caseId:null,step:0};if(!state.caseId)ensureHome();entered=-1;lastScroll=-1;stepAt=state.stepAt||Date.now();state={...state,min:false};save();setTimeout(tick,80)};
invite.querySelector('[data-ci-start]').onclick=()=>{const cid=invite.dataset.caseId||null;if(!cid)ensureHome();invite.hidden=true;pill.hidden=true;state={caseId:cid,step:0};entered=-1;lastScroll=-1;stepAt=Date.now();save();setTimeout(tick,80)};
invite.querySelector('[data-ci-later]').onclick=()=>{
  invite.hidden=true;
  const isCase=!!invite.dataset.caseId;
  try{sessionStorage.setItem(isCase?'rfq-case-tour-declined':'rfq-home-tour-declined','1')}catch{}
  pill.innerHTML='继续引导';pill.hidden=false;
};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state)end()});

// 导览的第一步在工作区首页；从别处启动时先把首页切出来，否则目标元素不可见。
function ensureHome(){
  const home=document.getElementById('agentHome');
  if(home&&home.hidden&&typeof window.showHome==='function')window.showHome();
}

const steps=()=>state&&!state.caseId?HOME_STEPS:STEPS;
function renderTick(){
 if(!state||document.body.dataset.auth!=='ready'){root.hidden=true;document.body.classList.remove('coaching');return}
 if(state.caseId&&(!current||current.id!==state.caseId)){root.hidden=true;document.body.classList.remove('coaching');return}
 // A failed agent turn leaves nothing to wait for: go back to the send step.
 // Steps already done, or not relevant to this work order, are passed over.
 let skippedNow=0;
 while(steps()[state.step]&&(steps()[state.step].skip?.()||steps()[state.step].kind==='act'&&steps()[state.step].done())){state={...state,step:state.step+1};entered=-1;lastScroll=-1;skippedNow++;save()}
 if(skippedNow){state={...state,skipped:(state.skipped||0)+skippedNow};save()}
 const step=steps()[state.step];if(!step){end(true);return}
 if(state.caseId&&step.waiting&&!agentChat.busy&&!agentChat.turns.length){go(STEPS.findIndex(s=>s.enter===toAgent));return}
 try{if(step.fill)step.fill()}catch{}
 if(entered!==state.step){entered=state.step;stepAt=Date.now();waitAt=null;step.enter?.()}
 root.hidden=false;document.body.classList.add('coaching');
 if(state.min){
   hole.hidden=true;bubble.hidden=true;reopen.hidden=false;
   reopen.innerHTML=`继续引导 · <b class="coach-reopen-count">${state.step+1} / ${steps().length}</b>`;
   document.body.classList.remove('coaching');
   return;
 }
 bubble.hidden=false;reopen.hidden=true;
 root.querySelector('.coach-count').textContent=`${state.caseId?'3 分钟体验':'工作区导览'} · ${state.step+1} / ${steps().length}`+(state.skipped?`（已跳过 ${state.skipped} 步${state.caseId?'，当前工作单不适用':''}）`:'');
 root.querySelector('.coach-title').textContent=step.title;
 // 等 Agent 的这一步最容易被当成卡住，把已等待时间说出来。
 const waiting=!!step.waiting?.();
 if(waiting&&waitAt===null)waitAt=Date.now();else if(!waiting)waitAt=null;
 const waited=waiting?Math.round((Date.now()-waitAt)/1000):0;
 root.querySelector('.coach-body').textContent=(mobileGuide()&&step.mobileBody||step.body)+(waited>=6?`（已进行 ${waited} 秒，工具调用多时会久一些）`:'');
 const next=root.querySelector('.coach-next');next.hidden=step.kind!=='look';next.textContent=step.next||'下一步';
 root.querySelector('.coach-skip').hidden=step.kind!=='act';
 place(step);
 // 用户已经发出指令、正在等结果时，把高光让开，别挡着看回复。
 const busy=(typeof ahState!=='undefined'&&ahState.busy)||(typeof agentChat!=='undefined'&&agentChat.busy);
 if(busy){hole.hidden=true;bubble.hidden=false}
 if(entered===state.step&&!targets(step).length&&state.step===0)setTimeout(()=>{if(state&&state.step===0)place(STEPS[0])},120);
}
function tick(){syncMobileDock();try{renderTick()}finally{syncMobileDock()}}
setInterval(tick,300);addEventListener('resize',tick);addEventListener('scroll',tick,true);
window.visualViewport?.addEventListener('resize',tick);
function showInvite(caseId){
  invite.dataset.caseId=caseId||'';
  if(caseId){
    invite.querySelector('.ci-head b').textContent='要看一遍这张单怎么处理吗';
    invite.querySelector('.ci-head span').textContent='约 2 分钟';
    invite.querySelector('.ci-body').textContent='从三栏布局讲起，再走一遍提取、核对、核价、批准和导出。';
  }else{
    invite.querySelector('.ci-head b').textContent='要跟着走一遍吗';
    invite.querySelector('.ci-head span').textContent=HOME_STEPS.length+' 步 · 约 1 分钟';
    invite.querySelector('.ci-body').textContent='看它怎么汇总待办、怎么用一句描述找到件号，再进收件箱处理询价。';
  }
  invite.hidden=false;pill.hidden=true;syncMobileDock();
}
// 任何路径打开工作单都会走到这里：安静地看一眼，只问一次。
let shownCase='';
setInterval(()=>{
  try{
    const desk=document.getElementById('desk');
    if(!desk||desk.hidden)return;
    const cid=(typeof current!=='undefined'&&current&&current.id)?current.id:'';
    if(!cid||cid===shownCase||state||!invite.hidden)return;
    if(sessionStorage.getItem('rfq-case-tour-done')||sessionStorage.getItem('rfq-case-tour-declined'))return;
    shownCase=cid;showInvite(cid);
  }catch{}
},800);

window.rfqSpotlight={
  start(caseId){if(!caseId)ensureHome();invite.hidden=true;pill.hidden=true;state={caseId,step:0};entered=-1;lastScroll=-1;stepAt=Date.now();save()},
  active:()=>!!state,
  invite(caseId){showInvite(caseId||null)},
  inviteCase(caseId){showInvite(caseId)},
  maybeInviteCase(caseId){
    try{
      if(!caseId)return;
      if(sessionStorage.getItem('rfq-case-tour-done')||sessionStorage.getItem('rfq-case-tour-declined'))return;
      // 首页导览还没走完就进了工单：那次导览已经没有意义，收掉再问新的。
      if(state&&!state.caseId){state=null;save();root.hidden=true;pill.hidden=true;document.body.classList.remove('coaching')}
      if(state)return;
      showInvite(caseId);
    }catch{}
  },
  dismiss(){invite.hidden=true}
};
})();
