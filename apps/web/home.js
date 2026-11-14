/* Workspace home: the agent speaks first, the rest is one click away. */
const ahState = {overview: null, turns: [], busy: false, started: false, loading: false};
window.ahState = ahState;   // 导览要据此判断这步是否已经做完

function ahEsc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

const ahLabels = {new_rfq: '询价', revision: '修订', other: '非询价', suspicious: '可疑', unrouted: '未分流'};

const ahCatClass = {new_rfq: 'c-new', revision: 'c-rev', other: 'c-other', suspicious: 'c-sus'};

function ahStat(value, label, hint, go, hot) {
  const tag = go ? "button" : "div";
  return `<${tag} class="ah-stat${hot ? " hot" : ""}"${go ? ` type="button" data-go="${go}"` : ""}>
    <b>${value}</b><span>${label}</span>${hint ? `<small>${hint}</small>` : ""}</${tag}>`;
}

function ahBrief(ov) {
  if (!ov) return "";
  const m = ov.mails || {}, cats = m.by_category || {};
  const unrouted = m.unrouted || 0, needReview = m.need_review || 0;
  const judged = Object.values(cats).reduce((a, b) => a + b, 0);
  const cases = ov.cases || [];
  const todo = ov.todo || [];
  const pendingCandidates = todo.find(t => t.kind === "candidates")?.count || 0;
  const parts = Object.entries(cats).map(([k, v]) => `${ahLabels[k] || k} ${v}`).join(" · ");
  const cards = [
    ahStat(unrouted, "封待分流", unrouted ? "点开收件箱逐封分流" : "都已分流", unrouted ? "inbox" : "", unrouted > 0),
    ahStat(needReview, "封需人工确认", needReview ? "Jev 不确定，交给你定" : "没有待确认", needReview ? "inbox" : ""),
    ahStat(judged, "封已由 Jev 初筛", parts || "尚未调用模型", "", false),
    ahStat(cases.length, "张工作单", cases.length ? "继续处理待批与待核价" : "还没有工作单", cases.length ? "cases" : ""),
  ].join("");
  return cards;
}

function ahMailCards(turn) {
  const mails = (turn.mails || turn.cards || (turn.result && turn.result.mails) || []);
  const rows = Array.isArray(mails) && mails.length && mails[0] && mails[0].subject ? mails : turn.mails || [];
  if (!rows.length) return '';
  return `<div class="ah-mailcards">${rows.slice(0, 8).map(r => `<button type="button" class="ah-mail" data-ah-mail="${ahEsc(r.id)}"><b>${ahEsc(r.subject)}</b><small>${ahEsc(ahLabels[r.category] || r.category || '未分流')}${r.needs_review ? ' · 需人工确认' : ''}</small><span>去收件箱处理 →</span></button>`).join('')}</div>`;
}

function ahTurn(turn) {
  const steps = (turn.steps || []).map(s => `<li><i>▸</i><span>${ahEsc(s.summary || s.tool)}</span></li>`).join('');
  return `<div class="ah-msg me">${ahEsc(turn.message)}</div>
    <div class="ah-msg bot"><div class="ah-who"><span class="ah-avatar">R</span><b>询价 Agent</b><small>${(turn.steps || []).length ? '本轮调用 ' + (turn.steps || []).length + ' 次工具' : ''}</small></div><p class="ah-text">${ahEsc(turn.reply || '')}</p>
      ${steps ? `<ul class="ah-steps">${steps}</ul>` : ''}
      ${ahMailCards(turn)}
      ${window.renderAgentReferences?.(turn) || ''}
    </div>`;
}

function ahRenderLog() {
  const log = $('ahLog');
  if (!ahState.turns.length) {
    log.innerHTML = '';           // 空态交给简报渲染，这里不再放占位
    return;
  }
  log.innerHTML = ahState.turns.map(ahTurn).join('');
  log.querySelectorAll('[data-ah-mail]').forEach(b => b.onclick = () => {
    showCases();
    workspaceMode('inbox');
    run(showInbox);
  });
}

function ahRenderStats(ov) {
  const box = document.getElementById('ahStats');
  if (!box) return;
  box.innerHTML = ahBrief(ov) || '';
  box.querySelectorAll('[data-go]').forEach(b => b.onclick = () => ahOpen(b.dataset.go));
}

function ahMaybeInvite() {
  try {
    const done = sessionStorage.getItem('rfq-home-tour-done');
    const declined = sessionStorage.getItem('rfq-home-tour-declined');
    if (!done && !declined && !window.rfqSpotlight?.active?.() && authState.user?.role === 'demo') {
      window.rfqSpotlight?.invite();
    }
  } catch {}
}

async function ahLoad() {
  if (ahState.loading) return;
  ahState.loading = true;
  ahState.started = true;
  try {
  const ov = await request('/agent/overview').catch(() => null);
  ahState.overview = ov;
  ahRenderStats(ov);
  if (ov) {
    const mailTotal = (ov.mails?.total || 0);
    const caseTotal = (ov.cases || []).length;
    $('ahMailCount').textContent = mailTotal; $('ahMailCount').hidden = !mailTotal;
    $('ahCaseCount').textContent = caseTotal; $('ahCaseCount').hidden = !caseTotal;
    $('ahDate').textContent = (ov.today || '').replace(/-/g, ' / ');
    const todo = ov.todo || [];
    $('ahSub').textContent = todo.length
      ? `${todo.map(t => t.text).join('，')}。可以问它，也可以直接点下面的数字进去。`
      : '当前没有待办。可以让它按件号查库存、历史报价或替代件。';
  }

  const history = await request('/agent/home').catch(() => ({turns: []}));
  ahState.turns = history.turns || [];
  ahRenderLog();
  ahRenderBrief(ov);
  } finally {
    ahState.loading = false;
  }
}

