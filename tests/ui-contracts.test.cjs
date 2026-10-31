const {test}=require('node:test'),assert=require('node:assert/strict');
const {RfqUiState:ui,RfqFormMemory:Forms}=require('../apps/web/ui-state.js');
class Storage {constructor(){this.map=new Map()}getItem(k){return this.map.get(k)??null}setItem(k,v){this.map.set(k,v)}removeItem(k){this.map.delete(k)}}
const loc=href=>new URL(href);
test('API config retains default loopback, supports explicit same-origin, rejects credentials/mixed content',()=>{
 assert.equal(ui.apiBase(undefined,loc('http://127.0.0.1:5311/')),'http://127.0.0.1:8311/api');
 assert.equal(ui.apiBase('/api',loc('http://127.0.0.1:5361/')),'http://127.0.0.1:5361/api');
 assert.equal(ui.apiBase(undefined,loc('https://review.invalid/')),'https://review.invalid/api');
 for(const raw of ['https://user:secret@review.invalid/api','http://review.invalid/api','//other.invalid/api','data:text/plain,secret','/api?token=secret'])assert.throws(()=>ui.apiBase(raw,loc('https://review.invalid/')));
});
test('structured issue class remains authoritative with changed wording, Chinese fallback is lossless',()=>{
 const row={issues:['需要报价授权','缺少单位','自定义原文'],issue_codes:[{code:'missing_price',message:'需要报价授权'}]};
 const issues=ui.issues(row);assert(ui.isPrice(issues[0]));assert.equal(issues[1].code,'missing_field');assert.equal(issues[2].code,'unknown');assert.deepEqual(issues.map(i=>i.message),row.issues);
});
test('review conclusions never imply clarification resolved and fresh pending review wins',()=>{
 assert.match(ui.replyLabel({review_status:'no_answer'}),/未回答/);
 assert.match(ui.questionLabel({state:'received',replies:[{review_status:'no_answer'}]}),/仍未解决/);
 assert.match(ui.questionLabel({state:'received',replies:[{review_status:'pending_review',reviews:[{status:'no_answer'}]}]}),/待核对/);
});
test('no-op price response reports no new revision or invalidation',()=>{
 assert.match(ui.priceNotice({revision:6,price_version:2},{revision:6,priceVersion:2}),/没有生成新版本/);
 assert.match(ui.priceNotice({revision:7,price_version:3},{revision:6,priceVersion:2}),/v3/);
});
test('tab forms survive reload, stay with case/focus and do not reuse stale confirmations',()=>{
 const storage=new Storage();let c={id:'case-a',revision:5,price_version:1};const a=new Forms(storage,()=>true,()=>c);
 a.set('case-a|g|g:actor','合成复核员');a.set('case-a|q:q1|k:c1:assoc',true);a.set('case-a|q:q1|r:reason','按合成答复核对');
 const b=new Forms(storage,()=>true,()=>c);assert.equal(b.get('case-a|g|g:actor'),'合成复核员');assert(b.compatible('case-a|q:q1|k:c1:assoc',c));assert.equal(b.get('case-b|g|g:actor'),undefined);
 c={...c,revision:6};assert(!b.compatible('case-a|q:q1|k:c1:assoc',c));assert.equal(b.stale('case-a|q:q1|',c).length,2);assert(b.compatible('case-a|g|g:actor',c));
});
test('pending-request new edits are not cleared by a submitted-value cleanup',()=>{
 const storage=new Storage(),c={revision:1,price_version:0},a=new Forms(storage,()=>true,()=>c),k='case|q:q|r:reason';a.set(k,'提交值');const submitted=new Map(a);a.set(k,'等待中新输入');for(const [key,value] of submitted)if(a.get(key)===value)a.delete(key);assert.equal(new Forms(storage,()=>true,()=>c).get(k),'等待中新输入');
});
test('disabled or unavailable policy clears tab persistence while RAM remains usable',()=>{
 const storage=new Storage();let enabled=true;const c={revision:1,price_version:0},a=new Forms(storage,()=>enabled,()=>c);a.set('case|g|g:actor','合成复核员');enabled=false;a.set('case|g|g:actor','只在页内');assert.equal(storage.getItem(Forms.KEY),null);assert.equal(a.get('case|g|g:actor'),'只在页内');assert.equal(new Forms(storage,()=>false,()=>c).size,0);
 const broken={getItem(){throw Error()},setItem(){throw Error()},removeItem(){throw Error()}};const b=new Forms(broken,()=>true,()=>c);b.set('case|g|g:actor','当前页');assert.match(b.error,/暂存失败/);assert.equal(b.get('case|g|g:actor'),'当前页');
});
test('expired or malformed tab records cannot become current input',()=>{
 const s=new Storage();s.setItem(Forms.KEY,JSON.stringify([{k:'case|g|g:actor',v:'expired',revision:1,pv:0,time:1},{k:'bad-key',v:'bad',revision:1,pv:0,time:Date.now()}]));assert.equal(new Forms(s,()=>true,()=>({revision:1,price_version:0})).size,0);
});
