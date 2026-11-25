const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

class FakeClassList {
  constructor(el){this.el=el;this.set=new Set()}
  add(...names){for(const n of names)if(n)this.set.add(n)}
  remove(...names){for(const n of names)this.set.delete(n)}
  toggle(n,force){if(force===undefined){if(this.set.has(n))this.set.delete(n);else this.set.add(n)}else if(force)this.set.add(n);else this.set.delete(n);return this.set.has(n)}
  contains(n){return this.set.has(n)}
  get value(){return [...this.set].join(' ')}
}

class FakeStyle {
  constructor(){this.props=new Map();this._cssText=''}
  set cssText(v){this._cssText=String(v||'');if(!v){this.left='';this.top='';this.width='';this.height='';this.transform=''}}
  get cssText(){return this._cssText}
  setProperty(k,v){this.props.set(k,String(v))}
  getPropertyValue(k){return this.props.get(k)||''}
}

class FakeElement {
  constructor(tag='div',id=''){
    this.tagName=tag.toUpperCase();
    this.id=id;
    this.hidden=false;
    this.disabled=false;
    this.readOnly=false;
    this.checked=false;
    this.value='';
    this.textContent='';
    this._innerHTML='';
    this.dataset={};
    this.classList=new FakeClassList(this);
    this.style=new FakeStyle();
    this.children=[];
    this.parent=null;
    this.isConnected=true;
    this.focused=false;
    this.scrollTop=0;
    this.rect={left:40,top:120,right:240,bottom:180,width:200,height:60};
    this.offsetHeight=180;
    this.attrs=new Map();
    this.events=new Map();
  }
  set className(v){this.classList.set=new Set(String(v||'').split(/\s+/).filter(Boolean))}
  get className(){return this.classList.value}
  set innerHTML(v){this._innerHTML=String(v||'')}
  get innerHTML(){return this._innerHTML}
  append(...els){for(const e of els){e.parent=this;this.children.push(e)}}
  getClientRects(){return this.hidden?[]:[this.rect]}
  getBoundingClientRect(){return {...this.rect}}
  scrollIntoView(){}
  focus(){this.focused=true}
  click(){if(this.tagName==='INPUT')this.checked=!this.checked;if(typeof this.onclick==='function')this.onclick({target:this,preventDefault(){}})}
  dispatchEvent(){}
  setAttribute(k,v){this.attrs.set(k,String(v))}
  getAttribute(k){return this.attrs.get(k)??null}
  closest(sel){
    let cur=this;
    while(cur){if(cur.matches(sel))return cur;cur=cur.parent}
    return null;
  }
  matches(sel){
    return sel.split(',').some(part=>{
      const s=part.trim();
      if(s==='input'||s==='textarea'||s==='select')return this.tagName===s.toUpperCase();
      if(s.startsWith('.'))return this.classList.contains(s.slice(1));
      if(s.startsWith('#'))return this.id===s.slice(1);
      return false;
    });
  }
  querySelector(sel){return this._sub?.[sel]||null}
  querySelectorAll(sel){const v=this._sub?.[sel];return v?(Array.isArray(v)?v:[v]):[]}
}