/* 简报：数字都在卡上，这里只给一句建议，不占一次模型调用。 */
function ahRenderBrief(ov) {
  const box = document.getElementById('ahLog');
  if (!box) return;
  if (ahState.turns.length) return;            // 已经有对话就不重复
  box.querySelectorAll('.ah-briefline').forEach(el => el.remove());
  if (box.querySelector('.ah-briefline')) return;
  const m = ov?.mails || {}, cats = m.by_category || {};
  const needReview = m.need_review || 0, unrouted = m.unrouted || 0;
  const cases = ov?.cases || [];
  const firstCase = cases.find(c => c.next) || cases[0];
  let advice;
  if (needReview) advice = `建议先处理 ${needReview} 封 Jev 拿不准的分流，再往下走。`;
  else if (unrouted) advice = `建议先把 ${unrouted} 封还没分流的邮件过一遍，分流后就能进工作单。`;
  else if (firstCase) advice = `建议从工作单「${firstCase.title}」继续：${firstCase.next}。`;
  else advice = '现在没有待办。可以直接问它按件号查库存、历史报价或替代件。';
  const line = document.createElement('div');
  line.className = 'ah-msg bot ah-briefline';
  line.innerHTML = `<div class="ah-who"><span class="ah-avatar">R</span><b>今日简报</b><small>系统汇总 · 未调用模型</small></div>
    <p class="ah-text">${ahEsc(advice)}</p>
    <p class="ah-hint">有问题直接在下面问，例如“那个液压系统的密封圈还有多少库存”。</p>`;
  box.append(line);
}

async function ahOpening() {}  // 开场改成本地简报，不再调用模型

async function ahAsk(text, opts = {}) {
  if (ahState.busy) return;
  if (!ahState.started) await ahLoad();
  ahState.busy = true;
  $('ahSend').disabled = true;
  $('ahStatus').classList.remove('error');
  $('ahStatus').textContent = '正在处理…';
  const pending = {message: text, reply: '', steps: [], pending: true};
  ahState.turns.push(pending);
  ahRenderLog();
  try {
    const post = () => request('/agent/home', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, consent: true}),
    });
    let data;
    try {
      data = await post();
    } catch (first) {
      // 开场这一轮偶尔会撞上模型慢或被拒；再试一次，别让第一眼就是兜底。
      if (!opts.opening) throw first;
      $('ahStatus').textContent = '模型这会儿没回应，正在重试…';
      await new Promise(r => setTimeout(r, 1500));
      data = await post();
    }
    ahState.turns[ahState.turns.length - 1] = data.turn;
    ahRenderLog();
    $('ahStatus').textContent = '';
    const ov = await request('/agent/overview').catch(() => null);
    if (ov) { ahState.overview = ov; ahRenderStats(ov); }
  } catch (error) {
    pending.pending = false;
    pending.error = true;
    pending.reply = '未完成：' + (error.message || '暂时无法连接，请稍后重试');
    ahRenderLog();
    // Keep both the failed question and anything typed while it was waiting.
    if (!$('ahInput').value.trim()) $('ahInput').value = text;
    $('ahStatus').textContent = pending.reply + '，可以重试。';
    $('ahStatus').classList.add('error');
    if (opts.opening) {
      // 模型没响应时，用已经拿到的真实计数做一份本地汇报，别让第一眼是报错。
      const ov = ahState.overview;
      const m = ov?.mails || {}, cats = m.by_category || {};
      const parts = Object.entries(cats).map(([k, v]) => `${ahLabels[k] || k} ${v}`).join('、');
      const text = ov
        ? `今天有 ${(ov.mails?.total || 0)} 封邮件${parts ? '（Jev 初筛：' + parts + '）' : ''}、${(ov.cases || []).length} 张工作单。${(ov.todo || []).map(t => t.text).join('；') || '暂时没有待办。'}。模型这会儿没响应，这份是系统直接汇总的；可以直接点上方入口，或再问我一次。`
        : '暂时读不到待办，可以直接点上方入口查看收件箱与工作单。';
      ahState.turns.push({message: '先看看现在有什么需要我处理的。', reply: text, steps: [], local: true});
      ahRenderLog();
    }
  } finally {
    ahState.busy = false;
    $('ahSend').disabled = false;
  }
}

function ahOpen(mode) {
  showCases();
  if (mode === 'inbox') { workspaceMode('inbox'); run(showInbox); }
  else if (mode === 'references') { workspaceMode('references'); renderReferences($('onsiteHomePanel')); }
  else if (mode === 'import') { $('uploadLanding')?.click(); }
}

$('ahForm').onsubmit = e => {
  e.preventDefault();
  const text = $('ahInput').value.trim();
  if (!text) return;
  $('ahInput').value = '';
  run(() => ahAsk(text));
};
document.querySelectorAll('[data-ah-go]').forEach(b => b.onclick = () => ahOpen(b.dataset.ahGo));
$('ahInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('ahForm').requestSubmit(); }
});
window.renderAgentHome = () => { ahMaybeInvite(); run(ahLoad); };
