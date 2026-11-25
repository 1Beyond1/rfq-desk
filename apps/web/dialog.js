/* Unified confirm / input dialog — same .dlg-head, .btn-row and .msg skin as 价目审阅、预览与账号管理。
   替代浏览器原生 confirm / prompt，保证视觉与交互一致。 */
const RfqDialog=(()=>{
  let host=null,fields=[],done=null;

  function build(){
    if(host)return host;
    host=document.createElement('dialog');
    host.id='askDialog';
    host.innerHTML='<div class="dlg-head"><h2 id="askTitle"></h2><button type="button" class="icon-btn" data-ask-cancel aria-label="关闭">×</button></div>'
      +'<p id="askBody" class="ask-body"></p>'
      +'<form id="askForm" novalidate><div id="askFields"></div>'
      +'<p id="askError" class="msg error" role="alert"></p>'
      +'<div class="btn-row"><button type="submit" class="btn btn-primary" id="askOk">确定</button>'
      +'<button type="button" class="btn btn-ghost" id="askCancel" data-ask-cancel>取消</button></div></form>';
    document.body.append(host);
    host.querySelectorAll('[data-ask-cancel]').forEach(b=>b.onclick=()=>finish(null));
    host.addEventListener('cancel',e=>{e.preventDefault();finish(null)});
    host.addEventListener('close',()=>{if(done)finish(null)});
    host.querySelector('#askForm').onsubmit=e=>{e.preventDefault();submit()};
    return host;
  }

  function finish(value){
    const resolve=done;
    done=null;
    if(host&&host.open)host.close();
    if(resolve)resolve(value);
  }

  function submit(){
    const values={},error=host.querySelector('#askError');
    error.textContent='';
    for(const f of fields){
      const el=host.querySelector(`[name="${f.name}"]`),value=(el?el.value:'').trim();
      const fail=message=>{error.textContent=message;if(el)el.focus();return true};
      if(f.required&&!value){if(fail(f.missing||`请填写${f.label}`))return}
      if(f.maxlength&&value.length>f.maxlength){if(fail(`${f.label}不能超过 ${f.maxlength} 个字符`))return}
      if(f.pattern&&value&&!new RegExp(f.pattern).test(value)){if(fail(f.patternError||`${f.label}格式不正确`))return}
      values[f.name]=value;
    }
    finish(values);
  }

  function open(options){
    build();
    if(done||host.open)finish(null);
    const o=options||{};
    fields=o.fields||[];
    host.querySelector('#askTitle').textContent=o.title||'请确认';
    const body=host.querySelector('#askBody');
    body.textContent=o.body||'';
    body.hidden=!o.body;
    host.querySelector('#askError').textContent='';
    host.querySelector('#askOk').textContent=o.ok||'确定';
    host.querySelector('#askOk').className='btn '+(o.tone==='danger'?'btn-danger':'btn-primary');
    host.querySelector('#askCancel').textContent=o.cancel||'取消';
    host.querySelector('#askCancel').hidden=o.cancel===false;
    const box=host.querySelector('#askFields');
    box.replaceChildren();
    box.hidden=!fields.length;
    for(const f of fields){
      const label=document.createElement('label');
      label.append(document.createTextNode(f.label));
      const el=document.createElement(f.type==='textarea'?'textarea':'input');
      el.name=f.name;
      if(f.type!=='textarea')el.type=f.type||'text';
      if(f.value!=null)el.value=f.value;
      if(f.placeholder)el.placeholder=f.placeholder;
      if(f.maxlength)el.maxLength=f.maxlength;
      if(f.inputmode)el.inputMode=f.inputmode;
      label.append(el);
      if(f.hint){const hint=document.createElement('span');hint.className='hint';hint.textContent=f.hint;label.append(hint)}
      box.append(label);
    }
    const autofocus=host.querySelector(`[name="${fields[0]?.name}"]`);
    host.showModal();
    (autofocus||host.querySelector('#askOk')).focus();
    if(autofocus&&autofocus.select)autofocus.select();
    return new Promise(resolve=>{done=resolve});
  }

  return {
    /* 确认框：返回 true / false */
    confirm:options=>open({...options,fields:[]}).then(value=>Boolean(value)),
    /* 提示/说明框（单按钮） */
    alert:options=>open({ok:'知道了',cancel:false,...options,fields:[]}).then(()=>true),
    /* 表单框：返回 {字段名: 值}，取消返回 null */
    ask:options=>open(options)
  };
})();