function makeSpotlightEnv(opts={}){
  const store=new Map();
  const sessionStorage={
    get length(){return store.size},
    key:i=>[...store.keys()][i]??null,
    getItem:k=>store.has(k)?store.get(k):null,
    setItem:(k,v)=>store.set(k,String(v)),
    removeItem:k=>store.delete(k),
  };

  const body=new FakeElement('body');
  body.dataset={auth:opts.auth||'ready',view:opts.view||'work'};

  const byId=new Map();
  const regId=(id,tag='div',extra={})=>{
    const el=new FakeElement(tag,id);
    Object.assign(el,extra);
    byId.set(id,el);
    return el;
  };

  const agentHome=regId('agentHome','main',{hidden:Boolean(opts.deskOpen)});
  const landing=regId('landing','main',{hidden:true});
  const desk=regId('desk','div',{hidden:!opts.deskOpen});
  const ahInput=regId('ahInput','textarea');
  const ahSend=regId('ahSend','button');
  const agentInput=regId('agentInput','textarea');
  const queueEl=regId('queue','div');
  const workEl=regId('work','main');
  const sourceEl=regId('sourcePane','aside');
  const mAgent=regId('mAgent','button');
  const agentEntry=regId('agentEntry','button');
  const candAccept=regId('candAccept','button');
  const candAcceptBatch=regId('candAcceptBatch','button');
  const candReject=regId('candReject','button');
  const candError=regId('candError','p');
  const approveBtn=regId('approve','button');
  const actorInput=regId('actor','input');
  const readiness=regId('readiness','p');
  const loadPricesInline=regId('loadPricesInline','button');
  const savePrice=regId('savePrice','button');
  const quotePreview=regId('quotePreview','button');
  const quoteFrame=regId('quoteFrame','iframe',{hidden:true});
  const exportCsv=regId('exportCsv','button');

  const candReason=new FakeElement('textarea');
  const candActor=new FakeElement('input');
  const candCheck=new FakeElement('input');
  const cfields=new FakeElement('div');
  const ahHero=new FakeElement('header');
  const ahLog=new FakeElement('section');
  const ahAsk=new FakeElement('form');
  const ahWrap=new FakeElement('div');
  ahWrap.rect={left:100,top:60,right:1000,bottom:700,width:900,height:640};
  const ahInboxBtn=new FakeElement('button');
  const ahBriefline=new FakeElement('div');
  const agentSubmit=new FakeElement('button');
  const mQueue=new FakeElement('button');
  const checksBadJump=new FakeElement('button');

  const selectors=new Map([
    ['.queue',queueEl],['.work',workEl],['.source',sourceEl],
    ['#agentInput',agentInput],['#agentForm button[type=submit]',agentSubmit],
    ['#agentEntry',agentEntry],['#mAgent',mAgent],
    ['#queue',queueEl],['#mobileNav [data-view="queue"]',mQueue],
    ['#work .cfields',cfields],
    ['#work [data-keep="reason"]',candReason],
    ['#work [data-keep="actor"]',candActor],
    ['#work .checks input[type=checkbox]',candCheck],
    ['#candAccept',candAccept],['#candAcceptBatch',candAcceptBatch],['#candReject',candReject],['#candError',candError],
    ['#approve',approveBtn],['#actor',actorInput],['#readiness',readiness],
    ['.checks-list li.bad [data-gate-jump]',checksBadJump],
    ['#loadPricesInline',loadPricesInline],['#savePrice',savePrice],
    ['#quotePreview',quotePreview],['#quoteFrame',quoteFrame],['#exportCsv',exportCsv],
    ['.ah-hero',ahHero],['.ah-log',ahLog],['.ah-ask',ahAsk],['.ah-wrap',ahWrap],
    ['[data-ah-go="inbox"]',ahInboxBtn],['#ahLog .ah-briefline',ahBriefline],
    ['#ahInput',ahInput],['#ahSend',ahSend],
  ]);

  let mobile=Boolean(opts.mobile);
  let innerWidth=opts.innerWidth||(mobile?375:1440);
  let innerHeight=opts.innerHeight||(mobile?812:900);
  let vvHeight=opts.vvHeight||innerHeight;
  let overlayOpen=false;
  let docListeners=new Map();
  let winListeners=new Map();
  const notices=[];
  const focusCalls=[];
  const viewCalls=[];
  let homeShown=0;
  let onsiteMode=opts.onsiteMode||'cases';

  const makeCoachRoot=()=>{
    const el=new FakeElement('div');
    const hole=new FakeElement('div');hole.className='coach-hole';
    const bubble=new FakeElement('div');bubble.className='coach-bubble';
    const count=new FakeElement('div');const title=new FakeElement('h3');const bodyEl=new FakeElement('p');
    const next=new FakeElement('button');const skip=new FakeElement('button');
    const toggle=new FakeElement('button');const collapse=new FakeElement('button');const endBtn=new FakeElement('button');
    el._sub={
      '.coach-hole':hole,'.coach-bubble':bubble,'.coach-count':count,'.coach-title':title,'.coach-body':bodyEl,
      '.coach-next':next,'.coach-skip':skip,'.coach-toggle':toggle,'.coach-collapse':collapse,'.coach-end':endBtn,
    };
    return el;
  };
  const makeInvite=()=>{
    const el=new FakeElement('div');
    const b=new FakeElement('b');const span=new FakeElement('span');const p=new FakeElement('p');
    const start=new FakeElement('button');const later=new FakeElement('button');
    el._sub={'.ci-head b':b,'.ci-head span':span,'.ci-body':p,'[data-ci-start]':start,'[data-ci-later]':later};
    return el;
  };
  let createdCount=0;
  const document={
    body,
    activeElement:null,
    createElement(tag){
      createdCount++;
      if(createdCount===1)return makeCoachRoot();
      if(createdCount===2)return makeInvite();
      return new FakeElement(tag);
    },
    getElementById:id=>byId.get(id)||null,
    querySelector:sel=>{
      if(sel==='dialog[open]'||sel==='.drawer:not([hidden]), .drawer.open'||sel==='.pop:not([hidden])'||sel==='.account-menu[open]'){
        return overlayOpen?new FakeElement('div'):null;
      }
      if(selectors.has(sel))return selectors.get(sel);
      if(sel.startsWith('#'))return byId.get(sel.slice(1))||null;
      return null;
    },
    querySelectorAll:sel=>{
      const v=selectors.get(sel);
      return v?(Array.isArray(v)?v:[v]):[];
    },
    addEventListener:(ev,fn)=>{if(!docListeners.has(ev))docListeners.set(ev,new Set());docListeners.get(ev).add(fn)},
    removeEventListener:(ev,fn)=>docListeners.get(ev)?.delete(fn),
  };

  const visualViewport={
    get height(){return vvHeight},
    addEventListener:(ev,fn)=>{if(!winListeners.has('vv:'+ev))winListeners.set('vv:'+ev,new Set());winListeners.get('vv:'+ev).add(fn)},
    removeEventListener:(ev,fn)=>winListeners.get('vv:'+ev)?.delete(fn),
  };

  const chats=new Map();
  const getAgentChat=id=>{
    const k=id||'__none__';
    if(!chats.has(k))chats.set(k,{caseId:id||null,turns:[],busy:false,text:'',steps:[]});
    return chats.get(k);
  };

  const ctx={
    window:null,
    document,
    sessionStorage,
    Event:class Event{constructor(t){this.type=t}},
    matchMedia:()=>({matches:mobile}),
    get innerWidth(){return innerWidth},
    get innerHeight(){return innerHeight},
    get scrollY(){return 0},
    scrollTo(){},
    requestAnimationFrame:fn=>{fn();return 1},
    setInterval:()=>1,
    setTimeout:fn=>{fn();return 1},
    addEventListener:(ev,fn)=>{if(!winListeners.has(ev))winListeners.set(ev,new Set());winListeners.get(ev).add(fn)},
    removeEventListener:(ev,fn)=>winListeners.get(ev)?.delete(fn),
    visualViewport,
    authState:{required:true,user:{id:opts.userId||'u1',role:opts.role||'demo'}},
    modelState:{requests_enabled:opts.requestsEnabled!==undefined?opts.requestsEnabled:true},
    current:opts.current||null,
    focus:opts.focus||null,
    ahState:{turns:[],busy:false},
    getAgentChat,
    getOnsiteMode:()=>onsiteMode,
    showHome:()=>{homeShown++;agentHome.hidden=false;landing.hidden=true;desk.hidden=true},
    setFocus:(type,id='')=>{ctx.focus={type,id};focusCalls.push({type,id})},
    setView:(v)=>{body.dataset.view=v;viewCalls.push(v)},
    notice:(msg)=>notices.push(msg),
    summarize:(c)=>{
      const active=(c.rows||[]).filter(r=>!r.excluded);
      const pending=(c.candidate_batches||[]).filter(b=>b.expected_revision===c.revision)
        .flatMap(b=>b.candidates.filter(x=>x.status==='pending').map(x=>({b,x})));
      const replyFiles=new Set((c.clarifications||[]).flatMap(q=>(q.replies||[]).map(r=>r.filename+':'+r.sha256)));
      const cands=pending.filter(({x})=>!Object.values(x.field_sources||{}).every(s=>replyFiles.has(s.file+':'+s.sha256)));
      return {active,cands};
    },
  };
  ctx.window=ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/spotlight.js'),'utf8'),ctx);

  return {
    ctx,body,byId,selectors,sessionStorage,store,notices,focusCalls,viewCalls,
    get homeShown(){return homeShown},
    setMobile(v){mobile=v},
    setSize(w,h,vv){innerWidth=w;innerHeight=h;vvHeight=vv??h},
    setOverlay(v){overlayOpen=v},
    setOnsiteMode(m){onsiteMode=m},
    fireKey(key,extra={}){for(const fn of (docListeners.get('keydown')||[]))fn({key,...extra})},
    winListeners,docListeners,
    els:{agentHome,landing,desk,ahInput,ahSend,agentInput,queueEl,workEl,sourceEl,candReason,candActor,candCheck,approveBtn,actorInput,loadPricesInline,savePrice,ahWrap,checksBadJump},
    dbg:ctx.window.rfqSpotlight._debug,
    api:ctx.window.rfqSpotlight,
  };
}

