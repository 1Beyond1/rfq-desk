/* Agent-first spotlight tour for the judge trial: the page dims, the one thing to look at or click lights up, and a
   bubble beside it explains why. Action steps move on by themselves once the work order shows they were done.
   It reads the page's own state (current, focus, agentChat, ahState). */
(()=>{
const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
const visible=el=>!!el&&el.getClientRects().length>0;
const rows=()=>(typeof current!=='undefined'&&current?.rows?current.rows:[]).filter(r=>!r.excluded);
const TASK='请处理这封询价邮件：提取询价行并对照原文，查有效价格，缺信息就起草给客户的澄清邮件，最后告诉我下一步。';

const getChat=()=>{
  if(typeof window.getAgentChat==='function'&&typeof current!=='undefined'&&current?.id)return window.getAgentChat(current.id);
  if(typeof agentChat!=='undefined'&&agentChat)return agentChat;
  return {turns:[],busy:false,text:''};
};
const currentAgentTurns=()=>getChat().turns||[];
const currentAgentBusy=()=>!!getChat().busy;
const modelEnabled=()=>typeof modelState==='undefined'||!!modelState?.requests_enabled;
const matrixOneConnected=()=>typeof modelState!=='undefined'&&Boolean(modelState?.matrixone?.connected||modelState?.platform_connected);
const generalCands=()=>{
  if(typeof current==='undefined'||!current)return [];
  if(typeof summarize==='function')return summarize(current).cands||[];
  return (current.candidate_batches||[]).filter(b=>b.expected_revision===current.revision)
    .flatMap(b=>b.candidates.filter(x=>x.status==='pending').map(x=>({b,x})));
};
const hasCaseWork=()=>generalCands().length>0||!!current?.progress?.pending_parse_review||rows().length>0;
const caseReady=()=>{
  const active=rows();
  if(!active.length||!active.every(r=>r.approved))return false;
  if(typeof current?.case_approved==='boolean')return current.case_approved;
  if(typeof current?.progress?.case_approved==='boolean')return current.progress.case_approved;
  return true;
};
const exported=c=>!!c&&(c.events?.some(e=>e.action==='export'&&e.detail?.revision===c.revision)||window.rfqLastExport?.caseId===c.id&&window.rfqLastExport.revision===c.revision);
const mobileGuide=()=>matchMedia('(max-width:900px)').matches;
const ensureMobileView=v=>{
  if(!mobileGuide()||typeof setView!=='function')return;
  if(document.body.dataset.view!==v)setView(v,{noScroll:true});
};
const onAgentWorkView=()=>typeof focus!=='undefined'&&focus?.type==='agent'&&(!mobileGuide()||document.body.dataset.view==='work');
const hasAgentTimeline=()=>{
  const last=currentAgentTurns().at(-1);
  return !!(last&&((last.steps&&last.steps.length)||(last.tools&&last.tools.length)));
};
const hasAgentDraft=()=>!!currentAgentTurns().at(-1)?.draft;
const isInboxMode=()=>{
  const landing=document.getElementById('landing');
  if(!landing||landing.hidden)return false;
  if(typeof window.getOnsiteMode==='function')return window.getOnsiteMode()==='inbox';
  if(typeof onsiteMode!=='undefined')return onsiteMode==='inbox';
  return document.getElementById('workspaceInbox')?.getAttribute('aria-pressed')==='true';
};
const completedHomeTurns=()=>(window.ahState?.turns||[]).filter(t=>!t.pending&&!t.error&&Boolean(t.reply)).length;

const toAgent=()=>{
  if(typeof focus==='undefined'||focus?.type!=='agent')setFocus('agent');
  ensureMobileView('work');
  const chat=getChat();
  const i=document.getElementById('agentInput');
  if(i&&!i.value.trim()&&!(chat.turns&&chat.turns.length)&&!chat.busy){
    i.value=TASK;
    chat.text=TASK;
  }
};
const enterAgentView=()=>{
  if(typeof focus==='undefined'||focus?.type!=='agent')setFocus('agent');
  ensureMobileView('work');
};
const enterFirstCand=()=>{
  const cands=generalCands();
  if((typeof focus==='undefined'||focus?.type!=='cand')&&cands.length){
    const p=cands[0];
    setFocus('cand',p.b.id+':'+p.x.id);
  }
  ensureMobileView('work');
};
const currentCandObj=()=>{
  if(typeof focus==='undefined'||focus?.type!=='cand'||!current)return null;
  const [bid,cid]=String(focus.id||'').split(':');
  return current.candidate_batches?.find(b=>b.id===bid)?.candidates?.find(x=>x.id===cid)||null;
};
const candHasDispute=()=>{
  const c=currentCandObj();
  const err=q('#candError')?.textContent?.trim();
  if(err)return true;
  if(q('#candMode')?.value==='partial')return true;
  const batchBtn=q('#candAcceptBatch');
  if(batchBtn&&(batchBtn.hidden||batchBtn.disabled))return true;
  if(c&&Array.isArray(c.unknown_fields)&&c.unknown_fields.length)return true;
  if(c&&c.fields?.rfq&&rows().some(r=>r.rfq===c.fields.rfq&&r.part===c.fields.part))return true;
  return false;
};

const STEPS=[
 {id:'layout',kind:'look',overview:true,
  target:()=>[q('.queue'),q('.work'),q('.source')],
  title:'先看布局：三栏各管一段',
  mobileBody:'手机上用底部的“事项 / 处理 / 原件”切换视图，或点“Agent”提问。上方是可滚动的操作区，下方说明不会盖住原件或按钮。',
  body:'左栏是这张单要处理的事项，中间是核对、裁定与核价，右侧是邮件原件。任何结论都要回到右侧原件核对，所以我们把它一直留在旁边。'},
 {id:'agent-send',phase:'agent',kind:'act',
  skip:()=>Boolean(state?.skipAgent)||(!modelEnabled()&&!currentAgentTurns().length&&!currentAgentBusy()),
  enter:toAgent,
  target:()=>[q('#agentInput'),q('#agentForm button[type=submit]')],
  title:'把客户邮件交给询价 Agent',
  body:'这张工作单里是一封客户询价邮件（右侧“原件”可展开查看），任务已经替你写好。点“发送”：Agent 会自己决定调用哪些工具——读原件、提取询价行、查价、查规则、起草澄清——再告诉你结论。',
  done:()=>currentAgentBusy()||currentAgentTurns().length>0},
 {id:'agent-wait',phase:'agent',kind:'act',
  skip:()=>Boolean(state?.skipAgent)||(!modelEnabled()&&!currentAgentTurns().length&&!currentAgentBusy()),
  waiting:()=>currentAgentBusy(),
  enter:enterAgentView,
  target:()=>q('#agentPending')||q('#agentLog'),
  title:'Agent 正在自主调用工具',
  body:'下方实时显示它已经做了哪些步骤，通常 10–30 秒。候选和草稿都要经你确认才生效。',
  done:()=>!currentAgentBusy()&&currentAgentTurns().length>0},
 {id:'agent-tl',phase:'agent',kind:'look',
  skip:()=>Boolean(state?.skipAgent)||!currentAgentTurns().length||!hasAgentTimeline()||(onAgentWorkView()&&!visible(qa('#agentLog .ag-tl').at(-1))),
  enter:enterAgentView,
  target:()=>qa('#agentLog .ag-tl').at(-1)?.closest('.ag-card'),
  title:'看它这一轮做了什么',
  body:'每一行是它真实调用的一个工具和得到的结果：提取了几条候选、价格查到没有、要不要向客户澄清。工具由模型自己选，结果由程序给出。'},
 {id:'agent-conclusion',phase:'agent',kind:'look',
  skip:()=>Boolean(state?.skipAgent)||!currentAgentTurns().length,
  enter:enterAgentView,
  target:()=>qa('#agentLog .agent-msg.bot .agent-text').at(-1),
  title:'它的结论',
  body:'结论里说清提取到哪几行、价格情况、还缺什么信息，以及下一步该由你做什么。下方“回答模型”是实际响应的模型服务。'},
 {id:'agent-draft',phase:'agent',kind:'look',
  skip:()=>Boolean(state?.skipAgent)||!hasAgentDraft()||(onAgentWorkView()&&!visible(qa('#agentLog .agent-draft').at(-1))),
  enter:enterAgentView,
  target:()=>qa('#agentLog .agent-draft').at(-1),
  title:'缺信息时，它起草澄清邮件',
  body:'这封邮件是草稿，发不发、发给谁由你决定。'},
 {id:'agent-next',phase:'agent',kind:'act',
  skip:()=>Boolean(state?.skipAgent)||!generalCands().length,
  enter:()=>{
    if(onAgentWorkView()&&q('#agentNext')){ensureMobileView('work');return}
    if(mobileGuide()){
      if(q('#agentNext')&&focus?.type==='agent')ensureMobileView('work');
      else ensureMobileView('queue');
    }
  },
  target:()=>{
    const next=q('#agentNext');
    if(visible(next))return next;
    const item=q('#queue [data-qtype="cand"]');
    if(visible(item))return item;
    if(visible(q('#queue')))return q('#queue');
    return q('#mobileNav [data-view="queue"]');
  },
  title:'打开它提出的候选',
  body:'点“下一步”或左侧修订候选去审阅。Agent 提取的询价行还不是正式数据，要你核对后才生效。',
  done:()=>focus?.type==='cand'||!generalCands().length},
 {id:'cand-look',kind:'look',
  skip:()=>!generalCands().length,
  enter:enterFirstCand,
  target:()=>q('#work .cfields'),
  title:'每个值都带原文出处',
  body:'询价号、件号、数量、单位、件状旁边都标着来自邮件第几行的哪段原文。点出处可以在右侧原件里高亮核对。'},
 {id:'cand-accept',kind:'act',
  skip:()=>!generalCands().length,
  enter:enterFirstCand,
  fill:()=>{
    const r=q('#work [data-keep="reason"]');
    if(r&&!r.value){r.value='已对照邮件原文核对';r.dispatchEvent(new Event('input',{bubbles:true}))}
    const a=q('#work [data-keep="actor"]');
    if(a&&!a.readOnly&&!a.value){a.value='评委体验';a.dispatchEvent(new Event('input',{bubbles:true}))}
    const c=q('#work .checks input[type=checkbox]');
    if(c&&!c.checked)c.click();
  },
  target:()=>candHasDispute()
    ?[q('#candAccept'),q('#candReject')].filter(Boolean)
    :[q('#work [data-keep="reason"]')||q('#work .checks'),q('#candAcceptBatch')||q('#candAccept')],
  title:'核对后，由你接纳',
  body:()=>candHasDispute()
    ?'当前候选存在需逐条确认或有争议字段：请核对原件后点“接纳为正式行”或“拒绝候选”，也可点“跳过这一步”继续后续步骤。'
    :'理由和勾选已经替你填好，你只要对照右侧原件确认，然后点“接纳本批所有无争议候选”。接纳后它们才成为正式询价行。',
  done:()=>!generalCands().length},
 {id:'parse-review',kind:'act',
  skip:()=>!current?.progress?.pending_parse_review,
  enter:()=>{setFocus('warnings','w');ensureMobileView('work')},
  fill:()=>{
    const t=q('#work textarea[data-keep$="note"],#work textarea[data-keep$="reason"],#work textarea');
    if(t&&!t.value){t.value='已逐行核对原件，没有漏项';t.dispatchEvent(new Event('input',{bubbles:true}))}
  },
  target:()=>[q('#work textarea'),q('#review')],
  title:'确认原件没有漏项',
  body:'结论已经替你写好，对照右侧原件看一眼，点“记录人工核查”即可。',
  done:()=>!current?.progress?.pending_parse_review},
 {id:'price',kind:'act',
  skip:()=>!rows().length||rows().every(r=>r.price),
  enter:()=>{
    const r=rows().find(x=>!x.price);
    if(r)setFocus('price',r.id);
    ensureMobileView('work');
  },
  sync:()=>{
    if(typeof focus==='undefined'||focus?.type!=='price')return;
    const curRow=rows().find(x=>x.id===focus.id);
    const nextUnpriced=rows().find(x=>!x.price);
    if(curRow?.price&&nextUnpriced){
      setFocus('price',nextUnpriced.id);
      ensureMobileView('work');
      lastScroll=-1;
    }
  },
  target:()=>{
    if(typeof focus!=='undefined'&&focus?.type==='price'){
      const curRow=rows().find(x=>x.id===focus.id);
      const nextUnpriced=rows().find(x=>!x.price);
      if(curRow?.price&&nextUnpriced){
        setFocus('price',nextUnpriced.id);
        ensureMobileView('work');
        lastScroll=-1;
      }
    }
    const loadBtn=q('#loadPricesInline')||q('#loadPrices');
    const saveBtn=q('#savePrice');
    const hasSynthetic=Boolean(current?.prices?.some(p=>p.kind==='synthetic'));
    if(loadBtn?.disabled)return q('[data-goto="prices|"]')||q('.note.warn')||loadBtn;
    if(saveBtn?.disabled&&q('#work [data-goto^="row|"]'))return q('#work [data-goto^="row|"]');
    if(hasSynthetic&&saveBtn&&!saveBtn.disabled)return saveBtn;
    return loadBtn||saveBtn;
  },
  title:'补上价格依据',
  body:()=>{
    const loadBtn=q('#loadPricesInline')||q('#loadPrices');
    const saveBtn=q('#savePrice');
    const hasSynthetic=Boolean(current?.prices?.some(p=>p.kind==='synthetic'));
    if(loadBtn?.disabled)return '价格依据总表有待保存修改，快捷载入暂不可用。请先去总表保存或放弃，或点“跳过这一步”。';
    if(saveBtn?.disabled&&q('#work [data-goto^="row|"]'))return '当前行缺少件号、单位或件状，需先回内容核对补齐后才能核价，或点“跳过这一步”。';
    if(hasSynthetic)return '示例价表未覆盖当前件号，缺价行需人工填写单价、有效期和来源后保存；也可先点“跳过这一步”。';
    return 'Agent 查价时已指出缺少有效价格。这里只接受有来源、在有效期内的价格；本次演示可直接载入预置价表。';
  },
  done:()=>rows().length>0&&rows().every(r=>r.price)},
 {id:'approve',kind:'act',
  skip:()=>!rows().length||caseReady(),
  enter:()=>{setFocus('approve','a');ensureMobileView('work')},
  fill:()=>{
    const a=q('#actor');
    if(a&&!a.readOnly&&!a.value){a.value='评委体验';a.dispatchEvent(new Event('input',{bubbles:true}))}
  },
  target:()=>{
    const btn=q('#approve');
    if(!btn||btn.disabled)return q('.checks-list li.bad [data-gate-jump]')||q('.checks-list')||q('#readiness');
    return [q('#actor'),btn];
  },
  title:'检查后，由你批准',
  body:()=>{
    const btn=q('#approve');
    if(!btn||btn.disabled)return '当前工作单仍有阻断项尚未解除，“批准当前版本”暂不可用。可先点上方红色事项旁的“处理”解除阻断，或点“跳过这一步”。';
    return matrixOneConnected()
      ?'批准人绑定当前登录身份。批准把这一版询价、价格和澄清状态锁定，同时在 MatrixOne 存一个快照；之后任何改动都会让批准失效。'
      :'批准人绑定当前登录身份。批准把这一版询价、价格和澄清状态锁定，锁定当前快照与版本记录；之后任何改动都会让批准失效。';
  },
  done:()=>caseReady()},
 {id:'preview',kind:'act',
  skip:()=>!caseReady(),
  enter:()=>{setFocus('output','o');ensureMobileView('work')},
  target:()=>q('#quotePreview'),
  title:'生成报价响应预览',
  body:'服务器会按批准的版本重新核验后渲染报价响应。核对询价号和金额。',
  done:()=>visible(q('#quoteFrame'))},
 {id:'export',kind:'act',
  skip:()=>!caseReady(),
  enter:()=>{if(focus?.type!=='output')setFocus('output','o');ensureMobileView('work')},
  target:()=>q('#exportCsv'),
  title:'导出这一版',
  body:'点“导出 CSV”或“导出 Excel (.xlsx)”。正式输出由服务器再次核验并记录，下载的文件绑定当前批准版本。',
  done:()=>exported(current)},
 {id:'done',kind:'look',
  target:()=>{
    if(!modelEnabled()&&!currentAgentTurns().length){
      const logBtn=q('[data-focus="log"]')||q('.queue-more');
      if(logBtn&&visible(logBtn))return [logBtn];
    }
    return mobileGuide()?[q('#mAgent')]:[q('#agentEntry'),q('#mAgent')];
  },
  title:'体验完成',
  body:()=>{
    const noAgent=!currentAgentTurns().length;
    if(!modelEnabled()&&noAgent){
      if(!rows().length)return '当前处于离线模式且本单尚无正式询价行。可先导入表格/邮件，或在「原件与修订候选」生成离线标签候选，完成核对、核价、批准与导出；随时可在「版本与决策记录」查看本地版本差异。';
      return '已完成离线工作单的核心步骤：核对询价行、补齐价格依据、批准并导出报价。之后可随时在左侧「版本与决策记录」对比本地版本差异与审计记录。';
    }
    if(state?.skipAgent&&noAgent){
      return '已完成人工核对、核价、批准与导出流程。可随时在左侧「版本与决策记录」对比版本差异，或在需要时打开「询价 Agent」继续提问。';
    }
    return 'Agent 读邮件、提候选、查价、起草澄清；你核对、接纳、核价、批准、导出。之后可以随时从这里回到 Agent 继续问它，比如“批准后改过什么”。';
  },next:'完成'},
];

const HOME_STEPS=[
 {id:'home-layout',kind:'look',overview:true,
  target:()=>[q('.ah-hero'),q('.ah-log'),q('.ah-ask')],
  title:'先看一眼布局：从上到下三块',
  body:'最上面是标题和四个入口（收件箱 / 工作单 / 库存与历史 / 导入文件）；中间四张卡是今天的待办数字，卡片可以直接点进去；下面是 Agent 对话和一键提问的输入框。后面几步就按这个顺序走。'},
 {id:'home-brief',kind:'look',
  target:()=>document.querySelector('#ahLog .ah-briefline')||document.querySelector('#ahStats'),
  title:'数字和一句建议',
  body:'上面四张卡是当前账号真实的待办：多少封待分流、多少封 Jev 拿不准、已经初筛了多少。下面这句是系统按这些数字给的建议，没有调用模型。'},
 {id:'home-ask-todo',kind:'act',waiting:()=>!!window.ahState?.busy,
  target:()=>[document.querySelector('#ahInput'),document.querySelector('#ahSend')].filter(Boolean),
  enter:()=>{
    if(!state||state.baseStep!==state.step){state={...state,baseStep:state.step,baseTurns:completedHomeTurns()};save()}
    const i=document.querySelector('#ahInput');
    if(i&&!i.value.trim())i.value='有什么要我审的？';
    if(i&&!mobileGuide())i.focus();
  },
  title:'把问题交给它，看它怎么查',
  body:'问题已经替你填好了，点“发送”。它会去查待办再逐条回答，数字和上面的卡片一致。',
  done:()=>!window.ahState?.busy&&state&&state.baseStep===state.step&&typeof state.baseTurns==='number'&&completedHomeTurns()>state.baseTurns},
 {id:'home-ask-parts',kind:'act',waiting:()=>!!window.ahState?.busy,
  target:()=>[document.querySelector('#ahInput'),document.querySelector('#ahSend')].filter(Boolean),
  enter:()=>{
    if(!state||state.baseStep!==state.step){state={...state,baseStep:state.step,baseTurns:completedHomeTurns()};save()}
    const i=document.querySelector('#ahInput');
    if(i&&!i.value.trim())i.value='液压系统那个密封圈还有多少库存？';
    if(i&&!mobileGuide())i.focus();
  },
  title:'只给描述，也能找件号',
  body:()=>modelEnabled()
    ?'这次只给一句人话，不给件号。它会先做向量检索，列出候选件号、相似度和库位；选哪一个由你定。'
    :'离线模式下会按本地规则与参考库检索候选件号和库位，不调用联网模型；选哪一个由你定。',
  done:()=>!window.ahState?.busy&&state&&state.baseStep===state.step&&typeof state.baseTurns==='number'&&completedHomeTurns()>state.baseTurns},
 {id:'home-inbox',kind:'act',
  target:()=>document.querySelector('[data-ah-go="inbox"]'),
  title:'去收件箱处理真正的询价',
  body:'上面几步是“先看一眼”。真正的处理在收件箱：挑一封询价，让 Jev 分流，再交给工作单。',
  done:()=>isInboxMode()},
];

/* ---------- Account-scoped storage ---------- */
const accountKey=()=>{
  const id=typeof authState!=='undefined'&&authState?.user?.id?authState.user.id:'anon';
  return 'rfq-tour:'+id+':';
};
const flagKey=name=>accountKey()+name;
const getFlag=name=>{try{return Boolean(sessionStorage.getItem(flagKey(name)))}catch{return false}};
const setFlag=name=>{try{sessionStorage.setItem(flagKey(name),'1')}catch{}};
let loadedAccount=null,state=null;
const save=()=>{
  try{
    const k=accountKey()+'state';
    if(state)sessionStorage.setItem(k,JSON.stringify(state));
    else sessionStorage.removeItem(k);
  }catch{}
};
function syncAccountState(){
  if(document.body.dataset.auth!=='ready')return;
  const acct=accountKey();
  if(loadedAccount===acct)return;
  loadedAccount=acct;
  shownCase='';
  entered=-1;lastScroll=-1;waitAt=null;mobileExpanded=false;
  try{
    const raw=sessionStorage.getItem(acct+'state');
    const parsed=raw?JSON.parse(raw):null;
    state=parsed&&typeof parsed==='object'&&Number.isInteger(parsed.step)?parsed:null;
  }catch{state=null}
}
function clearAccountStorage(){
  try{
    const prefix=accountKey();
    const drop=[];
    for(let i=0;i<sessionStorage.length;i++){
      const k=sessionStorage.key(i);
      if(k&&(k.startsWith(prefix)||k==='rfq-spotlight'||/^rfq-(case|home)-tour-(done|declined)$/.test(k)))drop.push(k);
    }
    for(const k of drop)sessionStorage.removeItem(k);
  }catch{}
}

/* ---------- DOM ---------- */
const root=document.createElement('div');root.className='coach';root.hidden=true;
root.innerHTML='<div class="coach-hole"></div><div class="coach-bubble" role="dialog" aria-live="polite"><div class="coach-copy"><div class="coach-count"></div><h3 class="coach-title"></h3><p class="coach-body"></p></div><div class="coach-actions"><button type="button" class="btn btn-primary btn-sm coach-next">下一步</button><button type="button" class="text-btn coach-skip">跳过这一步</button><button type="button" class="text-btn coach-toggle" hidden>展开</button><button type="button" class="text-btn coach-collapse">先收起</button><button type="button" class="text-btn coach-end">结束引导</button></div></div>';
document.body.append(root);

const invite=document.createElement('div');
invite.className='coach-invite';invite.hidden=true;
invite.innerHTML=`<div class="ci-head"><b>要跟着走一遍吗</b><span>${HOME_STEPS.length} 步 · 约 1 分钟</span></div><p class="ci-body">看它怎么汇总待办、怎么用一句描述找到件号，再进收件箱处理询价。</p><div class="ci-acts"><button type="button" class="btn btn-primary btn-sm" data-ci-start>开始</button><button type="button" class="text-btn" data-ci-later>暂不用</button></div>`;
document.body.append(invite);

const pill=document.createElement('button');
pill.type='button';pill.className='coach-reopen';pill.hidden=true;
document.body.append(pill);

const hole=root.querySelector('.coach-hole'),bubble=root.querySelector('.coach-bubble');
const elCount=root.querySelector('.coach-count'),elTitle=root.querySelector('.coach-title'),elBody=root.querySelector('.coach-body');
const btnNext=root.querySelector('.coach-next'),btnSkip=root.querySelector('.coach-skip'),btnToggle=root.querySelector('.coach-toggle');
const setText=(el,val)=>{if(el&&el.textContent!==val)el.textContent=val};
const setHtml=(el,val)=>{if(el&&el.innerHTML!==val)el.innerHTML=val};

let entered=-1,lastScroll=-1,stepAt=Date.now(),waitAt=null,shownCase='',docked=false,mobileExpanded=false;
let highlightedEls=[];
const mainView=()=>['agentHome','landing','desk'].map(id=>document.getElementById(id)).find(el=>el&&!el.hidden);
const hasOverlayOpen=()=>Boolean(
  document.querySelector('dialog[open]')||
  document.querySelector('.drawer:not([hidden]), .drawer.open')||
  document.querySelector('.pop:not([hidden])')||
  document.querySelector('.account-menu[open]')||
  document.body.classList.contains('src-open')
);

function clearGuideTarget(){
  for(const el of highlightedEls)el.classList.remove('guide-target');
  highlightedEls=[];
}
function setGuideTargets(els){
  const next=els||[];
  if(next.length===highlightedEls.length&&next.every((el,i)=>el===highlightedEls[i]))return;
  clearGuideTarget();
  for(const el of next){el.classList.add('guide-target');highlightedEls.push(el)}
}

function isKeyboardOrInput(){
  if(!mobileGuide())return false;
  const vv=window.visualViewport;
  const kbOpen=Boolean(vv&&vv.height<innerHeight*0.72);
  const act=document.activeElement;
  const inField=Boolean(act&&act.matches&&act.matches('input,textarea,select')&&!act.closest('.coach'));
  return kbOpen||inField;
}

function syncMobileDock(){
  const activeBubble=Boolean(state&&!state.min&&!root.hidden);
  const showInviteNow=!invite.hidden;
  // Pill alone never locks the page into coach-docked viewport mode.
  const next=mobileGuide()&&document.body.dataset.auth==='ready'&&(activeBubble||showInviteNow);
  const view=mainView(),previousScroll=docked?(view?.scrollTop||0):scrollY;
  const h=Math.min(innerHeight,window.visualViewport?.height||innerHeight);
  const hPx=Math.round(h)+'px';
  if(document.body.style.getPropertyValue('--coach-viewport-height')!==hPx){
    document.body.style.setProperty('--coach-viewport-height',hPx);
  }
  document.body.classList.toggle('coach-docked',next);
  if(next!==docked){
    docked=next;
    if(next){window.scrollTo(0,0);if(view)view.scrollTop=previousScroll}
    else window.scrollTo(0,previousScroll);
  }
  const kb=activeBubble&&isKeyboardOrInput();
  if(!kb)mobileExpanded=false;
  const compact=Boolean(kb&&!mobileExpanded);
  bubble.classList.toggle('is-compact',compact);
  btnToggle.hidden=!kb;
  setText(btnToggle,compact?'展开':'精简');
}

function targets(step){
  const raw=typeof step.target==='function'?step.target():step.target;
  return [raw].flat().filter(visible);
}
function overlapArea(ax,ay,aw,ah,b){
  if(!b||b.right<=b.left||b.bottom<=b.top)return 0;
  const x=Math.max(0,Math.min(ax+aw,b.right)-Math.max(ax,b.left));
  const y=Math.max(0,Math.min(ay+ah,b.bottom)-Math.max(ay,b.top));
  return x*y;
}

function place(step){
  const els=targets(step);
  if(mobileGuide()){
    hole.hidden=true;
    if(bubble.style.cssText)bubble.style.cssText='';
    setGuideTargets(step.overview?[]:els);
    if(els.length&&lastScroll!==state.step){
      lastScroll=state.step;
      requestAnimationFrame(()=>{
        const alive=els.filter(e=>e?.isConnected);
        if(!state||!alive.length)return;
        try{
          const view=mainView();
          const vRect=view&&visible(view)?view.getBoundingClientRect():null;
          const visTop=vRect?Math.max(vRect.top+8,0):64;
          const visBottom=vRect?Math.min(vRect.bottom-8,innerHeight):innerHeight-180;
          const boxes=alive.map(e=>e.getBoundingClientRect());
          const minTop=Math.min(...boxes.map(b=>b.top));
          const maxBottom=Math.max(...boxes.map(b=>b.bottom));
          if(minTop<visTop||maxBottom>visBottom){
            const bottomClipped=alive.length>1&&maxBottom>visBottom&&minTop>=visTop;
            const targetEl=bottomClipped?alive[alive.length-1]:alive[0];
            targetEl.scrollIntoView({block:bottomClipped?'end':'center',inline:'nearest',behavior:'instant'});
          }
        }catch{}
      });
    }
    return;
  }
  clearGuideTarget();
  const W=innerWidth,H=innerHeight,gap=14,topBar=72;
  const clamp=(x,y,bw,bh)=>[Math.max(12,Math.min(x,W-bw-12)),Math.max(12,Math.min(y,H-bh-12))];
  const measureHeight=bw=>{
    bubble.style.width=bw+'px';
    return Math.min(bubble.offsetHeight||190,H-24);
  };
  if(!els.length){
    hole.hidden=true;
    const bw=Math.min(360,W-24),bh=measureHeight(bw);
    const [left,top]=clamp(Math.round((W-bw)/2),Math.round((H-bh)*0.38),bw,bh);
    bubble.style.left=left+'px';bubble.style.top=top+'px';bubble.style.transform='';
    return;
  }
  const rs=els.map(e=>e.getBoundingClientRect()),pad=8;
  const r={left:Math.min(...rs.map(x=>x.left))-pad,top:Math.min(...rs.map(x=>x.top))-pad,right:Math.max(...rs.map(x=>x.right))+pad,bottom:Math.max(...rs.map(x=>x.bottom))+pad};
  const wide=Boolean(step.overview)||(r.right-r.left)*(r.bottom-r.top)>W*H*0.55;
  const wrap=document.querySelector('.ah-wrap');
  const homeSidebarRoom=(!state.caseId&&wrap&&visible(wrap))?Math.round(W-wrap.getBoundingClientRect().right):0;

  if(wide){
    hole.hidden=true;
    if(homeSidebarRoom>=260){
      const wr=wrap.getBoundingClientRect();
      const tw=Math.min(homeSidebarRoom-20,340),bh=measureHeight(tw);
      const [left,top]=clamp(Math.round(wr.right+10),Math.round((H-bh)/2),tw,bh);
      bubble.style.left=left+'px';bubble.style.top=top+'px';bubble.style.transform='';
      return;
    }
    const bw=Math.min(340,W-24),bh=measureHeight(bw);
    const avoid=qa('.btn-primary,#ahForm,#agentForm').filter(e=>visible(e)&&!e.closest('.coach,.coach-invite,.coach-reopen')).map(e=>e.getBoundingClientRect());
    const wideSpots=[[W-bw-18,topBar],[18,topBar],[18,H-bh-18],[W-bw-18,H-bh-18]].map(([x,y])=>clamp(x,y,bw,bh));
    const best=wideSpots.reduce((acc,pos)=>{
      const score=avoid.reduce((s,b)=>s+overlapArea(pos[0],pos[1],bw,bh,b),0);
      return !acc||score<acc.score?{pos,score}:acc;
    },null);
    const [left,top]=best?best.pos:wideSpots[0];
    bubble.style.left=left+'px';bubble.style.top=top+'px';bubble.style.transform='';
    return;
  }

  const topEl=q('.top');
  const headerBottom=Math.max(60,Math.round(topEl&&visible(topEl)?topEl.getBoundingClientRect().bottom:60));
  const holeLeft=Math.max(0,r.left);
  const holeTop=Math.max(headerBottom,r.top);
  const holeBottom=Math.min(H-4,r.bottom);
  const holeHeight=Math.max(0,holeBottom-holeTop);
  const holeWidth=Math.max(0,r.right-holeLeft);
  hole.hidden=hasOverlayOpen()||holeHeight<=0||holeWidth<=0;
  Object.assign(hole.style,{left:holeLeft+'px',top:holeTop+'px',width:holeWidth+'px',height:holeHeight+'px'});

  if(homeSidebarRoom>=260){
    const wr=wrap.getBoundingClientRect();
    const tw=Math.min(homeSidebarRoom-20,340),bh=measureHeight(tw);
    const [left,top]=clamp(Math.round(wr.right+10),Math.round((H-bh)/2),tw,bh);
    bubble.style.left=left+'px';bubble.style.top=top+'px';bubble.style.transform='';
  }else{
    const bw=Math.min(340,W-24),bh=measureHeight(bw);
    const src=document.querySelector('.source')?.getBoundingClientRect();
    const over=(x,y,b)=>overlapArea(x,y,bw,bh,b)>0;
    const spots=[
      [r.left,r.bottom+gap],
      [r.left,r.top-gap-bh],
      [r.right+gap,r.top],
      [r.left-gap-bw,r.top],
      [r.right-bw,r.bottom+gap],
      [r.right-bw,r.top-gap-bh],
      [W-bw-12,topBar],
      [12,topBar],
      [12,H-bh-12],
      [W-bw-12,H-bh-12],
    ].map(([x,y])=>clamp(x,y,bw,bh));

    const ok=spots.filter(([x,y])=>!over(x,y,r));
    const clear=spots.filter(([x,y])=>!rs.some(b=>over(x,y,b)));
    let picked=ok.find(([x,y])=>!over(x,y,src))||ok[0]||clear.find(([x,y])=>!over(x,y,src))||clear[0];
    if(!picked){
      picked=spots.reduce((acc,pos)=>{
        const score=rs.reduce((s,b)=>s+overlapArea(pos[0],pos[1],bw,bh,b),0)+overlapArea(pos[0],pos[1],bw,bh,r)*0.1;
        return !acc||score<acc.score?{pos,score}:acc;
      },null).pos;
    }
    bubble.style.left=Math.round(picked[0])+'px';
    bubble.style.top=Math.round(picked[1])+'px';
    bubble.style.transform='';
  }

  if(lastScroll!==state.step){
    lastScroll=state.step;
    requestAnimationFrame(()=>{
      const alive=els.filter(e=>e?.isConnected);
      if(!state||!alive.length)return;
      try{
        const boxes=alive.map(e=>e.getBoundingClientRect());
        const minTop=Math.min(...boxes.map(b=>b.top));
        const maxBottom=Math.max(...boxes.map(b=>b.bottom));
        const safeTop=Math.max(headerBottom+12,72);
        const safeBottom=innerHeight-24;
        if(minTop<safeTop||maxBottom>safeBottom){
          const bottomClipped=alive.length>1&&maxBottom>safeBottom&&minTop>=safeTop;
          const targetEl=bottomClipped?alive[alive.length-1]:(maxBottom>safeBottom&&alive.length>1?alive[alive.length-1]:alive[0]);
          targetEl.scrollIntoView({block:bottomClipped?'end':'center',inline:'nearest',behavior:'smooth'});
        }
      }catch{}
    });
  }
}

function steps(){return state&&!state.caseId?HOME_STEPS:STEPS}

function effectiveSteps(list){
  if(!state||!state.caseId)return list;
  const visited=new Set(Array.isArray(state.visited)?state.visited:[]);
  const cur=list[state.step];
  const agentSkipped=Boolean(state.skipAgent)||(!modelEnabled()&&!currentAgentTurns().length&&!currentAgentBusy());
  const agentPending=!agentSkipped&&!currentAgentTurns().length;
  const hasCands=generalCands().length>0;
  const hasRows=rows().length>0;
  const willHaveRows=hasRows||hasCands||agentPending;
  return list.filter((s,i)=>{
    if(cur&&s.id===cur.id)return true;
    if(visited.has(s.id))return true;
    if(i<state.step)return false;
    if(s.id==='layout'||s.id==='done')return true;
    if(s.phase==='agent'){
      if(agentSkipped)return false;
      if(s.id==='agent-tl')return agentPending||hasAgentTimeline();
      if(s.id==='agent-draft')return hasAgentDraft();
      if(s.id==='agent-next')return agentPending||hasCands;
      return !s.skip?.();
    }
    if(s.id==='cand-look'||s.id==='cand-accept')return hasCands||(agentPending&&!hasRows);
    if(s.id==='parse-review')return Boolean(current?.progress?.pending_parse_review);
    if(s.id==='price')return willHaveRows&&(!hasRows||!rows().every(r=>r.price));
    if(s.id==='approve')return willHaveRows&&!caseReady();
    if(s.id==='preview'||s.id==='export')return willHaveRows;
    return !s.skip?.();
  });
}

function end(completed=false){
  if(state)setFlag(state.caseId?'case-'+(completed?'done':'declined'):'home-'+(completed?'done':'declined'));
  state=null;save();
  root.hidden=true;pill.hidden=true;
  document.body.classList.remove('coaching');
  clearGuideTarget();
  syncMobileDock();
  syncListeners();
}
function go(i,extra={}){
  state={...state,...extra,step:i,skipped:0};
  delete state.baseStep;delete state.baseTurns;
  entered=-1;lastScroll=-1;mobileExpanded=false;
  save();
}

btnNext.onclick=()=>{if(!state)return;if(state.step+1>=steps().length)end(true);else{go(state.step+1);tick()}};
btnSkip.onclick=()=>{
  if(!state)return;
  const list=steps(),cur=list[state.step];
  // Semantic check for skipping the Agent send / wait phase: never bounce back in a loop!
  if(state.caseId&&cur&&(cur.enter===toAgent||cur.id==='agent-wait')&&(!currentAgentTurns().length||currentAgentBusy())){
    if(!hasCaseWork()){
      end(false);
      if(typeof notice==='function'){
        notice(currentAgentBusy()
          ?'Agent 仍在后台运行；已结束引导，处理完成后可从左侧「操作引导」继续。'
          :!modelEnabled()
          ?'当前为离线模式且本单尚无正式询价行：可先在「原件与修订候选」生成离线标签候选，或启用模型后再从「操作引导」开始。'
          :'本单尚无正式询价行或待审候选：可先手动核对原件或生成候选，随时可从「操作引导」重新开始。');
      }
      return;
    }
    const afterAgent=list.findIndex(s=>s.phase!=='agent'&&s.id!=='layout');
    go(afterAgent>=0?afterAgent:state.step+1,{skipAgent:true});
    tick();
    return;
  }
  if(state.step+1>=list.length)end(true);
  else{go(state.step+1);tick()}
};
root.querySelector('.coach-end').onclick=()=>end(false);
btnToggle.onclick=()=>{mobileExpanded=!mobileExpanded;syncMobileDock()};
root.querySelector('.coach-collapse').onclick=()=>{if(!state)return;state={...state,min:true};save();clearGuideTarget();tick()};

const reopen=pill;
reopen.onclick=()=>{
  if(!state){
    const cid=pill.dataset.caseId||'';
    const desk=document.getElementById('desk');
    const inSameCase=Boolean(cid&&typeof current!=='undefined'&&current?.id===cid&&desk&&!desk.hidden);
    state={caseId:inSameCase?cid:null,step:0};
  }
  if(!state.caseId)ensureHome();
  entered=-1;lastScroll=-1;stepAt=state.stepAt||Date.now();
  state={...state,min:false};save();
  setTimeout(tick,80);
};
invite.querySelector('[data-ci-start]').onclick=()=>{
  const cid=invite.dataset.caseId||null;
  if(!cid)ensureHome();
  invite.hidden=true;pill.hidden=true;pill.dataset.caseId='';
  const skipAgent=Boolean(cid&&!modelEnabled()&&!currentAgentTurns().length&&!currentAgentBusy());
  if(skipAgent&&!hasCaseWork()){
    if(typeof notice==='function')notice('当前为离线模式且本单尚无正式询价行：请先在「原件与修订候选」生成离线标签候选或导入表格。');
    syncMobileDock();syncListeners();return;
  }
  state={caseId:cid,step:0,...(skipAgent?{skipAgent:true}:{})};
  entered=-1;lastScroll=-1;stepAt=Date.now();save();
  setTimeout(tick,80);
};
invite.querySelector('[data-ci-later]').onclick=()=>{
  invite.hidden=true;
  const cid=invite.dataset.caseId||'';
  setFlag(cid?'case-declined':'home-declined');
  pill.dataset.caseId=cid;
  setText(pill,'继续引导');
  pill.hidden=false;
  syncMobileDock();
  syncListeners();
};
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&!e._rfqOverlayEscape&&!e.defaultPrevented&&state&&!state.min&&!hasOverlayOpen())end(false);
});

