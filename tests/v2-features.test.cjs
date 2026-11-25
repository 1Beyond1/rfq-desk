const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const readWeb=name=>fs.readFileSync(path.join(__dirname,'../apps/web',name),'utf8');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

test('U3 & U4 & U16 & U19: clarification reply filtering, stayOnQuestion, demo disable, and association label',()=>{
  const workSrc=readWeb('work.js');
  // U3: proposeCandidates accepts stayOnQuestion option and skips setFocus('cand',...) when true
  assert.match(workSrc,/async function proposeCandidates\(mode,opts=\{\}\)/);
  assert.match(workSrc,/if\(!opts\.stayOnQuestion&&found&&current\?\.id===ctx\.caseId&&batch\?\.candidates\?\.\[0\]\)setFocus\('cand'/);
  assert.match(workSrc,/proposeCandidates\('offline',\{stayOnQuestion:true\}\)/);
  // U4: filters materials.files strictly by material_append events and shows hint + disabled submit when empty
  assert.match(workSrc,/e\.action==='material_append'&&e\.detail\?\.filename/);
  assert.match(workSrc,/请先在上方追加答复原件/);
  assert.match(workSrc,/id="saveReply" \$\{unlinked\.length&&!isDemo\?'':'disabled'\}/);
  // U16: demo role disables saveReply and explains
  assert.match(workSrc,/replyDemoHint/);
  // U19: association translated to 重复归属 in viewQuestion
  assert.match(workSrc,/q\.field==='association'\?'重复归属':q\.field/);
});

test('U7 & U9 & U10: partial candidate hides batch accept, GBP/JPY currencies, demo-prices confirm & draft locks',async()=>{
  const workSrc=readWeb('work.js');
  // U7: partial/target candidate disables & hides #candAcceptBatch and shows hint
  assert.match(workSrc,/const hasRevisionTarget=partial\|\|Boolean\(target\)\|\|same\.length>0/);
  assert.match(workSrc,/id="candAcceptBatch"\$\{hasRevisionTarget\?' disabled hidden':''\}/);
  assert.match(workSrc,/id="candBatchHint"/);
  assert.match(workSrc,/const others=candButtons\(\)\.filter\(x=>x!==activeBtn&&!x\.disabled&&!x\.hidden\)/);

  // U9: GBP & JPY options present in priceFields
  assert.match(workSrc,/<option>USD<\/option><option>CNY<\/option><option>EUR<\/option><option>GBP<\/option><option>JPY<\/option>/);

  // U10: execute loadDemoPrices() in VM to verify confirm guard & priceDrafts block
  const fnStart=workSrc.indexOf('async function loadDemoPrices(){');
  const fnEnd=workSrc.indexOf('const rowRefCache=new Map();');
  let confirmCalls=0,confirmAnswer=false,changeCalls=0;
  const ctx={
    current:{id:'c1',prices:[{part:'P1'}]},
    priceDrafts:new Map(),
    kept:{delete(){}},
    keepKey:k=>k,
    RfqUiState:{priceNotice:()=>'ok'},
    RfqDialog:{confirm:async()=>{confirmCalls++;return confirmAnswer}},
    change:async()=>{changeCalls++},
  };
  vm.createContext(ctx);
  vm.runInContext(workSrc.slice(fnStart,fnEnd),ctx);

  // When current.prices.length > 0 and user cancels -> no change() call
  await ctx.loadDemoPrices();
  assert.equal(confirmCalls,1);
  assert.equal(changeCalls,0);

  // When user confirms -> change('demo-prices') runs
  confirmAnswer=true;
  await ctx.loadDemoPrices();
  assert.equal(confirmCalls,2);
  assert.equal(changeCalls,1);

  // When priceDrafts has current.id -> throws error before confirm
  ctx.priceDrafts.set('c1',{list:[]});
  await assert.rejects(()=>ctx.loadDemoPrices(),/有待保存修改/);

  // Catalog & inline price upload disabled when priceDrafts exists
  assert.match(workSrc,/id="priceUpload"[^>]*\$\{hasDraft\?'disabled':''\}/);
  assert.match(workSrc,/id="loadPrices" \$\{hasDraft\?'disabled':''\}/);
  assert.match(workSrc,/id="priceFileInline" \$\{catalogDraft\?'disabled':''\}/);
});

test('U8 & U16: landing #mailDemo uses prose, offline #tourStart runs /guided-demo, demo disables #agentMailSend',()=>{
  const appSrc=readWeb('app.js');
  const workSrc=readWeb('work.js');
  assert.match(appSrc,/\$\('mailDemo'\)\.onclick=\(\)=>run\(\(\)=>importCase\('\/semantic-demo\/prose'/);
  assert.match(appSrc,/\$\('tourStart'\)\.disabled=false/);
  assert.match(appSrc,/\$\('agentMailSend'\)\.disabled=!enabled\|\|isDemo/);
  assert.match(workSrc,/if\(!modelState\.requests_enabled\)\{\s*const c=await request\('\/guided-demo'/);
  assert.match(workSrc,/window\.rfqSpotlight\?\.start\(c\.id,\{skipAgent:true\}\)/);
});

test('U11 & Feature 3: home.js uses ov.case_total and renders offline-local turn badge, mail cards, and references',()=>{
  const elements=new Map();
  const el=id=>{
    if(!elements.has(id))elements.set(id,{id,value:'',disabled:false,hidden:false,textContent:'',innerHTML:'',classList:{add(){},remove(){}},addEventListener(){},querySelectorAll(){return []},replaceChildren(){}});
    return elements.get(id);
  };
  const ctx={
    window:{renderAgentReferences:t=>t.references?.length?`<div class="ref-ok">${t.references.length}</div>`:''},
    document:{querySelectorAll:()=>[],getElementById:id=>el(id)},
    $:el,
    modelState:{requests_enabled:false},
    request:async()=>({turns:[]}),
    run:fn=>fn(),setTimeout,sessionStorage:{getItem:()=>null},
  };
  vm.createContext(ctx);
  vm.runInContext(readWeb('home.js'),ctx);

  // U11: case_total=25 beats cases.length=12
  const ov={
    today:'2026-11-25',
    case_total:25,
    archived_total:3,
    cases:Array.from({length:12},(_,i)=>({id:'c'+i,title:'Case '+i})),
    mails:{total:12,unrouted:2,need_review:1,by_category:{new_rfq:9}},
    todo:[{kind:'mail_unrouted',count:2,text:'2 封邮件还没分流'}],
  };
  ctx.ov=ov;
  vm.runInContext('ahApplyOverview(ov)',ctx);
  assert.equal(el('ahCaseCount').textContent,25);
  assert.match(el('ahStats').innerHTML,/<b>25<\/b><span>张工作单<\/span>/);
  assert.match(el('ahStats').innerHTML,/另含 3 张已归档/);

  // Feature 3: offline local turn renders badge + mail cards + references
  ctx.localTurn={
    message:'有什么要我审的？',
    reply:'今天共有 2 封待分流邮件。',
    local:true,
    mode:'offline-local',
    steps:[{tool:'pending_overview',summary:'读取本地待办'}],
    mails:[{id:'m1',subject:'RFQ-100',category:'new_rfq',needs_review:false}],
    references:[{tool:'lookup_stock',result:{records:[]}}],
  };
  const html=vm.runInContext('ahTurn(localTurn)',ctx);
  assert.match(html,/本地规则汇总 · 未调用模型/);
  assert.match(html,/ah-msg bot is-local/);
  assert.match(html,/data-ah-mail="m1"/);
  assert.match(html,/class="ref-ok">1/);
});

test('U12, U13, U15 & U19: responsive CSS, 1180 breakpoint, account menu close, accounts errors/audit, cache-bust',()=>{
  const css=readWeb('style.css');
  const appSrc=readWeb('app.js');
  const workSrc=readWeb('work.js');
  const accSrc=readWeb('accounts.js');
  const html=readWeb('index.html');

  // U12
  assert.doesNotMatch(appSrc,/innerWidth<=1280/);
  assert.doesNotMatch(workSrc,/innerWidth<=1280/);
  assert.match(appSrc,/innerWidth<=1180/);
  assert.match(workSrc,/innerWidth<=1180/);
  assert.match(css,/\.recovery\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(css,/#localDraftCompare\{min-width:0\}/);
  assert.match(css,/\.ag\{max-width:980px;margin:0 auto;padding:16px 24px 28px\}/);
  assert.match(css,/\.rag-pipeline li\+li\{border-top:0\}/);
  assert.doesNotMatch(css,/\.rag-pipeline li\{border-left:1px solid var\(--line\);border-top:0\}/);

  // U13
  assert.match(appSrc,/if\(\$\('accountMenu'\)\?\.open&&!e\.target\.closest\('\.account-menu'\)\)\$\('accountMenu'\)\.open=false/);
  assert.match(appSrc,/if\(open\)\{[^}]*\$\('accountMenu'\)\.open=false/);

  // U15
  assert.match(accSrc,/两次新密码不一致';\$\('authError'\)\.className='msg error'/);
  assert.match(accSrc,/\$\('accountsError'\)\.className='msg error'/);
  assert.match(accSrc,/demo_start:'体验空间进入'/);
  assert.match(accSrc,/legacy_assign:'分配历史工单'/);
  assert.match(html,/id="createUsername"[^>]*title="[^"]+"/);

  // U19 cache busting
  assert.match(html,/style\.css\?v=20261125-v3/);
  assert.match(html,/app\.js\?v=20261125-v3/);
  assert.match(html,/work\.js\?v=20261125-v3/);
  assert.match(html,/spotlight\.js\?v=20261125-v3/);
  assert.match(html,/onsite\.js\?v=20261125-v3/);
  assert.match(html,/home\.js\?v=20261125-v3/);
  assert.doesNotMatch(html,/航材/);
  assert.doesNotMatch(readWeb('app.js'),/航材/);
});

test('U17, U18 & Feature 4C: onsite.js inbox retry, title sync, reference model options collapse & inbox filter/search',async()=>{
  const onsiteSrc=readWeb('onsite.js');
  const nodes=new Map();
  const makeNode=(id)=>{
    const attrs=new Map();
    return {
      id,hidden:false,innerHTML:'',textContent:'',value:'',checked:false,
      setAttribute:(k,v)=>attrs.set(k,v),getAttribute:k=>attrs.get(k),
      replaceChildren(){this.innerHTML=''},
      querySelector(){return null},querySelectorAll(){return []},
    };
  };
  const $=id=>{if(!nodes.has(id))nodes.set(id,makeNode(id));return nodes.get(id)};
  const landCases=makeNode('landCases'),landCreate=makeNode('landCreate');
  $('landing').hidden=false;

  let inboxShouldFail=true;
  const ctx={
    window:{},
    document:{querySelector:sel=>sel==='#landing .land-cases'?landCases:sel==='#landing .land-create'?landCreate:null},
    $,esc,tail:s=>String(s).slice(-6),
    views:{},W:()=>makeNode('work'),
    caseList:[],current:null,modelState:{requests_enabled:false},
    showCases(){},openCase(){},setFocus(){},
    busyButton:()=>()=>{},
    run:fn=>fn(),
    request:async(url)=>{
      if(url==='/inbox'&&inboxShouldFail)throw Error('收件箱服务暂时不可用');
      return [];
    },
  };
  ctx.window=ctx;
  vm.createContext(ctx);
  vm.runInContext(onsiteSrc,ctx);

  // U17: title sync on workspaceMode
  vm.runInContext('workspaceMode("inbox")',ctx);
  assert.equal($('title').textContent,'询价收件箱');
  vm.runInContext('workspaceMode("references")',ctx);
  assert.equal($('title').textContent,'库存与历史参考');
  vm.runInContext('workspaceMode("cases")',ctx);
  assert.equal($('title').textContent,'我的工作单');

  // U17: showInbox failure displays error + retryInbox button
  await assert.rejects(()=>vm.runInContext('showInbox()',ctx),/收件箱服务暂时不可用/);
  assert.match($('onsiteHomePanel').innerHTML,/收件箱读取失败/);
  assert.match($('onsiteHomePanel').innerHTML,/id="retryInbox"/);

  // U18: referenceState persists consent & hides model options for exact queries
  assert.match(onsiteSrc,/const refUsesModel=kind=>kind==='parts'\|\|kind==='rule'/);
  assert.match(onsiteSrc,/referenceState=\{[^}]*consent:false/);
  assert.match(onsiteSrc,/id="referenceOptions"\$\{showModelOpts\?'':' hidden'\}/);
  assert.match(onsiteSrc,/name="consent" type="checkbox" \$\{referenceState\.consent\?'checked':''\}/);

  // Feature 4C: matchesInboxFilter filters all 6 chips + search
  const mails=[
    {id:'m1',subject:'Hydraulic seal RFQ',sender:'a@airline.test',preview:'SYN-002',decision:null,manual:null,case_id:null},
    {id:'m2',subject:'Uncertain inquiry',sender:'b@mro.test',preview:'check part',decision:{category:'new_rfq',needs_review:true},manual:null,case_id:null},
    {id:'m3',subject:'FW: Qty Revision',sender:'c@ops.test',preview:'change qty',decision:{category:'revision',needs_review:false},manual:null,case_id:null},
    {id:'m4',subject:'Linked RFQ',sender:'d@fleet.test',preview:'SYN-001',decision:{category:'new_rfq',needs_review:false},manual:null,case_id:'case-1'},
  ];
  const f=ctx.window.rfqMatchesInboxFilter;
  assert.deepEqual(mails.filter(m=>f(m,'all','')).map(m=>m.id),['m1','m2','m3','m4']);
  assert.deepEqual(mails.filter(m=>f(m,'unrouted','')).map(m=>m.id),['m1']);
  assert.deepEqual(mails.filter(m=>f(m,'need_review','')).map(m=>m.id),['m2']);
  assert.deepEqual(mails.filter(m=>f(m,'new_rfq','')).map(m=>m.id),['m2','m4']);
  assert.deepEqual(mails.filter(m=>f(m,'revision','')).map(m=>m.id),['m3']);
  assert.deepEqual(mails.filter(m=>f(m,'linked','')).map(m=>m.id),['m4']);
  assert.deepEqual(mails.filter(m=>f(m,'all','syn-002')).map(m=>m.id),['m1']);
});

test('Feature 1: local version diff HTML renderer & human-readable event summaries',()=>{
  const workSrc=readWeb('work.js');
  const start=workSrc.indexOf('/* ---------- log & local version diff ---------- */');
  const end=workSrc.indexOf('async function loadMatrixOne(');
  const ctx={
    window:{},
    esc,
    fieldNames:{rfq:'询价号',part:'件号',description:'描述',quantity:'数量',unit:'单位',condition:'件状',due:'截止日期',requirements:'特殊要求',priority:'优先级'},
    engineName:e=>({http_model:'模型提议',offline_label_rules:'离线标签规则'}[e]||e),
    current:{id:'c1',revision:4},
  };
  ctx.window=ctx;
  vm.createContext(ctx);
  vm.runInContext(workSrc.slice(start,end),ctx);

  const html=ctx.window.rfqRenderLocalDiff({
    snapshots:[
      {revision:1,kind:'import',actor:'alice',created_at:'2026-11-25T08:00:00Z'},
      {revision:3,kind:'approve',actor:'alice',created_at:'2026-11-25T09:00:00Z'},
    ],
    default_from:3,
    current_revision:4,
    diff:{
      from_revision:3,to_revision:4,from_kind:'approve',to_kind:'current',from_actor:'alice',
      price_version_before:1,price_version_after:2,materials_changed:true,
      summary:{added:0,removed:0,excluded:1,restored:0,changed:1,price_changed:1,unchanged:0},
      rows:[
        {
          row_id:'r1',rfq:'RFQ-1',part:'SYN-001',status:'price_changed',
          changes:[
            {field:'quantity',before:'2',after:'4'},
            {field:'price_amount',before:'10',after:'12.5'},
            {field:'price_currency',before:'USD',after:'GBP'},
            {field:'price_source',before:'旧价表',after:'新授权报价'},
            {field:'approved',before:true,after:false},
          ],
        },
        {
          row_id:'r2',rfq:'RFQ-1',part:'SYN-002',status:'excluded',
          changes:[{field:'excluded',before:false,after:true}],
        },
      ],
    },
  });
  assert.match(html,/id="diffFromRev"/);
  assert.match(html,/id="diffToRev"/);
  assert.match(html,/value="current" selected/);
  assert.match(html,/价表 v1 → v2/);
  assert.match(html,/原件清单已变更/);
  assert.match(html,/<del class="diff-old">10<\/del>.*<ins class="diff-new">12\.5<\/ins>/);
  assert.match(html,/单价/);
  assert.match(html,/币种/);
  assert.match(html,/价格依据/);
  assert.match(html,/批准状态/);
  assert.match(html,/排除状态/);
  assert.match(html,/已排除/);

  const sum=ctx.window.rfqEventSummary;
  assert.match(sum({action:'import',detail:{filename:'rfq.eml',rows:3}}),/导入 rfq\.eml，共 3 行/);
  assert.match(sum({action:'resolve',detail:{before:{quantity:'2'},after:{quantity:'5'},reason:'按客户回信更新'}}),/变更 数量.*按客户回信更新/);
  assert.match(sum({action:'export',detail:{format:'xlsx',revision:4}}),/导出 XLSX · 工作版本 r4/);
  assert.match(sum({action:'archive',detail:{archived:true,actor:'alice'}}),/已归档工作单/);
});

test('Feature 2: output view supports Excel (.xlsx) export and bilingual quote reply email preview + copy',()=>{
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/id="exportXlsx">导出 Excel \(\.xlsx\)<\/button>/);
  assert.match(workSrc,/\$\('exportXlsx'\)\.onclick=\(\)=>formal\('xlsx',\$\('exportXlsx'\)\)/);
  assert.match(workSrc,/\/quote-email\?revision=/);
  assert.match(workSrc,/data-email-lang="zh"/);
  assert.match(workSrc,/data-email-lang="en"/);
  assert.match(workSrc,/id="copyQuoteEmail"/);
  assert.match(workSrc,/navigator\.clipboard\.writeText/);
});

test('Feature 4A & 4B: case status filter chips, archived isolation, archive & delete API integration',async()=>{
  const appSrc=readWeb('app.js');
  const start=appSrc.indexOf('let caseStatusFilter=\'all\';');
  const end=appSrc.indexOf('function caseTodo(');
  const ctx={};
  vm.createContext(ctx);
  vm.runInContext(appSrc.slice(start,end),ctx);

  const list=[
    {id:'c-cand',pending_candidates:2,open_clarifications:0,issue_rows:0,active:1,approved:0,archived:false},
    {id:'c-clar',pending_candidates:0,open_clarifications:1,issue_rows:1,active:1,approved:0,archived:false},
    {id:'c-price',pending_candidates:0,open_clarifications:0,issue_rows:2,active:2,approved:0,archived:false},
    {id:'c-app',pending_candidates:0,open_clarifications:0,issue_rows:0,active:2,approved:0,case_approved:false,archived:false},
    {id:'c-out',pending_candidates:0,open_clarifications:0,issue_rows:0,active:2,approved:2,case_approved:true,archived:false},
    {id:'c-arch',pending_candidates:0,open_clarifications:0,issue_rows:0,active:1,approved:1,case_approved:true,archived:true},
  ];
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'all')).map(c=>c.id),['c-cand','c-clar','c-price','c-app','c-out']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'cand')).map(c=>c.id),['c-cand']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'clarify')).map(c=>c.id),['c-clar']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'price')).map(c=>c.id),['c-clar','c-price']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'approve')).map(c=>c.id),['c-app']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'output')).map(c=>c.id),['c-out']);
  assert.deepEqual(list.filter(c=>ctx.matchesCaseStatus(c,'archived')).map(c=>c.id),['c-arch']);

  // Verify archive & delete API calls in app.js and viewLog lifecycle card in work.js
  assert.match(appSrc,/\/archive`,\{\s*method:'PATCH'/);
  assert.match(appSrc,/method:'DELETE'/);
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/id="toggleArchiveCase"/);
  assert.match(workSrc,/id="deleteCaseBtn"/);
});

test('Feature 5: price triple reference tabs, RfqDialog.alert, and workbench keyboard shortcuts with silence guards',async()=>{
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/priceRefTabs=\[\['stock','现货库存与缺口'\],\['quote','历史报价'\],\['alternative','替代件'\]\]/);
  assert.match(workSrc,/id="rowRefTabs"/);
  assert.match(workSrc,/loadRowReference\(r,priceRefTab\)/);

  // Test RfqDialog.alert
  let shown=0,cancelHidden=null;
  const map=new Map();
  const host={
    open:false,
    querySelector(sel){
      if(!map.has(sel))map.set(sel,{textContent:'',className:'',hidden:false,replaceChildren(){},append(){},focus(){},onsubmit:null});
      return map.get(sel);
    },
    querySelectorAll:()=>[],
    addEventListener(){},
    showModal(){this.open=true;shown++;cancelHidden=map.get('#askCancel')?.hidden},
    close(){this.open=false},
  };
  const dCtx={document:{createElement:()=>host,body:{append(){}},createTextNode:t=>t}};
  vm.createContext(dCtx);
  vm.runInContext(readWeb('dialog.js')+';this.RfqDialog=RfqDialog;',dCtx);
  const p=dCtx.RfqDialog.alert({title:'快捷键',body:'[ 上一项'});
  assert.equal(shown,1);
  assert.equal(cancelHidden,true);
  host.querySelector('#askForm').onsubmit({preventDefault(){}});
  assert.equal(await p,true);

  // Test workbench shortcuts ([ ] Alt+S / ?) and silence when input focused or dialog open
  const appSrc=readWeb('app.js');
  const sStart=appSrc.indexOf('function isEditableTarget(');
  const sEnd=appSrc.indexOf('window.rfqHandleShortcut=');
  let focusHistory=[],srcOpened=false,alertOpened=0,searchFocused=0,dialogOpen=false;
  const searchInput={tagName:'INPUT',focus(){searchFocused++},select(){}};
  const elements={
    drawer:{hidden:true},
    landing:{hidden:true},
    desk:{hidden:false},
    agentHome:{hidden:true},
    rowSearch:searchInput,
  };
  const sCtx={
    document:{
      body:{dataset:{auth:'ready',view:'work'},classList:{contains:c=>c==='src-open'&&srcOpened}},
      activeElement:{tagName:'BODY'},
      querySelector:sel=>sel==='dialog[open]'&&dialogOpen?{}:null,
    },
    $:id=>elements[id]||null,
    current:{id:'c1'},
    focus:{type:'row',id:'r1'},
    queueMode:'rows',
    renderQueue(){},
    narrow:()=>false,
    openSource:()=>{srcOpened=true},
    closeSource:()=>{srcOpened=false},
    setView(){},
    queueItems:()=>[{type:'row',id:'r1',tone:'bad'},{type:'price',id:'r2',tone:'price'},{type:'output',id:'o',tone:'off'}],
    setFocus:(t,id)=>{sCtx.focus={type:t,id};focusHistory.push(t+':'+id)},
    RfqDialog:{alert:()=>{alertOpened++}},
  };
  vm.createContext(sCtx);
  vm.runInContext(appSrc.slice(sStart,sEnd),sCtx);
  const mkEv=(key,extra={})=>({key,altKey:false,ctrlKey:false,metaKey:false,target:{tagName:'BODY'},preventDefault(){},...extra});

  assert.equal(sCtx.handleWorkbenchShortcut(mkEv(']')),true);
  assert.deepEqual(focusHistory,['price:r2']);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('[')),true);
  assert.deepEqual(focusHistory,['price:r2','row:r1']);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('s',{altKey:true})),true);
  assert.equal(srcOpened,true);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('s',{altKey:true})),true);
  assert.equal(srcOpened,false);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('/')),true);
  assert.equal(searchFocused,1);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('?')),true);
  assert.equal(alertOpened,1);

  // Silent when input focused
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv(']',{target:{tagName:'INPUT'}})),false);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('?',{target:{tagName:'TEXTAREA'}})),false);
  // Silent when <dialog open>
  dialogOpen=true;
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv(']')),false);
  assert.equal(sCtx.handleWorkbenchShortcut(mkEv('?')),false);
  assert.equal(focusHistory.length,2);
  assert.equal(alertOpened,1);
});

test('V2 Red-Team convergence: snapKindNames, triple-ref currency/qty sanitization, delete cleanup & mobile CSS',()=>{
  const workSrc=readWeb('work.js');
  assert.match(workSrc,/prices:'价表更新'/);
  assert.match(workSrc,/material:'原件变更'/);
  assert.doesNotMatch(workSrc,/r\.price\?\.currency\|\|'USD'/);
  assert.match(workSrc,/const qCur=String\(r\.price\?\.currency\|\|''\)\.trim\(\)\.slice\(0,10\)/);
  assert.match(workSrc,/const qQty=\/\^\\d\+\(\?:\\\.\\d\+\)\?\$\/\.test\(rawQty\)\?rawQty\.slice\(0,30\):''/);

  const appSrc=readWeb('app.js');
  assert.match(appSrc,/for\(const k of \[\.\.\.kept\.keys\(\)\]\)if\(k\.startsWith\(item\.id\+'\|'\)\)kept\.delete\(k\)/);
  assert.match(appSrc,/localDrafts\.removeIf\(r\.caseId,r\.rowId,r\.editId\)/);

  const css=readWeb('style.css');
  assert.match(css,/\.ah-who\{[^}]*flex-wrap:wrap/);
  assert.match(css,/\.ah-avatar\{[^}]*flex:none/);
  assert.match(css,/\.diff-panel \.diff-controls\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(css,/\.case-row-acts \.btn\{min-height:36px\}/);
});