test('S1: skipping toAgent step never loops; jumps past agent when case has work, ends cleanly when empty',()=>{
  // Case with formal rows: skipping toAgent jumps straight to pricing without bouncing back
  const env=makeSpotlightEnv({
    deskOpen:true,
    current:{id:'c1',revision:1,rows:[{id:'r1',excluded:false,price:null,approved:false}],prices:[],progress:{}},
  });
  env.api.start('c1');
  env.dbg.root.querySelector('.coach-next').click(); // step 0 -> step 1 (agent-send)
  assert.equal(env.dbg.getState().step,1);
  env.dbg.root.querySelector('.coach-skip').click();
  // Should jump directly to price step (index 10), NOT bounce back to 1
  const st=env.dbg.getState();
  assert(st && st.step>2, 'expected step past agent phase, got '+st?.step);
  assert.equal(st.skipAgent,true);
  assert.equal(env.dbg.steps()[st.step].id,'price');

  // Empty case with online model: skipping toAgent ends cleanly with notice (no bounce-back)
  const envOnlineEmpty=makeSpotlightEnv({
    deskOpen:true,
    requestsEnabled:true,
    current:{id:'c2-online',revision:1,rows:[],prices:[],progress:{}},
  });
  envOnlineEmpty.api.start('c2-online');
  envOnlineEmpty.dbg.root.querySelector('.coach-next').click(); // step 0 -> step 1 (agent-send)
  assert.equal(envOnlineEmpty.dbg.getState().step,1);
  envOnlineEmpty.dbg.root.querySelector('.coach-skip').click();
  assert.equal(envOnlineEmpty.api.active(),false,'skipping toAgent on empty case must end cleanly without bouncing');
  assert.equal(envOnlineEmpty.notices.length,1);

  // Empty case with offline model: skips agent steps and never loops
  const env2=makeSpotlightEnv({
    deskOpen:true,
    requestsEnabled:false,
    current:{id:'c2',revision:1,rows:[],prices:[],progress:{}},
  });
  env2.api.start('c2');
  assert.equal(env2.dbg.getState().step,0);
  env2.dbg.root.querySelector('.coach-next').click();
  assert(env2.dbg.getState()===null || env2.dbg.steps()[env2.dbg.getState().step].id==='done');
});

