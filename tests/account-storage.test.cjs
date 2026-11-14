const test=require('node:test');
const assert=require('node:assert/strict');
const AccountStorage=require('../apps/web/account-storage.js');
const Drafts=require('../apps/web/draft-store.js');
const {RfqFormMemory}=require('../apps/web/ui-state.js');
function storage(){const data=new Map();return {get length(){return data.size},key:i=>[...data.keys()][i]??null,getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,String(v)),removeItem:k=>data.delete(k)}}
function record(value){return {schema:1,caseId:'samecase',rowId:'samerow',revision:1,rowRevision:1,priceVersion:0,rfq:'001',part:'P1',editId:value,updatedAt:Date.now(),edits:{reason:value},base:{reason:''}}}
test('changing accounts never lists or recovers another account draft, even with identical case keys',()=>{
  const disk=storage(),a=new Drafts(new AccountStorage(disk,'user:a:')),b=new Drafts(new AccountStorage(disk,'user:b:'));
  assert.equal(a.put(record('private-a')),true);
  assert.deepEqual(b.list(),[]);
  assert.equal(b.put(record('private-b')),true);
  assert.equal(a.get('samecase','samerow').edits.reason,'private-a');
  assert.equal(b.get('samecase','samerow').edits.reason,'private-b');
  assert.equal(b.clear(),true);
  assert.equal(a.get('samecase','samerow').edits.reason,'private-a');
});
test('tab form memory and legacy drafts are outside a different account namespace',()=>{
  const disk=storage(),c={id:'samecase',revision:1,price_version:0};
  disk.setItem('rfqdesk.drafts.settings.v1','legacy-data');
  const a=new RfqFormMemory(new AccountStorage(disk,'user:a:'),()=>true,()=>c);
  a.set('samecase|row:samerow|reason','private-reviewer-a');
  const b=new RfqFormMemory(new AccountStorage(disk,'user:b:'),()=>true,()=>c);
  assert.equal(b.size,0);b.clearPersisted();
  const restored=new RfqFormMemory(new AccountStorage(disk,'user:a:'),()=>true,()=>c);
  assert.equal(restored.get('samecase|row:samerow|reason'),'private-reviewer-a');
  assert.equal(disk.getItem('rfqdesk.drafts.settings.v1'),'legacy-data');
});
