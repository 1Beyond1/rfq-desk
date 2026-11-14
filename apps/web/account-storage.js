/* Virtual storage bound to one account prefix. */
class RfqAccountStorage {
  constructor(storage,prefix){this.storage=storage;this.prefix=prefix}
  keys(){return Array.from({length:this.storage.length},(_,i)=>this.storage.key(i)).filter(k=>k?.startsWith(this.prefix))}
  get length(){return this.keys().length}
  key(i){const k=this.keys()[i];return k==null?null:k.slice(this.prefix.length)}
  getItem(k){return this.storage.getItem(this.prefix+k)}
  setItem(k,v){this.storage.setItem(this.prefix+k,v)}
  removeItem(k){this.storage.removeItem(this.prefix+k)}
}
if(typeof module!=='undefined')module.exports=RfqAccountStorage;
if(typeof window!=='undefined')window.RfqAccountStorage=RfqAccountStorage;