function ensureHome(){
  const home=document.getElementById('agentHome');
  if(home&&home.hidden&&typeof window.showHome==='function')window.showHome();
}

function renderTick(){
  if(document.body.dataset.auth!=='ready'){
    root.hidden=true;invite.hidden=true;pill.hidden=true;
    document.body.classList.remove('coaching');
    clearGuideTarget();
    return;
  }
  syncAccountState();
  if(!state){
    root.hidden=true;document.body.classList.remove('coaching');clearGuideTarget();
    return;
  }
  if(state.caseId&&(typeof current==='undefined'||!current||current.id!==state.caseId)){
    root.hidden=true;pill.hidden=true;document.body.classList.remove('coaching');clearGuideTarget();
    return;
  }
  if(!state.caseId){
    const home=document.getElementById('agentHome');
    const desk=document.getElementById('desk');
    const curStep=HOME_STEPS[state.step];
    if(curStep?.kind==='act'&&curStep.done?.()){
      if(state.step+1>=HOME_STEPS.length){end(true);return}
      go(state.step+1);
    }
    if(!home||home.hidden){
      root.hidden=true;document.body.classList.remove('coaching');clearGuideTarget();
      if(desk&&!desk.hidden&&typeof current!=='undefined'&&current?.id){
        // Entered a work order: drop unfinished home tour so case invite can work cleanly.
        state=null;save();pill.hidden=true;
      }
      return;
    }
  }

  const list=steps();
  let autoSkipped=0;
  while(list[state.step]){
    const cur=list[state.step];
    const visited=Array.isArray(state.visited)?[...state.visited]:[];
    const wasEntered=visited.includes(cur.id);
    const isDone=wasEntered&&cur.kind==='act'&&Boolean(cur.done?.());
    const isSkip=!isDone&&(Boolean(cur.skip?.())||(cur.kind==='act'&&Boolean(cur.done?.())));
    if(!isDone&&!isSkip)break;
    if(isSkip)autoSkipped++;
    state={...state,step:state.step+1,visited,skipped:isDone?0:(state.skipped||0)};
    delete state.baseStep;delete state.baseTurns;
    entered=-1;lastScroll=-1;mobileExpanded=false;
    save();
  }
  if(autoSkipped&&state){state={...state,skipped:(state.skipped||0)+autoSkipped};save()}
  const step=list[state.step];
  if(!step){end(true);return}

  if(state.caseId&&step.waiting&&!currentAgentBusy()&&!currentAgentTurns().length&&!state.skipAgent){
    const sendIdx=STEPS.findIndex(s=>s.enter===toAgent);
    if(sendIdx>=0&&modelEnabled()){go(sendIdx);return}
  }

  if(entered!==state.step){
    entered=state.step;stepAt=Date.now();waitAt=null;mobileExpanded=false;
    const visited=Array.isArray(state.visited)?[...state.visited]:[];
    if(!visited.includes(step.id)){visited.push(step.id);state={...state,visited};save()}
    step.enter?.();
    try{step.fill?.()}catch{}
  }
  step.sync?.();

  const plan=effectiveSteps(list);
  const displayIdx=Math.max(0,plan.findIndex(s=>s.id===step.id));
  const displayStep=displayIdx+1,displayTotal=plan.length||1;

  root.hidden=false;
  if(state.min){
    hole.hidden=true;bubble.hidden=true;reopen.hidden=false;
    setHtml(reopen,`继续引导 · <b class="coach-reopen-count">${displayStep} / ${displayTotal}</b>`);
    document.body.classList.remove('coaching');
    clearGuideTarget();
    return;
  }
  document.body.classList.add('coaching');
  bubble.hidden=false;reopen.hidden=true;

  const countText=`${state.caseId?'3 分钟体验':'工作区导览'} · ${displayStep} / ${displayTotal}`;
  setText(elCount,countText);
  setText(elTitle,step.title);

  const waiting=Boolean(step.waiting?.());
  if(waiting&&waitAt===null)waitAt=Date.now();else if(!waiting)waitAt=null;
  const waited=waiting?Math.round((Date.now()-waitAt)/1000):0;
  const rawBody=typeof step.body==='function'?step.body():step.body;
  const bodyText=((mobileGuide()&&step.mobileBody)||rawBody)+(waited>=6?`（已进行 ${waited} 秒，工具调用多时会久一些）`:'');
  setText(elBody,bodyText);

  btnNext.hidden=step.kind!=='look';
  setText(btnNext,step.next||'下一步');
  btnSkip.hidden=step.kind!=='act';

  place(step);

  const busy=(typeof window.ahState!=='undefined'&&window.ahState.busy)||currentAgentBusy();
  if(busy||hasOverlayOpen()){hole.hidden=true;bubble.hidden=false}
  if(entered===state.step&&!targets(step).length&&state.step===0){
    setTimeout(()=>{if(state&&state.step===0&&!root.hidden&&!state.min)place(steps()[0])},120);
  }
}