test('S2: home tour hides when leaving agentHome and clears when entering a work order',()=>{
  const env=makeSpotlightEnv({deskOpen:false});
  env.api.start(null);
  assert.equal(env.dbg.root.hidden,false);

  // Navigate to cases list (agentHome hidden, landing visible)
  env.els.agentHome.hidden=true;env.els.landing.hidden=false;
  env.dbg.tick();
  assert.equal(env.dbg.root.hidden,true);
  assert.equal(env.body.classList.contains('coaching'),false);

  // Enter a work order (desk visible, current set) -> home tour clears so case invite is unblocked
  env.els.landing.hidden=true;env.els.desk.hidden=false;
  env.ctx.current={id:'c9',revision:1,rows:[],prices:[],progress:{}};
  env.dbg.tick();
  assert.equal(env.api.active(),false);
  env.api.maybeInviteCase('c9');
  assert.equal(env.dbg.invite.hidden,false);
  assert.equal(env.dbg.invite.dataset.caseId,'c9');
});

test('S3: step.fill runs once on entry and never overwrites user edits on subsequent ticks',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,
    current:{
      id:'c3',revision:1,rows:[],prices:[],progress:{pending_candidates:1},
      candidate_batches:[{id:'b1',expected_revision:1,candidates:[{id:'x1',status:'pending',fields:{rfq:'1',part:'P1'},field_sources:{part:{file:'a.eml',sha256:'h1'}}}]}],
      clarifications:[],
    },
  });
  env.api.start('c3',{skipAgent:true});
  env.dbg.root.querySelector('.coach-next').click(); // layout -> cand-look
  env.dbg.root.querySelector('.coach-next').click(); // cand-look -> cand-accept
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'cand-accept');
  assert.equal(env.els.candReason.value,'已对照邮件原文核对');
  assert.equal(env.els.candCheck.checked,true);

  // User edits reason and unchecks checkbox
  env.els.candReason.value='人工自定义理由';
  env.els.candCheck.checked=false;
  env.dbg.tick();env.dbg.tick();env.dbg.tick();
  assert.equal(env.els.candReason.value,'人工自定义理由');
  assert.equal(env.els.candCheck.checked,false);
});

test('S3: reply-only candidates do not stall cand steps; disabled approve points to blocking checklist',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,
    current:{
      id:'c4',revision:1,
      rows:[{id:'r1',excluded:false,price:{amount:'10',currency:'USD',kind:'manual'},approved:false}],
      prices:[{part:'P1',kind:'manual'}],
      progress:{pending_candidates:1},
      candidate_batches:[{id:'b1',expected_revision:1,candidates:[{id:'x1',status:'pending',fields:{unit:'EA'},field_sources:{unit:{file:'reply.txt',sha256:'sha-r'}}}]}],
      clarifications:[{id:'q1',replies:[{filename:'reply.txt',sha256:'sha-r'}]}],
    },
  });
  env.els.approveBtn.disabled=true;
  env.api.start('c4',{skipAgent:true});
  env.dbg.root.querySelector('.coach-next').click();
  // Reply-only candidate is skipped, price is already set -> lands on approve
  const step=env.dbg.steps()[env.dbg.getState().step];
  assert.equal(step.id,'approve');
  assert.match(env.dbg.root.querySelector('.coach-body').textContent,/阻断项/);
  assert.equal(step.target(),env.els.checksBadJump);
});

test('S3: mobile step 6 without #agentNext switches to queue view instead of hidden #queue',()=>{
  const env=makeSpotlightEnv({
    mobile:true,deskOpen:true,view:'source',
    current:{
      id:'c5',revision:1,rows:[],prices:[],progress:{pending_candidates:1},
      candidate_batches:[{id:'b1',expected_revision:1,candidates:[{id:'x1',status:'pending',fields:{rfq:'1',part:'P1'},field_sources:{part:{file:'a.eml',sha256:'h1'}}}]}],
      clarifications:[],
    },
  });
  // Agent already has a completed turn without timeline/draft, no #agentNext in DOM
  env.ctx.getAgentChat('c5').turns=[{message:'go',reply:'ok',steps:[]}];
  env.api.start('c5');
  env.dbg.root.querySelector('.coach-next').click(); // layout -> agent-conclusion (skips send,wait,tl)
  assert.equal(env.body.dataset.view,'work');
  env.dbg.root.querySelector('.coach-next').click(); // agent-conclusion -> agent-next (skips draft)
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'agent-next');
  assert.equal(env.body.dataset.view,'queue');
});

