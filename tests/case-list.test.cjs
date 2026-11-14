const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {RfqUiState}=require('../apps/web/ui-state.js');

// Exercise the actual list controller and its rendered states with a deferred transport.
const app=fs.readFileSync(require.resolve('../apps/web/app.js'),'utf8');
const controller=app.slice(app.indexOf('async function refreshList(){'),app.indexOf("$('caseFilter').oninput="));
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function desk(request){
  const nodes=Object.fromEntries(['cases','landingCases','caseFilter','landingFilter'].map(k=>[k,{value:'',innerHTML:''}]));
  const retries=[{},{}];
  const ctx={request,listRequest:0,listLoading:false,listError:'',caseList:[],current:null,
    $:id=>nodes[id],esc:v=>String(v??''),tail:v=>v.slice(-6),RfqUiState,
    notice:()=>{},run:f=>f(),document:{querySelectorAll:s=>s==='[data-retry-cases]'?retries:[]}};
  vm.createContext(ctx);vm.runInContext(controller,ctx);
  return {ctx,nodes,retries};
}
const row=(title,id='case001')=>({id,title,revision:1,active:2,approved:0,issue_rows:2});

test('failed refresh keeps an explicit retry state through filtering instead of old or empty rows',async()=>{
  const task=deferred(),{ctx,nodes}=desk(()=>task.promise);ctx.caseList=[row('旧列表')];
  const result=ctx.refreshList();assert.match(nodes.landingCases.innerHTML,/正在读取/);
  task.reject(Error('连接中断'));assert.equal(await result,false);
  assert.match(nodes.landingCases.innerHTML,/工作单读取失败/);
  assert.doesNotMatch(nodes.landingCases.innerHTML,/旧列表|还没有工作单/);
  nodes.landingFilter.value='不存在';ctx.renderCaseLists();
  assert.match(nodes.landingCases.innerHTML,/连接中断/);
  assert.match(nodes.cases.innerHTML,/data-retry-cases/);
});
test('retrying either list clears its failure and displays the fresh result',async()=>{
  let fails=true;const {ctx,nodes,retries}=desk(async()=>{if(fails)throw Error('暂不可用');return [row('新工作单')]});
  await ctx.refreshList();fails=false;await retries[1].onclick();
  assert.equal(ctx.listError,'');assert.match(nodes.landingCases.innerHTML,/新工作单/);
  assert.match(nodes.cases.innerHTML,/新工作单/);assert.doesNotMatch(nodes.landingCases.innerHTML,/读取失败/);
});
test('a late failed response cannot replace a newer successful list',async()=>{
  const old=deferred(),fresh=deferred();let n=0;const {ctx,nodes}=desk(()=>[old,fresh][n++].promise);
  const first=ctx.refreshList(),second=ctx.refreshList();fresh.resolve([row('最新结果')]);
  assert.equal(await second,true);old.reject(Error('旧请求失败'));assert.equal(await first,false);
  assert.equal(ctx.listError,'');assert.equal(ctx.listLoading,false);
  assert.match(nodes.landingCases.innerHTML,/最新结果/);assert.doesNotMatch(nodes.landingCases.innerHTML,/旧请求失败/);
});