/* ---------- Throttled listeners (attached only when active) ---------- */
let rafId=0,listenersBound=false;
function scheduleTick(){
  if(rafId)return;
  rafId=requestAnimationFrame(()=>{rafId=0;tick()});
}
function onFocusChange(){scheduleTick()}
function syncListeners(){
  const needed=Boolean(state||!invite.hidden||!pill.hidden);
  if(needed&&!listenersBound){
    listenersBound=true;
    addEventListener('resize',scheduleTick);
    addEventListener('scroll',scheduleTick,true);
    window.visualViewport?.addEventListener('resize',scheduleTick);
    document.addEventListener('focusin',onFocusChange,true);
    document.addEventListener('focusout',onFocusChange,true);
  }else if(!needed&&listenersBound){
    listenersBound=false;
    removeEventListener('resize',scheduleTick);
    removeEventListener('scroll',scheduleTick,true);
    window.visualViewport?.removeEventListener('resize',scheduleTick);
    document.removeEventListener('focusin',onFocusChange,true);
    document.removeEventListener('focusout',onFocusChange,true);
  }
}

function tick(){
  try{renderTick()}finally{syncMobileDock();syncListeners()}
}
setInterval(tick,300);

function showInvite(caseId){
  if(document.body.dataset.auth!=='ready')return;
  invite.dataset.caseId=caseId||'';
  if(caseId){
    invite.querySelector('.ci-head b').textContent='要看一遍这张单怎么处理吗';
    invite.querySelector('.ci-head span').textContent='约 2 分钟';
    invite.querySelector('.ci-body').textContent=modelEnabled()
      ?'从三栏布局讲起，再走一遍提取、核对、核价、批准和导出。'
      :'从三栏布局讲起，再走一遍核对、核价、批准和导出（离线模式自动跳过联网 Agent）。';
  }else{
    invite.querySelector('.ci-head b').textContent='要跟着走一遍吗';
    invite.querySelector('.ci-head span').textContent=HOME_STEPS.length+' 步 · 约 1 分钟';
    invite.querySelector('.ci-body').textContent='看它怎么汇总待办、怎么用一句描述找到件号，再进收件箱处理询价。';
  }
  invite.hidden=false;pill.hidden=true;
  syncMobileDock();
  syncListeners();
}