test('S4: home tour advances on any completed turn, preserves input, never focuses on mobile, checks inbox mode',()=>{
  const env=makeSpotlightEnv({mobile:true,deskOpen:false});
  assert.match(env.dbg.invite.innerHTML,/5 步/);
  env.api.start(null);
  env.dbg.root.querySelector('.coach-next').click(); // step 0 -> 1
  env.dbg.root.querySelector('.coach-next').click(); // step 1 -> 2 (home-ask-todo)
  assert.equal(env.dbg.getState().step,2);
  assert.equal(env.els.ahInput.value,'有什么要我审的？');
  assert.equal(env.els.ahInput.focused,false,'must not focus input on mobile');

  // Complete turn WITHOUT hardcoded tool name 'pending_overview'
  env.ctx.ahState.turns.push({message:'有什么要我审的？',reply:'离线兜底回复',tools:[]});
  // Pre-fill user text before advancing to step 3 -> step 3 must NOT overwrite it
  env.els.ahInput.value='用户自己打的问题';
  env.dbg.tick();
  assert.equal(env.dbg.getState().step,3);
  assert.equal(env.els.ahInput.value,'用户自己打的问题');
  assert.equal(env.els.ahInput.focused,false);

  // Complete turn WITHOUT hardcoded tool name 'search_parts'
  env.ctx.ahState.turns.push({message:'用户自己打的问题',reply:'找到了几个候选',tools:['custom_tool']});
  env.dbg.tick();
  assert.equal(env.dbg.getState().step,4);

  // Opening landing in 'cases' mode must NOT complete step 4
  env.els.agentHome.hidden=true;env.els.landing.hidden=false;env.setOnsiteMode('cases');
  env.dbg.tick();
  assert.equal(env.api.active(),true);
  assert.equal(env.dbg.root.hidden,true);

  // Switching to 'inbox' mode DOES complete step 4
  env.setOnsiteMode('inbox');
  env.dbg.tick();
  assert.equal(env.api.active(),false);
  assert.equal(env.sessionStorage.getItem('rfq-tour:u1:home-done'),'1');
});

test('S5: coach-end marks declined (not done), later pill remembers caseId, Esc respects overlays, account switch resets',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,userId:'alice',
    current:{id:'case-77',revision:1,rows:[],prices:[],progress:{}},
  });
  // Invite case -> click later -> pill remembers case-77 and does NOT kick to home
  env.api.inviteCase('case-77');
  env.dbg.invite.querySelector('[data-ci-later]').click();
  assert.equal(env.dbg.pill.hidden,false);
  assert.equal(env.dbg.pill.dataset.caseId,'case-77');
  assert.equal(env.sessionStorage.getItem('rfq-tour:alice:case-declined'),'1');
  env.dbg.pill.click();
  assert.equal(env.dbg.getState().caseId,'case-77');
  assert.equal(env.homeShown,0);

  // Esc with overlay open must NOT end tour
  env.setOverlay(true);
  env.fireKey('Escape');
  assert.equal(env.api.active(),true);

  // Esc with _rfqOverlayEscape must NOT end tour
  env.setOverlay(false);
  env.fireKey('Escape',{_rfqOverlayEscape:true});
  assert.equal(env.api.active(),true);

  // Clicking coach-end with an Event object marks declined, NEVER done
  env.dbg.root.querySelector('.coach-end').onclick({type:'pointerup'});
  assert.equal(env.api.active(),false);
  assert.equal(env.sessionStorage.getItem('rfq-tour:alice:case-done'),null);
  assert.equal(env.sessionStorage.getItem('rfq-tour:alice:case-declined'),'1');

  // Account switch reset clears alice flags and hides everything
  env.api.reset(true);
  assert.equal(env.sessionStorage.getItem('rfq-tour:alice:case-declined'),null);
  assert.equal(env.dbg.root.hidden,true);
  assert.equal(env.dbg.invite.hidden,true);
  assert.equal(env.dbg.pill.hidden,true);
});

test('S6 & M3: home sidebar >=260px threshold, overlay pauses hole dimming, pill never docks, soft keyboard compacts',()=>{
  // Desktop narrow sidebar (room = 1200 - 1000 = 200 < 260) must NOT squeeze bubble to 184px
  const deskEnv=makeSpotlightEnv({mobile:false,deskOpen:false,innerWidth:1200,innerHeight:800});
  deskEnv.api.start(null);
  deskEnv.dbg.root.querySelector('.coach-next').click(); // step 1 (home-brief)
  const w=parseInt(deskEnv.dbg.bubble.style.width,10);
  assert(w>=300,`expected standard bubble width >=300, got ${w}`);
  assert.equal(deskEnv.dbg.hole.hidden,false);

  // Overlay open pauses hole dimming
  deskEnv.setOverlay(true);
  deskEnv.dbg.tick();
  assert.equal(deskEnv.dbg.hole.hidden,true);
  deskEnv.setOverlay(false);

  // Ending tour detaches scroll/resize listeners
  deskEnv.dbg.root.querySelector('.coach-end').click();
  assert.equal(deskEnv.winListeners.get('scroll')?.size||0,0);
  assert.equal(deskEnv.winListeners.get('resize')?.size||0,0);

  // Mobile M3: pill alone must NOT enable coach-docked
  const mobEnv=makeSpotlightEnv({mobile:true,deskOpen:false,innerWidth:375,innerHeight:812,vvHeight:812});
  mobEnv.api.invite(null);
  assert.equal(mobEnv.body.classList.contains('coach-docked'),true);
  mobEnv.dbg.invite.querySelector('[data-ci-later]').click();
  assert.equal(mobEnv.dbg.pill.hidden,false);
  assert.equal(mobEnv.body.classList.contains('coach-docked'),false,'pill alone must not enable coach-docked');

  // Mobile M3: active tour applies guide-target and soft keyboard compacts bubble
  mobEnv.api.start(null);
  mobEnv.dbg.root.querySelector('.coach-next').click(); // step 1 (home-brief)
  assert.equal(mobEnv.body.classList.contains('coach-docked'),true);
  assert.equal(mobEnv.selectors.get('#ahLog .ah-briefline').classList.contains('guide-target'),true);
  assert.equal(mobEnv.dbg.bubble.classList.contains('is-compact'),false);

  // Simulate soft keyboard shrinking visualViewport below 72%
  mobEnv.setSize(375,812,420);
  mobEnv.dbg.tick();
  assert.equal(mobEnv.dbg.bubble.classList.contains('is-compact'),true);
});

