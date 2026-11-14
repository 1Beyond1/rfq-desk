/* Account-scoped draft storage helpers. */
function scopedStorage(storage,prefix){
  return storage?new RfqAccountStorage(storage,prefix):null;
}
function initAccountStorage(){
  storageNamespace=authState.required?'rfq-account:'+authState.user.id+':':'';
  localDrafts=new RfqDraftStore(storageNamespace?scopedStorage(browserStorage,storageNamespace):browserStorage);
  kept=new RfqFormMemory(storageNamespace?scopedStorage(tabStorage,storageNamespace):tabStorage,()=>localDrafts.syncPolicy(),()=>current);
  renderLocalDraftStatus();
}
let accountReloading=false;
function clearAccountMemory(){
  rowDrafts.clear();pendingRowValues.clear();priceDrafts.clear();kept.clear();kept.clearPersisted();
  if(authState.required)localDrafts.clear();
  current=null;caseList=[];materials={caseId:null,revision:-1,files:[],error:''};interaction.navigate(null);
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  for(const id of ['work','srcBody','queue','cases','landingCases','taskActivity','accountList','accountAudit'])$(id).replaceChildren();
  document.body.dataset.auth='pending';
}
function reloadAccount(broadcast=false){
  if(accountReloading)return;accountReloading=true;clearAccountMemory();
  if(broadcast)try{browserStorage?.setItem('rfq-account-event',String(Date.now())+Math.random())}catch{}
  location.reload();
}
async function accountFetch(path,options={}){
  const headers=new Headers(options.headers||{});
  if(authState.user){
    headers.set('X-RFQ-Account',authState.user.id);
    if(!['GET','HEAD','OPTIONS'].includes((options.method||'GET').toUpperCase()))headers.set('X-CSRF-Token',authState.csrf);
  }
  const response=await fetch(API+path,{...options,headers,credentials:'include',cache:'no-store'});
  if(authState.user&&(response.status===401||response.status===409&&response.headers.get('X-RFQ-Session-Changed')==='1'))reloadAccount();
  return response;
}
function accountScreen(password=false,message=''){
  document.body.dataset.auth=password?'password':'login';$('authScreen').hidden=false;
  $('loginForm').hidden=password;$('passwordForm').hidden=!password;
  $('judgeEntry').hidden=password;
  $('authTitle').textContent=password?'修改登录密码':'登录工作台';
  $('authIntro').textContent=password?(authState.user?.must_change?'首次登录，请先更换管理员提供的初始密码。':'修改后，所有设备都需要重新登录。'):'账号由管理员开通，登录后继续处理你的工作单。';
  $('authError').textContent=message;$('authError').className='msg';
}
async function initializeAccount(){
  let state;
  try{state=await request('/auth/session')}
  catch(e){accountScreen(false,e.message);return false}
  Object.assign(authState,state);
  if(state.required&&!state.user){accountScreen();return false}
  if(state.user?.must_change){accountScreen(true);return false}
  document.body.dataset.auth='ready';$('authScreen').hidden=true;
  $('accountMenu').hidden=!state.required;
  if(state.user){$('accountLabel').textContent=state.user.name;$('accountRole').textContent=state.user.role==='demo'?'独立体验空间 / 最长 1 小时':(state.user.role==='admin'?'管理员':'普通用户')+' / '+state.user.username;$('manageAccounts').hidden=state.user.role!=='admin';$('changePassword').hidden=state.user.role==='demo'}
  initAccountStorage();return true;
}
setInterval(async()=>{
  if(!authState.required||!authState.user||accountReloading)return;
  try{const state=await request('/auth/session');if(state.user?.id!==authState.user.id||Boolean(state.user?.must_change)!==Boolean(authState.user.must_change))reloadAccount()}catch{}
},60000);
function formBusy(form,busy){form.querySelectorAll('button,input').forEach(el=>el.disabled=busy)}
$('loginForm').onsubmit=async e=>{
  e.preventDefault();const form=e.currentTarget;formBusy(form,true);$('judgeExperience').disabled=true;$('authError').textContent='正在登录…';
  try{
    const state=await request('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('loginUsername').value.trim(),password:$('loginPassword').value})});
    $('loginPassword').value='';Object.assign(authState,state);
    if(state.user.must_change){accountScreen(true);try{browserStorage?.setItem('rfq-account-event',String(Date.now()))}catch{}}
    else reloadAccount(true);
  }catch(error){$('authError').textContent=error.message;$('authError').className='msg error'}
  finally{formBusy(form,false);$('judgeExperience').disabled=false}
};
$('judgeExperience').onclick=async()=>{
  const b=$('judgeExperience');b.disabled=true;formBusy($('loginForm'),true);$('authError').textContent='正在准备独立体验空间…';
  try{
    const state=await request('/auth/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    Object.assign(authState,state);
    // The trial starts from a raw synthetic customer mail, so the agent does the reading and the visitor reviews.
    // 收件箱样例自带 Jev 判定，直接铺好即可；不再逐次调用模型。
    await request('/inbox/samples',{method:'POST'}).catch(()=>null);
    history.replaceState(null,'',location.pathname);reloadAccount(true);
  }catch(e){$('authError').textContent=e.message;$('authError').className='msg error'}finally{b.disabled=false;formBusy($('loginForm'),false)}
};
$('passwordForm').onsubmit=async e=>{
  e.preventDefault();
  if($('newPassword').value!==$('confirmPassword').value){$('authError').textContent='两次新密码不一致';return}
  const form=e.currentTarget;formBusy(form,true);
  try{await request('/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:$('oldPassword').value,new_password:$('newPassword').value})});form.reset();reloadAccount(true)}
  catch(error){$('authError').textContent=error.message;$('authError').className='msg error'}
  finally{formBusy(form,false)}
};
async function logoutAccount(){
  if((rowDrafts.size||priceDrafts.size||kept.size)&&!await RfqDialog.confirm({title:'退出登录',body:'有尚未提交的填写。退出将清除本机暂存，服务器数据不变。',ok:'退出登录',tone:'danger'}))return;
  try{await request('/auth/logout',{method:'POST'});reloadAccount(true)}catch(e){notice(e.message,true)}
}
$('logout').onclick=logoutAccount;
$('passwordBack').onclick=logoutAccount;
$('changePassword').onclick=()=>{ $('accountMenu').open=false;document.querySelectorAll('dialog[open]').forEach(d=>d.close());accountScreen(true); };
window.addEventListener('storage',e=>{if(e.key==='rfq-account-event'&&authState.required)reloadAccount()});
window.addEventListener('pageshow',e=>{if(e.persisted&&authState.required)reloadAccount()});

async function loadAccounts(){
  const users=await request('/admin/users');
  $('accountList').innerHTML=`<div class="table-wrap"><table class="grid"><thead><tr><th>账号 / 姓名</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>${users.map(u=>`<tr><td><b>${esc(u.username)}</b><div class="hint">${esc(u.name)}</div></td><td>${u.role==='admin'?'管理员':'普通用户'}</td><td>${u.active?(u.must_change?'待首次修改密码':'正常'):'已停用'}</td><td>${u.role==='user'?`<button type="button" class="btn btn-sm" data-account="${esc(u.id)}" data-active="${u.active?'0':'1'}">${u.active?'停用':'启用'}</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`;
  $('accountList').querySelectorAll('[data-account]').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    try{await request('/admin/users/'+button.dataset.account,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({active:button.dataset.active==='1'})});$('accountsError').textContent='账号状态已更新';await loadAccounts()}
    catch(e){$('accountsError').textContent=e.message;button.disabled=false}
  });
  const audit=await request('/admin/audit');
  const names={account_create:'开通账号',account_disable:'停用账号',account_enable:'启用账号',login:'登录',password_change:'修改密码',password_reset:'本机重置密码'};
  $('accountAudit').innerHTML=audit.map(e=>`<p>${esc(new Date(e.at*1000).toLocaleString())} ${esc(e.actor)} ${esc(names[e.action]||e.action)} ${esc(e.subject)}</p>`).join('');
}
$('manageAccounts').onclick=async()=>{
  $('accountMenu').open=false;$('accountsError').textContent='';$('accountList').replaceChildren();$('accountAudit').replaceChildren();$('accountsDialog').showModal();
  try{await loadAccounts()}catch(e){$('accountsError').textContent=e.message}
};
$('closeAccounts').onclick=()=>{$('createAccountForm').reset();$('accountsDialog').close()};
$('accountsDialog').addEventListener('close',()=>$('createAccountForm').reset());
$('createAccountForm').onsubmit=async e=>{
  e.preventDefault();const form=e.currentTarget;formBusy(form,true);
  try{await request('/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('createUsername').value.trim(),name:$('createName').value.trim(),password:$('createPassword').value})});form.reset();$('accountsError').textContent='账号已开通，请私下交付初始密码；本人首次登录时须修改。';await loadAccounts()}
  catch(error){$('accountsError').textContent=error.message}
  finally{formBusy(form,false)}
};
