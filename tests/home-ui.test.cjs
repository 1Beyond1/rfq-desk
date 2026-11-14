const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function page(request){
 const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{value:'',disabled:false,textContent:'',innerHTML:'',classList:{add(){},remove(){}},addEventListener(){},querySelectorAll(){return []}});return elements.get(id)};
 const ctx=vm.createContext({window:{renderAgentReferences:t=>`<div class="test-evidence">${t.references?.length||0}</div>`},document:{querySelectorAll:()=>[]},$:el,request,run:fn=>fn(),setTimeout,sessionStorage:{getItem:()=>null}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps/web/home.js'),'utf8'),ctx);
 vm.runInContext('ahState.started=true; ahRenderLog=()=>{}',ctx);
 return {ctx,el,ask:(text)=>vm.runInContext(`ahAsk(${JSON.stringify(text)})`,ctx)};
}
test('failed home request preserves question, restores input and leaves visible error after finally',async()=>{
 const p=page(async()=>{throw Error('服务暂不可用')});await p.ask('查SYN-002');
 assert.equal(p.el('ahInput').value,'查SYN-002');assert.match(p.el('ahStatus').textContent,/服务暂不可用/);
 assert.equal(p.el('ahSend').disabled,false);assert.equal(vm.runInContext('ahState.busy',p.ctx),false);
 assert.equal(vm.runInContext('ahState.turns[0].message',p.ctx),'查SYN-002');
});
test('failed request does not overwrite a new question typed while waiting',async()=>{
 let reject;const p=page(()=>new Promise((_,r)=>reject=r));const waiting=p.ask('原问题');p.el('ahInput').value='正在写的新问题';reject(Error('断联'));await waiting;
 assert.equal(p.el('ahInput').value,'正在写的新问题');assert.equal(vm.runInContext('ahState.turns[0].message',p.ctx),'原问题');
});
test('home reply renders returned mail summaries safely and includes query evidence',()=>{
 const p=page();p.ctx.turn={message:'问题',reply:'回复',mails:[{id:'one',subject:'<script>x</script>',category:'new_rfq',needs_review:true}],references:[{}]};
 const html=vm.runInContext('ahTurn(turn)',p.ctx);assert.match(html,/test-evidence/);assert.match(html,/&lt;script&gt;/);assert.match(html,/需人工确认/);assert.doesNotMatch(html,/<script>x/);
});