test('P2-C & P1-A: collapsed case pill hides when leaving case, and case_approved=false keeps approve step active',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,
    current:{
      id:'case-a',revision:3,case_approved:false,
      rows:[{id:'r2',excluded:false,price:{amount:'25',currency:'USD',kind:'synthetic'},approved:true}],
      prices:[{part:'P1',kind:'synthetic'}],
      progress:{active:1,approved:1,case_approved:false,pending_candidates:0},
      candidate_batches:[],clarifications:[],
    },
  });
  env.api.start('case-a',{skipAgent:true});
  env.dbg.root.querySelector('.coach-next').click(); // layout -> approve (must NOT skip because case_approved is false!)
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'approve');

  // Collapse case-a tour -> pill shows
  env.dbg.root.querySelector('.coach-collapse').click();
  assert.equal(env.dbg.pill.hidden,false);

  // Leave case-a back to Home -> dismiss() clears stale state and hides pill
  env.els.desk.hidden=true;env.els.agentHome.hidden=false;env.ctx.current=null;
  env.api.dismiss();
  assert.equal(env.dbg.pill.hidden,true);
  assert.equal(env.api.active(),false);

  // Also test switching directly from collapsed case-a to case-b -> tick() hides pill & maybeInviteCase invites case-b
  env.els.desk.hidden=false;env.els.agentHome.hidden=true;
  env.ctx.current={id:'case-a',revision:3,rows:[],prices:[],progress:{}};
  env.api.start('case-a',{skipAgent:true});
  env.dbg.root.querySelector('.coach-collapse').click();
  assert.equal(env.dbg.pill.hidden,false);
  env.ctx.current={id:'case-b',revision:1,rows:[],prices:[],progress:{}};
  env.dbg.tick();
  assert.equal(env.dbg.pill.hidden,true);
  env.api.maybeInviteCase('case-b');
  assert.equal(env.dbg.invite.hidden,false);
  assert.equal(env.dbg.invite.dataset.caseId,'case-b');
});

test('wide overview step excludes bubble own .btn-primary so it never oscillates left/right across ticks',()=>{
  const env=makeSpotlightEnv({
    mobile:false,deskOpen:true,innerWidth:1280,innerHeight:800,
    current:{id:'case-osc',revision:1,rows:[],prices:[],progress:{}},
  });
  // Make querySelectorAll('.btn-primary,...') return the bubble's own .coach-next button (which tracks bubble left/top!)
  const origQa=env.ctx.document.querySelectorAll.bind(env.ctx.document);
  const nextBtn=env.dbg.root.querySelector('.coach-next');
  nextBtn.closest=sel=>sel.includes('.coach')?env.dbg.root:null;
  nextBtn.getBoundingClientRect=()=>{
    const l=parseFloat(env.dbg.bubble.style.left)||0;
    const t=parseFloat(env.dbg.bubble.style.top)||0;
    return {left:l+16,top:t+140,right:l+96,bottom:t+172,width:80,height:32};
  };
  env.ctx.document.querySelectorAll=sel=>{
    if(sel.includes('.btn-primary'))return [nextBtn];
    return origQa(sel);
  };
  env.api.start('case-osc',{skipAgent:true});
  env.dbg.tick();
  const firstLeft=env.dbg.bubble.style.left;
  const firstTop=env.dbg.bubble.style.top;
  for(let i=0;i<5;i++){
    env.dbg.tick();
    assert.equal(env.dbg.bubble.style.left,firstLeft,'wide bubble must not oscillate horizontally');
    assert.equal(env.dbg.bubble.style.top,firstTop,'wide bubble must not oscillate vertically');
  }
});

test('U1: failed home turns never advance home tour, while offline local turns advance cleanly',()=>{
  const env=makeSpotlightEnv({mobile:false,deskOpen:false,requestsEnabled:false});
  env.api.start(null);
  env.dbg.root.querySelector('.coach-next').click(); // 0 -> 1
  env.dbg.root.querySelector('.coach-next').click(); // 1 -> 2 (home-ask-todo)
  assert.equal(env.dbg.getState().step,2);

  // Failed turn has reply text AND error: true -> must NOT advance
  env.ctx.ahState.turns.push({message:'有什么要我审的？',reply:'未完成：网络中断',error:true,pending:false});
  assert.equal(env.dbg.completedHomeTurns(),0);
  env.dbg.tick();
  assert.equal(env.dbg.getState().step,2,'failed home turn must not advance step');

  // Offline local rule summary turn -> advances cleanly
  env.ctx.ahState.turns.push({message:'有什么要我审的？',reply:'今天有 2 封待分流',local:true,mode:'offline-local',pending:false});
  assert.equal(env.dbg.completedHomeTurns(),1);
  env.dbg.tick();
  assert.equal(env.dbg.getState().step,3);
  assert.match(env.dbg.root.querySelector('.coach-body').textContent,/离线模式/);
});