// 任何路径打开工作单都会走到这里：安静地看一眼，只问一次。
setInterval(()=>{
  try{
    if(document.body.dataset.auth!=='ready')return;
    syncAccountState();
    const desk=document.getElementById('desk');
    if(!desk||desk.hidden)return;
    const cid=(typeof current!=='undefined'&&current&&current.id)?current.id:'';
    if(!cid||cid===shownCase||state||!invite.hidden)return;
    if(getFlag('case-done')||getFlag('case-declined'))return;
    shownCase=cid;showInvite(cid);
  }catch{}
},800);

window.rfqSpotlight={
  start(caseId,opts={}){
    syncAccountState();
    if(!caseId)ensureHome();
    invite.hidden=true;pill.hidden=true;pill.dataset.caseId='';
    state={caseId:caseId||null,step:0,...(opts.skipAgent?{skipAgent:true}:{})};
    entered=-1;lastScroll=-1;stepAt=Date.now();mobileExpanded=false;save();
    tick();
  },
  active:()=>Boolean(state),
  invite(caseId){showInvite(caseId||null)},
  inviteCase(caseId){showInvite(caseId)},
  maybeInviteHome(){
    try{
      if(document.body.dataset.auth!=='ready')return;
      syncAccountState();
      if(getFlag('home-done')||getFlag('home-declined')||state)return;
      showInvite(null);
    }catch{}
  },
  maybeInviteCase(caseId){
    try{
      if(document.body.dataset.auth!=='ready'||!caseId)return;
      syncAccountState();
      if(getFlag('case-done')||getFlag('case-declined'))return;
      if(state&&(!state.caseId||state.caseId!==caseId)){state=null;save();root.hidden=true;pill.hidden=true;pill.dataset.caseId='';document.body.classList.remove('coaching');clearGuideTarget()}
      if(state)return;
      shownCase=caseId;
      showInvite(caseId);
    }catch{}
  },
  onCaseSwitch(newCaseId){
    if(!newCaseId)return;
    syncAccountState();
    if(state&&state.caseId!==newCaseId){
      state=null;save();
      entered=-1;lastScroll=-1;waitAt=null;mobileExpanded=false;
      root.hidden=true;pill.hidden=true;pill.dataset.caseId='';
      document.body.classList.remove('coaching');clearGuideTarget();
    }else if(pill.dataset.caseId&&pill.dataset.caseId!==newCaseId){
      pill.hidden=true;pill.dataset.caseId='';
    }
    if(!invite.hidden&&invite.dataset.caseId!==newCaseId)invite.hidden=true;
    if(shownCase&&shownCase!==newCaseId)shownCase='';
    syncMobileDock();
    syncListeners();
  },
  dismiss(){
    invite.hidden=true;
    const desk=document.getElementById('desk');
    const curId=(typeof current!=='undefined'&&current?.id)?current.id:'';
    if(state&&state.caseId&&(!desk||desk.hidden||curId!==state.caseId)){
      state=null;save();root.hidden=true;pill.hidden=true;pill.dataset.caseId='';
      document.body.classList.remove('coaching');clearGuideTarget();
    }else if(pill.dataset.caseId&&(!desk||desk.hidden||curId!==pill.dataset.caseId)){
      pill.hidden=true;pill.dataset.caseId='';
    }
    syncMobileDock();
    syncListeners();
  },
  sync(){tick()},
  reset(clearStorage=false){
    if(clearStorage)clearAccountStorage();
    state=null;entered=-1;lastScroll=-1;waitAt=null;shownCase='';loadedAccount=null;mobileExpanded=false;
    root.hidden=true;invite.hidden=true;pill.hidden=true;pill.dataset.caseId='';
    document.body.classList.remove('coaching','coach-docked');
    clearGuideTarget();
    syncListeners();
  },
  _debug:{tick,place,steps,effectiveSteps,completedHomeTurns,candHasDispute,hasOverlayOpen,getState:()=>state,root,invite,pill,hole,bubble,STEPS,HOME_STEPS},
};
})();
