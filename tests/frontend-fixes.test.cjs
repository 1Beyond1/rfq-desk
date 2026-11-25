const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const readWeb=name=>fs.readFileSync(path.join(__dirname,'../apps/web',name),'utf8');

test('P2-9: highlightSourceText never corrupts <mark> tags or HTML entities',()=>{
  const appSrc=readWeb('app.js');
  const start=appSrc.indexOf('function highlightSourceText(');
  const end=appSrc.indexOf('window.rfqHighlightSourceText=');
  const ctx={esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
  vm.createContext(ctx);
  vm.runInContext(appSrc.slice(start,end),ctx);

  // Quote containing 'mark' or '<mark>' or 'amp' must never corrupt inserted <mark> or &amp;
  const out1=ctx.highlightSourceText('Part A & amp <mark> mark',new Set(['mark','a','amp','<mark>']));
  assert.equal(out1.match(/<mark>/g).length,out1.match(/<\/mark>/g).length);
  assert.doesNotMatch(out1,/<m<mark>|&<mark>amp|<mark>[^<]*<mark>/);
  assert.match(out1,/<mark>&lt;mark&gt;<\/mark>/);
  assert.match(out1,/<mark>amp<\/mark>/);
  assert.match(out1,/&amp;/);

  const out2=ctx.highlightSourceText('PN-100 QTY 5 EA',new Set(['PN-100','EA']));
  assert.equal(out2,'<mark>PN-100</mark> QTY 5 <mark>EA</mark>');
});

test('P2-9: formatIntakeError renders structured {line, message} errors without [object Object]',()=>{
  const workSrc=readWeb('work.js');
  const start=workSrc.indexOf('function formatIntakeError(');
  const end=workSrc.indexOf('window.rfqFormatIntakeError=');
  const ctx={};
  vm.createContext(ctx);
  vm.runInContext(workSrc.slice(start,end),ctx);

  assert.equal(ctx.formatIntakeError({line:3,message:'单价格式无效'}),'第 3 行：单价格式无效');
  assert.equal(ctx.formatIntakeError({message:'没有价目行'}),'没有价目行');
  assert.equal(ctx.formatIntakeError('纯文本错误'),'纯文本错误');
  assert.doesNotMatch(ctx.formatIntakeError({line:1,message:'x'}),/object Object/);
});

test('P2-9 & F6: quoteFrame uses sandbox without allow-scripts and work.js avoids regex lookbehind',()=>{
  const workSrc=readWeb('work.js');
  const m=workSrc.match(/<iframe[^>]*id="quoteFrame"[^>]*>/);
  assert(m,'expected quoteFrame iframe');
  assert.match(m[0],/sandbox="[^"]*allow-same-origin[^"]*"/);
  assert.doesNotMatch(m[0],/allow-scripts/);
  assert.doesNotMatch(workSrc,/\(\?<=/,'work.js must not use regex lookbehind for Safari compatibility');
});

test('F1: deskInbox switches to cases view before loading inbox',()=>{
  const onsiteSrc=readWeb('onsite.js');
  assert.match(onsiteSrc,/\$\('deskInbox'\)\.onclick=\(\)=>\{showCases\(\);run\(\(\)=>showInbox\(\)\)\}/);
});

test('F6: RfqDialog.open handles concurrent calls without InvalidStateError',async()=>{
  let showCalls=0,closeCalls=0;
  const host={
    id:'',open:false,innerHTML:'',
    _map:new Map(),
    querySelector(sel){
      if(!this._map.has(sel))this._map.set(sel,{textContent:'',className:'',hidden:false,replaceChildren(){},append(){},focus(){},onsubmit:null});
      return this._map.get(sel);
    },
    querySelectorAll:()=>[],
    addEventListener(){},
    showModal(){if(this.open)throw Error('InvalidStateError');this.open=true;showCalls++},
    close(){this.open=false;closeCalls++},
  };
  const ctx={
    document:{
      createElement:()=>host,
      body:{append(){}},
      createTextNode:t=>t,
    },
  };
  vm.createContext(ctx);
  vm.runInContext(readWeb('dialog.js')+';this.RfqDialog=RfqDialog;',ctx);

  const p1=ctx.RfqDialog.confirm({title:'First'});
  assert.equal(host.open,true);
  const p2=ctx.RfqDialog.confirm({title:'Second'});
  assert.equal(await p1,false,'first dialog resolved as cancelled');
  assert.equal(showCalls,2);
  assert.equal(closeCalls,1);
  // Resolve second dialog via submit
  host.querySelector('#askForm').onsubmit({preventDefault(){}});
  assert.equal(await p2,true);
});

test('F3: 401 session expiry preserves localDrafts while explicit logout clears localDrafts and all caches',()=>{
  const accSrc=readWeb('accounts.js');
  const start=accSrc.indexOf('let accountReloading=false');
  const end=accSrc.indexOf('async function accountFetch(');
  let localCleared=0,keptPersistedCleared=0,workCleared=0,homeReset=0,onsiteReset=0,spotReset=0,reloaded=0;
  const ctx={
    rowDrafts:new Map([['a',1]]),pendingRowValues:new Map([['b',1]]),priceDrafts:new Map([['c',1]]),
    kept:{clear(){},clearPersisted(){keptPersistedCleared++}},
    localDrafts:{clear(){localCleared++}},
    authState:{required:true,user:{id:'u1'}},
    current:{id:'c1'},caseList:[{id:'c1'}],materials:{caseId:'c1',revision:1,files:[{}],error:''},
    interaction:{navigate(){}},
    document:{querySelectorAll:()=>[],body:{dataset:{auth:'ready'}}},
    $:()=>({replaceChildren(){}}),
    browserStorage:{setItem(){}},
    location:{reload(){reloaded++}},
    window:{
      clearWorkCaches(){workCleared++},
      resetAgentHomeState(){homeReset++},
      resetOnsiteState(){onsiteReset++},
      rfqSpotlight:{reset(){spotReset++}},
    },
  };
  vm.createContext(ctx);
  vm.runInContext(accSrc.slice(start,end),ctx);

  // 401 expiry: clearAccountMemory(false) must preserve localDrafts and persisted kept
  ctx.clearAccountMemory(false);
  assert.equal(localCleared,0);
  assert.equal(keptPersistedCleared,0);
  assert.equal(workCleared,1);
  assert.equal(homeReset,1);
  assert.equal(onsiteReset,1);
  assert.equal(spotReset,1);

  // Explicit logout: clearAccountMemory(true) clears localDrafts and persisted kept
  ctx.clearAccountMemory(true);
  assert.equal(localCleared,1);
  assert.equal(keptPersistedCleared,1);
});

test('F4 & P2-6: home.js shows retry on overview error, protects pending turn during busy ahLoad, and asks consent only on >120 chars',async()=>{
  const elements=new Map();
  const el=id=>{
    if(!elements.has(id))elements.set(id,{id,value:'',disabled:false,hidden:false,textContent:'',innerHTML:'',classList:{add(){},remove(){}},addEventListener(){},querySelectorAll(){return []},replaceChildren(){}});
    return elements.get(id);
  };
  let confirmCalls=0,confirmResult=false;
  const sentBodies=[];
  const notices=[];
  const ctx={
    window:{renderAgentReferences:()=>''},
    document:{querySelectorAll:()=>[],getElementById:id=>el(id)},
    $:el,
    authState:{user:{id:'u1',role:'demo'}},
    notice:m=>notices.push(m),
    RfqDialog:{confirm:async()=>{confirmCalls++;return confirmResult}},
    request:async(path,opts)=>{
      if(path==='/agent/overview')throw Error('网络超时');
      if(path==='/agent/home'&&opts?.method==='POST'){
        sentBodies.push(JSON.parse(opts.body));
        return {turn:{message:JSON.parse(opts.body).message,reply:'ok',steps:[]}};
      }
      return {turns:[]};
    },
    run:fn=>fn(),
    setTimeout,
    sessionStorage:{getItem:()=>null},
    showCases(){},workspaceMode(){},showInbox(){},renderReferences(){},
  };
  vm.createContext(ctx);
  vm.runInContext(readWeb('home.js'),ctx);

  // Overview failure displays error + retry button instead of stuck loading
  await vm.runInContext('ahLoad()',ctx);
  assert.match(el('ahSub').innerHTML,/待办读取失败/);
  assert.match(el('ahSub').innerHTML,/ahRetryOverview/);

  // Demo role clicking import shows notice instead of triggering upload
  vm.runInContext('ahOpen("import")',ctx);
  assert.equal(notices.length,1);
  assert.match(notices[0],/正式账号/);

  // Short question sends consent: false without confirmation popup
  await vm.runInContext('ahAsk("今天有哪些待办？")',ctx);
  assert.equal(confirmCalls,0);
  assert.equal(sentBodies[0].consent,false);

  // Long question (>120 chars) asks explicit consent; declining aborts and preserves input
  const longText='请帮我审阅这封真实客户邮件：'+'A'.repeat(130);
  await vm.runInContext(`ahAsk(${JSON.stringify(longText)})`,ctx);
  assert.equal(confirmCalls,1);
  assert.equal(sentBodies.length,1,'declined long message must not be sent');
  assert.equal(el('ahInput').value,longText);

  // Confirming long question sends consent: true
  confirmResult=true;
  el('ahInput').value='';
  await vm.runInContext(`ahAsk(${JSON.stringify(longText)})`,ctx);
  assert.equal(confirmCalls,2);
  assert.equal(sentBodies.length,2);
  assert.equal(sentBodies[1].consent,true);

  // ahLoad during busy must NOT overwrite pending turn
  vm.runInContext('ahState.busy=true; ahState.turns=[{message:"pending",pending:true}]',ctx);
  await vm.runInContext('ahLoad()',ctx);
  assert.equal(vm.runInContext('ahState.turns.length',ctx),1);
  assert.equal(vm.runInContext('ahState.turns[0].pending',ctx),true);
});

test('M1-M6 & S5: style.css preserves mobile layout, cascade order, iOS 16px inputs, and auth-hidden spotlight',()=>{
  const css=readWeb('style.css');
  // M1: no conflicting #activityBtn::before{content:"记录"!important}
  assert.doesNotMatch(css,/#activityBtn::before\s*\{\s*content:\s*"记录"\s*!important/);
  assert.match(css,/#activityBtn\{[^}]*min-width:\s*38px/);
  // M2: fixed centered .pop on mobile
  assert.match(css,/\.pop\{position:fixed;left:12px;right:12px;top:60px/);
  // M4: safe area bottom padding on .desk
  assert.match(css,/padding-bottom:\s*calc\(74px \+ env\(safe-area-inset-bottom\)\)/);
  // M5: mobile .ah-ask{position:static} appears AFTER desktop .ah-ask{position:sticky}
  const stickyIdx=css.lastIndexOf('.ah-ask{position:sticky');
  const staticIdx=css.lastIndexOf('.ah-ask{position:static}');
  assert(staticIdx>stickyIdx,'mobile .ah-ask{position:static} must come after desktop sticky rule');
  // M5: no broken .coach-invite{bottom:auto;top:64px}
  assert.doesNotMatch(css,/\.coach-invite\{[^}]*top:\s*64px/);
  // M5: no 54px override on .src-line
  assert.doesNotMatch(css,/\.src-line\{grid-template-columns:\s*54px/);
  // M6: 16px input font-size on <=900px and full-width .reference-query on <=600px
  assert.match(css,/input,select,textarea[^{]*\{font-size:16px\}/);
  assert.match(css,/\.reference-query\{grid-column:1\/-1\}/);
  // S5: auth-hidden spotlight selectors
  assert.match(css,/body:not\(\[data-auth=ready\]\)>\.coach/);
  assert.match(css,/body:not\(\[data-auth=ready\]\)>\.coach-invite/);
  assert.match(css,/body:not\(\[data-auth=ready\]\)>\.coach-reopen/);
});

test('F2 & P2-6: agentChat isolates state per caseId and requires explicit consent for real uploaded materials',async()=>{
  const workSrc=readWeb('work.js');
  const start=workSrc.indexOf('/* ---------- 询价 Agent ---------- */');
  const end=workSrc.indexOf('// The workbench shows what the agent actually did:');
  let confirmCalls=0,confirmAnswer=false;
  const requests=[];
  const ctx={
    window:null,
    current:{id:'case-a',revision:1,title:'Real Case'},
    focus:{type:'agent',id:''},
    materials:{caseId:'case-a',revision:1,files:[{file:'real-customer-rfq.xlsx',sha256:'abc'}]},
    authState:{user:{id:'u1',role:'user'}},
    RfqDialog:{confirm:async()=>{confirmCalls++;return confirmAnswer}},
    $:()=>null,
    renderWork(){},placeAgentNote(){},renderAgentEntry(){},show(){},activity(){},notice(){},
    setInterval:()=>1,clearInterval(){},
    request:async(url,opts)=>{
      requests.push({url,body:opts?.body?JSON.parse(opts.body):null});
      return {turn:{message:'hi',reply:'done'},case:{id:'case-a',title:'Real Case'}};
    },
  };
  ctx.window=ctx;
  vm.createContext(ctx);
  vm.runInContext(workSrc.slice(start,end),ctx);

  // Per-case isolation: case-a busy does not affect case-b
  const chatA=ctx.getAgentChat('case-a');
  const chatB=ctx.getAgentChat('case-b');
  chatA.busy=true;chatA.text='draft-a';
  assert.equal(chatB.busy,false);
  assert.equal(chatB.text,'');
  chatA.busy=false;chatA.text='';

  // Real material: declining consent aborts without sending request
  await ctx.agentSend('分析这份真实文件',{caseId:'case-a'});
  assert.equal(confirmCalls,1);
  assert.equal(requests.length,0);
  assert.equal(chatA.text,'分析这份真实文件');

  // Real material: accepting consent sends consent: true
  confirmAnswer=true;
  await ctx.agentSend('分析这份真实文件',{caseId:'case-a'});
  assert.equal(confirmCalls,2);
  assert.equal(requests.length,1);
  assert.equal(requests[0].body.consent,true);

  // Synthetic material: sends consent: false with ZERO dialog prompt
  ctx.current={id:'case-syn',revision:1,title:'Synthetic'};
  ctx.materials={caseId:'case-syn',revision:1,files:[{file:'guided.eml',sha256:'def'}]};
  await ctx.agentSend('处理样例',{caseId:'case-syn'});
  assert.equal(confirmCalls,2,'synthetic sample must not prompt dialog');
  assert.equal(requests.length,2);
  assert.equal(requests[1].body.consent,false);
});

test('M4 & B2: mobileNav work tab switches off agent focus and keeps single aria-current',()=>{
  const appSrc=readWeb('app.js');
  assert.match(appSrc,/b\.dataset\.view==='work'&&focus\?\.type==='agent'&&current/);
  assert.match(appSrc,/const agentActive=focus\?\.type==='agent'&&v==='work'/);
  assert.match(appSrc,/!agentActive&&b\.dataset\.view===v/);
  assert.match(appSrc,/ma\.setAttribute\('aria-current',String\(agentActive\)\)/);
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/syncMobileNavActive\(\)/);
});

test('P1-A, P2-D & B1: case_approved sync, drawer z-index above top, and mobile coach-docked min-height reset',()=>{
  const appSrc=readWeb('app.js');
  assert.match(appSrc,/serverCaseApproved/);
  assert.match(appSrc,/needsReapprove/);
  assert.match(appSrc,/function openDrawer\(\)\{toggleActivity\(false\)/);
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/s\.needsReapprove/);
  assert.match(workSrc,/合成体验-两张询价/);
  const css=readWeb('style.css');
  assert.match(css,/\.drawer\{[^}]*z-index:96/);
  assert.match(css,/\.scrim\{[^}]*z-index:94/);
  assert.match(css,/body\.coach-docked\{[^}]*min-height:0/);
  const spotSrc=readWeb('spotlight.js');
  assert.match(spotSrc,/const caseReady=\(\)=>/);
  assert.match(spotSrc,/if\(state\.caseId&&\(typeof current==='undefined'\|\|!current\|\|current\.id!==state\.caseId\)\)\{\s*root\.hidden=true;pill\.hidden=true/);
});