test('U2: dynamic step numbering (1/6..6/6), done steps never show skipped, offline done copy adapts',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,requestsEnabled:false,
    current:{
      id:'c-off',revision:1,case_approved:false,
      rows:[
        {id:'r1',rfq:'RFQ-1',part:'SYN-001',excluded:false,price:null,approved:false},
        {id:'r2',rfq:'RFQ-1',part:'SYN-003',excluded:false,price:null,approved:false},
      ],
      prices:[],progress:{},events:[],candidate_batches:[],clarifications:[],
    },
  });
  env.api.start('c-off',{skipAgent:true});
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 1 / 6');

  // Next -> price (2 / 6), never 10 / 15 or 已跳过
  env.dbg.root.querySelector('.coach-next').click();
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'price');
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 2 / 6');
  assert.doesNotMatch(env.dbg.root.querySelector('.coach-count').textContent,/已跳过/);

  // Complete pricing -> auto-advances to approve (3 / 6), NOT counted as skipped
  env.ctx.current.rows[0].price={amount:'10',currency:'USD',kind:'synthetic'};
  env.ctx.current.rows[1].price={amount:'20',currency:'USD',kind:'manual'};
  env.dbg.tick();
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'approve');
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 3 / 6');
  assert.doesNotMatch(env.dbg.root.querySelector('.coach-count').textContent,/已跳过/);
  // U19: offline approve copy does not promise MatrixOne snapshot
  assert.match(env.dbg.root.querySelector('.coach-body').textContent,/锁定当前快照与版本记录/);
  assert.doesNotMatch(env.dbg.root.querySelector('.coach-body').textContent,/MatrixOne/);

  // Complete approve -> preview (4 / 6) -> export (5 / 6) -> done (6 / 6)
  env.ctx.current.rows.forEach(r=>r.approved=true);
  env.ctx.current.case_approved=true;
  env.dbg.tick();
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'preview');
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 4 / 6');

  env.byId.get('quoteFrame').hidden=false;
  env.dbg.tick();
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'export');
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 5 / 6');

  env.ctx.window.rfqLastExport={caseId:'c-off',revision:1};
  env.dbg.tick();
  assert.equal(env.dbg.steps()[env.dbg.getState().step].id,'done');
  assert.equal(env.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 6 / 6');
  assert.match(env.dbg.root.querySelector('.coach-body').textContent,/版本与决策记录/);
  assert.doesNotMatch(env.dbg.root.querySelector('.coach-body').textContent,/批准后改过什么/);

  // Offline empty case -> 1 / 2 -> 2 / 2 with accurate empty-case copy
  const envEmpty=makeSpotlightEnv({
    deskOpen:true,requestsEnabled:false,
    current:{id:'c-empty',revision:1,rows:[],prices:[],progress:{},events:[],candidate_batches:[],clarifications:[]},
  });
  envEmpty.api.start('c-empty',{skipAgent:true});
  assert.equal(envEmpty.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 1 / 2');
  envEmpty.dbg.root.querySelector('.coach-next').click();
  assert.equal(envEmpty.dbg.steps()[envEmpty.dbg.getState().step].id,'done');
  assert.equal(envEmpty.dbg.root.querySelector('.coach-count').textContent,'3 分钟体验 · 2 / 2');
  assert.match(envEmpty.dbg.root.querySelector('.coach-body').textContent,/离线模式且本单尚无正式询价行/);
});

test('U5: price step automatically switches focus from already-priced row to next unpriced row',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,requestsEnabled:false,
    current:{
      id:'c-price',revision:1,
      rows:[
        {id:'r1',rfq:'RFQ-1',part:'SYN-001',excluded:false,price:null,approved:false},
        {id:'r2',rfq:'RFQ-1',part:'SYN-003',excluded:false,price:null,approved:false},
      ],
      prices:[],progress:{},candidate_batches:[],clarifications:[],
    },
  });
  env.api.start('c-price',{skipAgent:true});
  env.dbg.root.querySelector('.coach-next').click(); // enters price on r1
  assert.equal(env.ctx.focus.type,'price');
  assert.equal(env.ctx.focus.id,'r1');

  // Demo price covers SYN-001 (r1), leaving SYN-003 (r2) unpriced
  env.ctx.current.rows[0].price={amount:'12.5',currency:'USD',kind:'synthetic'};
  env.ctx.current.prices=[{part:'SYN-001',kind:'synthetic'}];
  env.dbg.tick();
  assert.equal(env.ctx.focus.type,'price');
  assert.equal(env.ctx.focus.id,'r2','must auto-switch focus to next unpriced row SYN-003');
});

test('U6: wide home sidebar scrolls, hole clips below header, multi-target scrolls clipped bottom button, mobile uses mainView rect',()=>{
  // 1) Wide home sidebar (1440 - 1000 = 440 >= 260) must still call scrollIntoView
  const wideEnv=makeSpotlightEnv({mobile:false,deskOpen:false,innerWidth:1440,innerHeight:800});
  const briefEl=wideEnv.selectors.get('#ahLog .ah-briefline');
  briefEl.rect={left:120,top:900,right:800,bottom:980,width:680,height:80};
  let wideScrolled=0;
  briefEl.scrollIntoView=()=>{wideScrolled++};
  wideEnv.api.start(null);
  wideEnv.dbg.root.querySelector('.coach-next').click(); // step 1 (home-brief)
  assert.equal(wideScrolled,1,'wide home sidebar must execute scrollIntoView');

  // 2) Desktop .coach-hole clips top/height below .top bar (60px)
  const topBarEl=new FakeElement('header');
  topBarEl.rect={left:0,top:0,right:1440,bottom:60,width:1440,height:60};
  wideEnv.selectors.set('.top',topBarEl);
  briefEl.rect={left:120,top:20,right:800,bottom:130,width:680,height:110};
  wideEnv.dbg.tick();
  assert(parseFloat(wideEnv.dbg.hole.style.top)>=60,'hole top must be clipped at or below .top bottom');
  assert.equal(parseFloat(wideEnv.dbg.hole.style.top),60);
  assert.equal(parseFloat(wideEnv.dbg.hole.style.height),78); // (130+8) - 60 = 78

  // 3) Multi-element target: top element visible, bottom button clipped below viewport -> bottom button scrolls
  const multiEnv=makeSpotlightEnv({mobile:false,deskOpen:false,innerWidth:1100,innerHeight:700});
  const inp=multiEnv.byId.get('ahInput'),send=multiEnv.byId.get('ahSend');
  inp.rect={left:100,top:500,right:700,bottom:620,width:600,height:120};
  send.rect={left:600,top:660,right:700,bottom:740,width:100,height:80}; // clipped below 700-24
  let inpScrolled=0,sendScrolled=0;
  inp.scrollIntoView=()=>{inpScrolled++};
  send.scrollIntoView=()=>{sendScrolled++};
  multiEnv.api.start(null);
  multiEnv.dbg.root.querySelector('.coach-next').click(); // 1
  multiEnv.dbg.root.querySelector('.coach-next').click(); // 2 (home-ask-todo -> [ahInput, ahSend])
  assert.equal(sendScrolled,1,'clipped bottom button in multi-target must scroll into view');
  assert.equal(inpScrolled,0);

  // 4) Mobile coach-docked uses mainView().getBoundingClientRect() visible window
  const mobEnv=makeSpotlightEnv({mobile:true,deskOpen:false,innerWidth:375,innerHeight:812,vvHeight:812});
  mobEnv.els.agentHome.rect={left:0,top:80,right:375,bottom:460,width:375,height:380};
  const mobBrief=mobEnv.selectors.get('#ahLog .ah-briefline');
  // Bottom 500 is < innerHeight-180 (632), so old check wouldn't scroll, but > mainView bottom (460) -> MUST scroll!
  mobBrief.rect={left:16,top:420,right:359,bottom:500,width:343,height:80};
  let mobScrolled=0;
  mobBrief.scrollIntoView=()=>{mobScrolled++};
  mobEnv.api.start(null);
  mobEnv.dbg.root.querySelector('.coach-next').click(); // step 1
  assert.equal(mobScrolled,1,'mobile docked scroll check must use mainView() bounding rect');
});

test('U7, U12 & U14: partial candidate dispute targets #candAccept, src-open pauses hole, onCaseSwitch clears old tour',()=>{
  const env=makeSpotlightEnv({
    deskOpen:true,
    current:{
      id:'c-cand',revision:1,
      rows:[{id:'r1',rfq:'RFQ-1',part:'PN-1',excluded:false,price:null,approved:false}],
      prices:[],progress:{pending_candidates:1},
      candidate_batches:[{id:'b1',expected_revision:1,candidates:[{id:'x1',status:'pending',fields:{rfq:'RFQ-1',part:'PN-1'},field_sources:{part:{file:'rev.eml',sha256:'h2'}}}]}],
      clarifications:[],
    },
  });
  const candMode=new FakeElement('select','candMode');
  candMode.value='partial';
  env.selectors.set('#candMode',candMode);
  env.ctx.focus={type:'cand',id:'b1:x1'};
  assert.equal(env.dbg.candHasDispute(),true,'partial mode must be treated as single-row dispute');
  const acceptStep=env.dbg.STEPS.find(s=>s.id==='cand-accept');
  assert(acceptStep.target().includes(env.byId.get('candAccept')));
  assert(!acceptStep.target().includes(env.byId.get('candAcceptBatch')));

  // U12: src-open pauses hole dimming
  assert.equal(env.dbg.hasOverlayOpen(),false);
  env.body.classList.add('src-open');
  assert.equal(env.dbg.hasOverlayOpen(),true);
  env.body.classList.remove('src-open');

  // U14: onCaseSwitch clears previous case tour state
  env.api.start('c-cand',{skipAgent:true});
  assert.equal(env.api.active(),true);
  env.api.onCaseSwitch('c-other');
  assert.equal(env.api.active(),false);
  assert.equal(env.dbg.root.hidden,true);
  assert.equal(env.dbg.pill.hidden,true);
});
