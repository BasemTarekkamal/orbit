/* Staffroom control panel. Plain JavaScript, no build step: it reads the JSON API in core/panel.py and
   renders each page as HTML. Polls every 8 seconds while the tab is visible; never re-renders while
   you're typing. */
'use strict';

// ---------------------------------------------------------------- utils
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const main = $('#main');
const side = $('#side');
const JOB_LABELS = { brief: 'Morning brief', standup: 'Standup', eod: 'End of day', scout: 'Self-improvement', evals: 'Weekly self-test' };
const MODELS = ['opus', 'sonnet', 'haiku'];
const MEMORY = [['STATE.md', 'State'], ['TASKS.md', 'Tasks'], ['GOALS.md', 'Goals'], ['LESSONS.md', 'Lessons'], ['CLAUDE.md', 'Instructions']];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const I = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M3 20c.5-4 3-6 6-6s5.5 2 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.5c2.5.2 4 2 4.5 5.5"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M4 12h16M4 17h16"/><path d="m8 5 2 2-2 2M8 10l2 2-2 2M8 15l2 2-2 2" opacity=".0"/><circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none"/><circle cx="7" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="7" cy="17" r="1.2" fill="currentColor" stroke="none"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  circle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="7.5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 2.8 19.5h18.4L12 4Z"/><path d="M12 10v4M12 17h.01"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.5"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 6v12M15 6v12"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l10-6.5z"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.6-4 3.4-6 7-6s6.4 2 7 6"/></svg>',
  gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 16a8 8 0 1 1 16 0"/><path d="m12 16 4-5"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 6h6l2 2h10v11H3z"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12 20 4l-4 16-4-7z"/></svg>',
};
const icon = (n) => I[n] || '';

function hue(id) { let h = 0; for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 8; }
function avatar(id, name, size = '') {
  const owner = !S.data || !S.data.employees.some((e) => e.id === id);
  const cls = owner ? 'owner' : 'hue-' + hue(id);
  return `<span class="avatar ${cls} ${size}" aria-hidden="true">${esc(String(name || id || '?').trim().charAt(0).toUpperCase())}</span>`;
}
function parseTs(ts) { if (!ts) return null; const d = new Date(String(ts).replace(' ', 'T')); return isNaN(d) ? null : d; }
const sameDay = (a, b) => a.toDateString() === b.toDateString();
function dayLabel(d) {
  const now = new Date(); if (sameDay(d, now)) return 'Today';
  const y = new Date(now); y.setDate(now.getDate() - 1); if (sameDay(d, y)) return 'Yesterday';
  const t = new Date(now); t.setDate(now.getDate() + 1); if (sameDay(d, t)) return 'Tomorrow';
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}
function hm(d) { return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function fmtTime(ts) { const d = parseTs(ts); if (!d) return ''; const l = dayLabel(d); return l === 'Today' ? hm(d) : l + ' ' + hm(d); }
function money(n) { return '$' + (Number(n) || 0).toFixed(2); }
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }
function sortedByTs(rows) { return rows.slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts))); }

// ---------------------------------------------------------------- state & api
const S = { data: null, detail: null, detailId: null, detailAt: 0, cat: null, roles: null, settings: null, file: null, fileLoading: '',
  theme: localStorage.getItem('theme') || '', lastHtml: '', vals: {}, hireRole: null, busy: new Set() };

async function api(path, body) {
  const opt = body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error(j.error || (r.status === 401 ? 'Signed out: run `staff panel` to open the panel again.' : 'HTTP ' + r.status));
  return j;
}
async function refresh(nav) {
  S.data = await api('/api/state');
  const r = route();
  if (r.page === 'employee') await loadDetail(r.id);
  await render(nav);
}
async function loadDetail(id) {
  try { S.detail = await api('/api/employee/' + id); S.detailId = id; S.detailAt = Date.now(); }
  catch (e) { S.detail = null; S.detailId = id; }
}

function toast(msg, kind) {
  const el = document.createElement('div');
  el.className = 'toast' + (kind === 'err' ? ' err' : '');
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 200); }, kind === 'err' ? 7000 : 3800);
}

function setTheme(t) {
  S.theme = t;
  if (t) localStorage.setItem('theme', t); else localStorage.removeItem('theme');
  if (t) document.documentElement.setAttribute('data-theme', t); else document.documentElement.removeAttribute('data-theme');
}
setTheme(S.theme);

// ---------------------------------------------------------------- routing
function route() {
  const p = location.pathname.replace(/\/+$/, '') || '/';
  const q = new URLSearchParams(location.search);
  if (p === '/') return { page: 'today' };
  if (p === '/team') return { page: 'team' };
  if (p === '/hire') return { page: 'hire', role: q.get('role') };
  if (p === '/abilities') return { page: 'abilities' };
  if (p === '/settings') return { page: 'settings' };
  const m = p.match(/^\/e\/([a-z0-9-]+)(?:\/(chat|memory|work|activity|abilities))?$/);
  if (m) return { page: 'employee', id: m[1], tab: m[2] || 'chat', say: q.get('say') || '', f: q.get('f') || '' };
  return { page: 'missing' };
}
function go(path) { history.pushState(null, '', path); render(true); }
window.addEventListener('popstate', () => render(true));

// ---------------------------------------------------------------- render
async function render(nav) {
  const r = route();
  if (!S.data) {
    try { S.data = await api('/api/state'); }
    catch (e) { main.innerHTML = `<div class="empty"><b>Can't reach the panel.</b><p>${esc(e.message)}</p></div>`; return; }
  }
  try {
    if (r.page === 'employee' && (S.detailId !== r.id || !S.detail || nav)) await loadDetail(r.id);
    if ((r.page === 'abilities' || r.page === 'employee') && !S.cat) S.cat = await api('/api/abilities');
    if (r.page === 'hire' && !S.roles) S.roles = await api('/api/roles');
    if (r.page === 'settings' && (nav || !S.settings)) S.settings = await api('/api/settings');
  } catch (e) { toast(e.message, 'err'); }
  renderSide(r);
  const active = document.activeElement;
  const typing = active && main.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName) && !nav;
  if (typing) return;
  const html = (PAGES[r.page] || PAGES.missing)(r);
  if (nav || html !== S.lastHtml) {
    const y = window.scrollY;
    main.innerHTML = html;
    S.lastHtml = html;
    afterRender(r, nav);
    if (nav) window.scrollTo(0, r.page === 'employee' && r.tab === 'chat' ? document.body.scrollHeight : 0);
    else window.scrollTo(0, y);
  }
  document.title = titleFor(r);
}
function titleFor(r) {
  const t = S.data.team_name;
  if (r.page === 'employee') { const e = S.data.employees.find((x) => x.id === r.id); return (e ? e.name : 'Employee') + ' · ' + t; }
  return { today: 'Today', team: 'Team', hire: 'Hire', abilities: 'Abilities', settings: 'Settings' }[r.page] + ' · ' + t;
}

function renderSide(r) {
  const d = S.data;
  const on = (p) => (r.page === p ? 'on' : '');
  const emps = d.employees.map((e) => {
    const st = e.status === 'paused' ? 'paused' : e.doing ? 'working' : 'active';
    const note = e.doing ? 'working' : e.status === 'paused' ? 'paused' : '';
    return `<a class="emp ${r.page === 'employee' && r.id === e.id ? 'on' : ''}" href="/e/${e.id}"><i class="dot ${st}"></i><span>${esc(e.name)}</span><small>${note}</small></a>`;
  }).join('');
  const u = d.usage || {};
  const meters = ['five_hour', 'seven_day'].filter((k) => k in u).map((k) => {
    const pct = Math.max(0, Math.min(100, u[k]));
    return `<div class="row"><span>${k === 'five_hour' ? '5-hour limit' : 'Weekly limit'}</span><span class="num">${Math.round(pct)}%</span></div><div class="meter ${pct >= 80 ? 'hot' : ''}"><i data-w="${pct}"></i></div>`;
  }).join('');
  const today = d.employees.reduce((a, e) => a + e.use_today, 0);
  side.innerHTML = `
    <div class="brand"><img src="/icon.svg" alt=""><div><b>${esc(d.team_name)}</b><span class="meta"><i class="dot ${d.online ? 'active' : 'off'}"></i>${d.online ? 'Running' : 'Service stopped'}</span></div></div>
    <nav class="nav">
      <a href="/" class="${on('today')}">${icon('home')}Today</a>
      <a href="/team" class="${on('team')}">${icon('users')}Team</a>
      <a href="/abilities" class="${on('abilities')}">${icon('grid')}Abilities</a>
      <a href="/settings" class="${on('settings')}">${icon('sliders')}Settings</a>
    </nav>
    <a class="btn btn-primary hire" href="/hire">${icon('plus')}Hire someone</a>
    <h3>Employees</h3>
    <nav class="nav emps">${emps || '<span class="faint small pad">None yet</span>'}</nav>
    <div class="spacer"></div>
    <div class="use">${meters}<div class="row"><span>Plan use today</span><span class="num">≈${money(today)}</span></div></div>
    <div class="theme"><span>Appearance</span><div class="seg" role="group" aria-label="Appearance">
      <button data-act="theme" data-v="" class="${S.theme === '' ? 'on' : ''}">Auto</button>
      <button data-act="theme" data-v="light" class="${S.theme === 'light' ? 'on' : ''}">Light</button>
      <button data-act="theme" data-v="dark" class="${S.theme === 'dark' ? 'on' : ''}">Dark</button></div></div>`;
  side.querySelectorAll('[data-w]').forEach((el) => { el.style.width = el.dataset.w + '%'; });
}

function afterRender(r, nav) {
  main.querySelectorAll('[data-w]').forEach((el) => { el.style.width = el.dataset.w + '%'; });
  main.querySelectorAll('textarea[data-grow]').forEach(grow);
  if (r.page === 'employee' && r.tab === 'chat') {
    const ta = $('.composer textarea', main);
    if (ta && nav) { if (r.say && !ta.value) { ta.value = r.say; grow(ta); } if (r.say) ta.focus(); }
  }
  if (r.page === 'employee' && r.tab === 'work' && r.f) ensureFile(r.id, r.f);
}
function grow(ta) { ta.style.height = 'auto'; ta.style.height = Math.min(240, ta.scrollHeight + 2) + 'px'; }
function v(form, name, dflt) { const f = S.vals[form]; return f && name in f ? f[name] : dflt; }

// ---------------------------------------------------------------- pages
const PAGES = {};

PAGES.missing = () => `<div class="empty"><b>No such page.</b><p><a class="link" href="/">Back to Today</a></p></div>`;

PAGES.today = () => {
  const d = S.data, emps = d.employees, h = new Date().getHours();
  const greet = h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const working = Object.keys(d.working).map((id) => emps.find((e) => e.id === id)).filter(Boolean);
  const required = d.checklist.filter((c) => !c.optional);
  const showSetup = required.some((c) => !c.done);
  const date = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  let sub = date;
  if (!emps.length) sub += ' · no employees yet';
  else if (emps.length === 1) sub += ` · ${esc(emps[0].name)} is ${emps[0].doing ? 'working: ' + esc(emps[0].doing) : emps[0].status === 'paused' ? 'paused' : 'idle'}`;
  else sub += ` · ${plural(emps.length, 'employee')} · ${working.length ? working.length + ' working' : 'all idle'}`;
  if (!d.online) sub += ' · <span class="badge danger">service stopped</span>';

  const setup = showSetup ? `<div class="setup"><h2>Set up your team</h2><ol>${d.checklist.map((c) => `
    <li class="${c.done ? 'done' : ''}">${icon(c.done ? 'check' : 'circle')}<div><span>${esc(c.title)}${c.optional ? ' <span class="meta">optional</span>' : ''}</span>${c.done ? '' : `<div class="how">${esc(c.how)}</div>`}</div></li>`).join('')}</ol></div>` : '';

  const kinds = { owner: 'user', failed: 'alert', paused: 'pause', waiting: 'clock', reminder: 'bell', usage: 'gauge' };
  const needs = d.needs.length ? `<div class="list needs">${d.needs.map((n) => `
    <a class="row ${n.kind}" href="${esc(n.href)}"><span class="k">${icon(kinds[n.kind] || 'alert')}</span><div><div class="title">${esc(n.title)}</div><div class="meta">${esc(n.detail)}</div></div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`).join('')}</div>`
    : `<p class="quiet">Nothing needs you right now.</p>`;

  const now = new Date();
  let feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && sameDay(t, now); });
  if (feed.length < 4) { const y = new Date(now); y.setDate(now.getDate() - 1); feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && (sameDay(t, now) || sameDay(t, y)); }); }
  const timeline = feed.length ? `<div class="timeline">${withDays(feed.slice(-40), (f) => tlItem(f), true)}</div>`
    : `<div class="empty"><b>Quiet so far.</b><p>${emps.length ? 'What your team says to you and to each other shows up here. Say hello to someone, or wait for the morning brief.' : 'Hire your first employee and this is where their work shows up.'}</p></div>`;

  const mini = emps.length ? `<div class="list mini">${emps.map((e) => `<a class="row" href="/e/${e.id}">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)}</div><div class="meta">${esc(empNow(e))}</div></div>${statusHtml(e)}</a>`).join('')}</div>`
    : `<p class="quiet">No employees yet. <a class="link" href="/hire">Hire someone</a>.</p>`;
  const useToday = emps.reduce((a, e) => a + e.use_today, 0), use7 = emps.reduce((a, e) => a + e.use_7d, 0);
  const u = d.usage || {};
  const usage = `<div class="usage-box"><div class="row2"><span>Today</span><b class="num">≈${money(useToday)}</b></div><div class="row2"><span>Last 7 days</span><b class="num">≈${money(use7)}</b></div>
    ${['five_hour', 'seven_day'].filter((k) => k in u).map((k) => `<div class="row2"><span>${k === 'five_hour' ? '5-hour limit' : 'Weekly limit'}</span><b class="num">${Math.round(u[k])}% used</b></div>`).join('')}
    <p class="meta">API-equivalent value of the runs. Nothing is billed on a subscription; the runs use your plan's limits.</p></div>`;
  const orders = d.orders.slice(-6).reverse();
  const ordHtml = orders.length ? `<div class="list mini">${orders.map((o) => `<div class="row row-2"><div><div class="small">${esc(o.summary)}</div><div class="meta">${esc(o.by)} · ${fmtTime(o.ts)}${o.result ? ' · ' + esc(o.result) : ''}</div></div><span class="badge ${o.status === 'failed' ? 'danger' : ''}">${esc(o.status)}</span></div>`).join('')}</div>` : `<p class="quiet">No orders yet.</p>`;

  return `<header class="greet"><h1>${greet}, ${esc(d.me)}.</h1><p class="sub">${sub}</p></header>${setup}
    <div class="cols"><div>
      <section><div class="sec-head"><h2>Needs you</h2>${d.needs.length ? `<span class="meta">${d.needs.length}</span>` : ''}</div>${needs}</section>
      <section><div class="sec-head"><h2>Today</h2><span class="meta">the team room</span></div>${timeline}</section>
    </div><aside>
      <section><div class="sec-head"><h2>Team</h2><a class="link small" href="/team">All</a></div>${mini}</section>
      <section><div class="sec-head"><h2>Plan use</h2></div>${usage}</section>
      <section><div class="sec-head"><h2>Recent orders</h2></div>${ordHtml}</section>
    </aside></div>`;
};

function empNow(e) {
  if (e.status === 'paused') return 'Paused';
  if (e.doing) return e.doing;
  if (e.next_job) return `Next: ${e.next_job} · ${fmtTime(e.next_job_at)}`;
  return e.last_run ? `Last run ${fmtTime(e.last_run)}` : 'Hasn\'t run yet';
}
function statusHtml(e) {
  if (!S.data.online) return `<span class="status"><i class="dot off"></i>Offline</span>`;
  if (e.status === 'paused') return `<span class="status"><i class="dot paused"></i>Paused</span>`;
  if (e.doing) return `<span class="status"><i class="dot working"></i>Working</span>`;
  return `<span class="status"><i class="dot active"></i>Idle</span>`;
}
function nameOf(id) { if (id === 'team') return 'Team'; const e = S.data.employees.find((x) => x.id === id); return e ? e.name : id; }
function channelBadge(c) { return c && c !== 'bus' ? `<span class="badge">${{ panel: 'Panel', telegram: 'Telegram', job: 'Routine', hq: 'Panel' }[c] || esc(c)}</span>` : ''; }
function withDays(rows, fn, skipToday) {
  let last = ''; let out = '';
  for (const r of rows) {
    const t = parseTs(r.ts); const l = t ? dayLabel(t) : '';
    if (l !== last) { if (!(skipToday && l === 'Today' && !last)) out += `<div class="day-sep">${esc(l)}</div>`; last = l; }
    out += fn(r);
  }
  return out;
}
function tlItem(f) {
  const long = (f.body || '').length > 600;
  return `<div class="tl">${avatar(f.from_id, f.from_name)}<div><div class="head"><b>${esc(f.from_name)}</b><span>→ ${esc(nameOf(f.to_id))}</span><span>·</span><span>${fmtTime(f.ts)}</span>${channelBadge(f.channel)}</div>
    <div class="body ${long ? 'clamp' : ''}">${esc(f.body)}</div>${long ? `<button class="btn btn-ghost btn-sm more" data-act="more">Show more</button>` : ''}</div></div>`;
}

PAGES.team = () => {
  const d = S.data, emps = d.employees;
  const working = emps.filter((e) => e.doing).length;
  const rows = emps.map((e) => `<a class="row team-row" href="/e/${e.id}">
    <div class="who">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)}</div><div class="meta">${esc(e.role)} · reports to ${esc(e.supervisor)}</div></div></div>
    ${statusHtml(e)}
    <div class="c-next small muted">${esc(empNow(e))}</div>
    <div class="c-today small muted num">${e.runs_today ? `${plural(e.runs_today, 'run')} · ≈${money(e.use_today)}` : 'No runs today'}${e.failures_today ? ` · <span class="badge danger">${e.failures_today} failed</span>` : ''}</div>
    <div class="c-model small muted">${esc(e.model)}</div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`).join('');
  return `<header class="page-head"><div><h1>Team</h1><p class="sub">${emps.length ? `${plural(emps.length, 'employee')}${working ? ` · ${working} working` : ''}` : 'Nobody works here yet.'}</p></div>
    <div class="actions"><a class="btn btn-primary" href="/hire">${icon('plus')}Hire someone</a></div></header>
    ${emps.length ? `<div class="list">${rows}</div>` : `<div class="empty"><b>Your first employee is one click away.</b><p>Pick a role on the Hire page: they come with the whole toolbelt, a memory, and a morning brief.</p></div>`}`;
};

// ---------------------------------------------------------------- employee
PAGES.employee = (r) => {
  const e = S.data.employees.find((x) => x.id === r.id);
  if (!e) return `<div class="empty"><b>No employee called “${esc(r.id)}”.</b><p><a class="link" href="/team">Back to the team</a></p></div>`;
  const dt = S.detail && S.detailId === r.id ? S.detail : null;
  const paused = e.status === 'paused';
  const jobs = Object.entries(JOB_LABELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
  const models = MODELS.map((m) => `<option ${m === e.model ? 'selected' : ''}>${m}</option>`).join('');
  const tabs = [['chat', 'Chat', ''], ['memory', 'Memory', ''], ['work', 'Work', dt ? dt.files.length : ''], ['activity', 'Activity', e.runs_today || ''], ['abilities', 'Abilities', `${e.abilities_on}/${e.abilities_total}`]];
  const body = { chat: tabChat, memory: tabMemory, work: tabWork, activity: tabActivity, abilities: tabAbilities }[r.tab](e, dt, r);
  return `<header class="emp-head">${avatar(e.id, e.name, 'lg')}<div class="id"><h1>${esc(e.name)}</h1><div class="sub"><span>${esc(e.role)}</span><span>·</span><span>reports to ${esc(e.supervisor)}</span><span>·</span>${statusHtml(e)}</div></div>
    <div class="actions">
      <button class="btn" data-act="order" data-kind="${paused ? 'resume' : 'pause'}" data-emp="${e.id}">${icon(paused ? 'play' : 'pause')}${paused ? 'Resume' : 'Pause'}</button>
      <span class="status"><select class="select auto" id="run-job" aria-label="Routine">${jobs}</select><button class="btn" data-act="order" data-kind="run_job" data-emp="${e.id}" data-from="#run-job" ${paused ? 'disabled' : ''}>Run now</button></span>
      <select class="select auto" data-field="model" data-emp="${e.id}" aria-label="Model">${models}</select>
      <button class="btn btn-ghost btn-danger" data-act="retire" data-emp="${e.id}" data-name="${esc(e.name)}">Retire…</button>
    </div></header>
    <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="/e/${e.id}/${k}" class="${r.tab === k ? 'on' : ''}">${l}${n !== '' ? `<small>${esc(n)}</small>` : ''}</a>`).join('')}</nav>
    ${body}`;
};

function tabChat(e, dt, r) {
  const rows = dt ? dt.chat : [];
  const working = S.data.working[e.id];
  const thread = rows.length ? `<div class="thread">${withDays(rows, (m) => { const owner = m.from_id !== e.id; return `<div class="msg ${owner ? 'owner' : ''}">${avatar(m.from_id, m.from_name, 'sm')}<div><div class="head"><b>${esc(m.from_name)}</b>${m.to_id && m.to_id !== e.id && m.to_id !== 'owner' ? `<span>→ ${esc(nameOf(m.to_id))}</span>` : ''}<span>${hm(parseTs(m.ts) || new Date())}</span>${channelBadge(m.channel)}</div><div class="body">${esc(m.body)}</div></div></div>`; })}</div>`
    : `<div class="empty"><b>No conversation yet.</b><p>${esc(e.name)} answers here within a minute or so. What they learn goes into their memory files.</p></div>`;
  return `${thread}${working ? `<p class="working mt"><i class="dot working"></i>${esc(e.name)} is working: ${esc(working)}…</p>` : ''}
    <form class="composer" data-form="message" data-emp="${e.id}"><div class="box"><textarea name="text" data-grow rows="1" placeholder="Message ${esc(e.name)}…" aria-label="Message" required maxlength="4000">${esc(v('message:' + e.id, 'text', ''))}</textarea>
    <div class="bar"><span class="meta"><kbd>⌘</kbd><kbd>↩</kbd> to send · they answer here, usually within a minute</span><button class="btn btn-primary btn-sm" type="submit">${icon('send')}Send</button></div></div></form>`;
}

function tabMemory(e, dt, r) {
  const f = MEMORY.some(([k]) => k === r.f) ? r.f : 'STATE.md';
  const subs = MEMORY.map(([k, l]) => `<a href="/e/${e.id}/memory?f=${k}" class="${f === k ? 'on' : ''}">${l}</a>`).join('');
  if (!dt) return `<div class="subtabs">${subs}</div><p class="quiet">Loading…</p>`;
  const text = dt.memory[f] || '';
  let extra = '';
  if (f === 'CLAUDE.md') {
    const i = text.indexOf('## Role-specific rules');
    const rules = i >= 0 ? text.slice(i + '## Role-specific rules'.length).trim() : '';
    extra = `<hr><form class="form prose" data-form="rules" data-emp="${e.id}"><div class="field"><label for="rules">Rules you set</label><textarea id="rules" class="textarea" name="text" rows="6" placeholder="One rule per line. Example: Reply in Arabic. Always give three options. Never contact suppliers yourself.">${esc(v('rules:' + e.id, 'text', rules.startsWith('_') ? '' : rules))}</textarea><span class="hint">Saved into the “Role-specific rules” section of their instructions. They read it on every run.</span></div><div class="save-bar"><button class="btn btn-primary" type="submit">Save rules</button></div></form>`;
  }
  return `<div class="subtabs">${subs}</div><div class="md">${md(text) || '<p class="quiet">Empty.</p>'}</div>${extra}
    <p class="meta mt-lg">Folder on this Mac: <code>${esc(dt.workspace)}</code></p>`;
}

function tabWork(e, dt, r) {
  if (!dt) return `<p class="quiet">Loading…</p>`;
  if (!dt.files.length) return `<div class="empty"><b>No work yet.</b><p>Files ${esc(e.name)} writes (research notes, scrapes, tools, growth log) appear here.</p></div>`;
  const groups = {};
  for (const f of dt.files) { const g = f.path.split('/')[0]; (groups[g] ||= []).push(f); }
  const list = Object.entries(groups).map(([g, fs]) => `<h3>${esc(g)}</h3>${fs.slice(0, 60).map((f) => f.text
    ? `<a href="/e/${e.id}/work?f=${encodeURIComponent(f.path)}" class="${r.f === f.path ? 'on' : ''}" title="${esc(f.path)} · ${fmtTime(f.mtime)}">${icon('file')}<span>${esc(f.path.slice(g.length + 1))}</span></a>`
    : `<span class="faint small pad">${esc(f.path.slice(g.length + 1))}</span>`).join('')}`).join('');
  let preview = `<div class="empty"><p>Pick a file to read it here. Newest first.</p></div>`;
  if (r.f) {
    const key = e.id + ':' + r.f;
    if (S.file && S.file.key === key) {
      const t = S.file.data.text;
      preview = `<div class="path"><span>${esc(r.f)}</span><span>${S.file.data.truncated ? 'first 400 KB' : ''}</span></div>${/\.md$/i.test(r.f) ? `<div class="md">${md(t)}</div>` : `<pre class="raw">${esc(t)}</pre>`}`;
    } else preview = `<p class="quiet">Loading ${esc(r.f)}…</p>`;
  }
  return `<div class="work"><div class="files">${list}</div><div class="preview">${preview}</div></div>`;
}
async function ensureFile(emp, path) {
  const key = emp + ':' + path;
  if ((S.file && S.file.key === key) || S.fileLoading === key) return;
  S.fileLoading = key;
  try { S.file = { key, data: await api(`/api/file?emp=${encodeURIComponent(emp)}&path=${encodeURIComponent(path)}`) }; }
  catch (e) { S.file = { key, data: { text: 'Could not open: ' + e.message, truncated: false } }; }
  S.fileLoading = '';
  render(false);
}

function tabActivity(e, dt) {
  if (!dt) return `<p class="quiet">Loading…</p>`;
  if (!dt.runs.length) return `<div class="empty"><b>No runs yet.</b><p>Every chat, routine and bus answer is logged here with its duration and plan use.</p></div>`;
  return `<table class="table"><thead><tr><th>When</th><th>What</th><th>Model</th><th class="num">Time</th><th class="num">Plan use</th><th>Result</th></tr></thead><tbody>
    ${dt.runs.map((x) => `<tr><td class="num">${fmtTime(x.ts)}</td><td>${esc(JOB_LABELS[x.job] || x.job)}</td><td class="muted">${esc(x.model || '')}</td><td class="num">${x.secs}s</td><td class="num">≈${money(x.cost_usd)}</td><td class="${x.ok ? '' : 'err'}">${x.ok ? 'ok' : esc(x.error || 'failed')}</td></tr>`).join('')}</tbody></table>`;
}

function tabAbilities(e, dt) {
  if (!S.cat || !dt) return `<p class="quiet">Loading…</p>`;
  const on = new Set(dt.abilities);
  const groups = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<div class="ab-group"><h3>${esc(g)}</h3>${items.map((a) => a.locked
      ? `<div class="ab">${icon('check')}<div><div class="n">${esc(a.name)}<span class="badge">always on</span></div><div class="d">${esc(a.description)}</div></div></div>`
      : `<label class="ab"><input type="checkbox" name="abilities" value="${a.id}" ${on.has(a.id) ? 'checked' : ''} form="ab-${e.id}"><div><div class="n">${esc(a.name)}${a.paid ? '<span class="badge warn">paid</span>' : ''}${a.job ? '<span class="badge">routine</span>' : ''}</div><div class="d">${esc(a.description)}</div></div></label>`).join('')}</div>`;
  }).join('');
  return `<form id="ab-${e.id}" data-form="abilities" data-emp="${e.id}"><div class="ab-bar"><button class="btn btn-primary" type="submit">Save</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super agent</button><span class="meta">${on.size} of ${S.cat.abilities.length} on · changes apply on their next run</span></div></form>
    <div class="ab-groups">${groups}</div>`;
}

// ---------------------------------------------------------------- abilities matrix
PAGES.abilities = () => {
  const d = S.data, emps = d.employees;
  if (!S.cat) return `<p class="quiet">Loading…</p>`;
  if (!emps.length) return `<header class="page-head"><div><h1>Abilities</h1></div></header><div class="empty"><b>Hire someone first.</b><p>Their abilities appear here as a column of checkboxes.</p></div>`;
  const eff = {}; emps.forEach((e) => { eff[e.id] = null; });
  const head = emps.map((e) => `<th><div>${esc(e.name)}</div><div class="acts"><button class="btn btn-sm btn-primary" type="submit" form="mx-${e.id}">Save</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super</button></div></th>`).join('');
  const rows = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<tr class="g"><th colspan="${emps.length + 1}">${esc(g)}</th></tr>` + items.map((a) => `<tr><td><div>${esc(a.name)}${a.paid ? ' <span class="badge warn">paid</span>' : ''}</div><div class="d">${esc(a.description)}</div></td>${emps.map((e) => a.locked
      ? `<td class="c" title="Always on">${icon('check')}</td>`
      : `<td class="c"><input type="checkbox" form="mx-${e.id}" name="abilities" value="${a.id}" ${matrixOn(e.id, a.id) ? 'checked' : ''} aria-label="${esc(a.name)} for ${esc(e.name)}"></td>`).join('')}</tr>`).join('');
  }).join('');
  return `<header class="page-head"><div><h1>Abilities</h1><p class="sub">Tick what each employee may do. <b>Default</b> is a capable, low-cost setup; <b>Super agent</b> ticks everything. Changes apply on their next run.</p></div></header>
    ${emps.map((e) => `<form id="mx-${e.id}" data-form="abilities" data-emp="${e.id}"></form>`).join('')}
    <div class="matrix-wrap"><table class="matrix"><thead><tr><th>Ability</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
};
function matrixOn(empId, abId) { const e = S.data.employees.find((x) => x.id === empId); return !!e && (e.abilities || []).includes(abId); }

// ---------------------------------------------------------------- hire
PAGES.hire = (r) => {
  const d = S.data;
  if (!S.roles) return `<p class="quiet">Loading…</p>`;
  if (r.role && !S.hireRole) pickRole(r.role, false);
  const roles = S.roles.roles;
  const sel = roles.find((x) => x.id === S.hireRole);
  const owners = d.owners.map((o) => `<option ${o.name === v('hire', 'supervisor', d.me) ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
  const tiles = roles.map((x) => `<button type="button" class="role ${S.hireRole === x.id ? 'on' : ''}" data-act="role" data-role="${x.id}" aria-pressed="${S.hireRole === x.id}"><b>${esc(x.title)}</b><p>${esc(x.blurb)}</p></button>`).join('');
  const names = sel && sel.names.length ? `<div class="chips">${sel.names.map((n) => `<button type="button" class="chip ${v('hire', 'name', '') === n ? 'on' : ''}" data-act="name" data-name="${esc(n)}">${esc(n)}</button>`).join('')}</div>` : '';
  const gets = sel ? `<ul class="gets">${sel.gets.map((g) => `<li>${icon('check')}<span>${esc(g)}</span></li>`).join('')}</ul>` : '';
  const form = sel ? `<form class="form max-720" data-form="hire">
    <div class="form-row"><div class="field"><label for="h-name">Name</label><input id="h-name" class="input" name="name" required maxlength="60" value="${esc(v('hire', 'name', ''))}" placeholder="Sara">${names}</div>
    <div class="field"><label for="h-role">Role</label><input id="h-role" class="input" name="role" required maxlength="120" value="${esc(v('hire', 'role', sel.role))}" placeholder="Market researcher"></div></div>
    <div class="field"><label for="h-scope">What they own</label><textarea id="h-scope" class="textarea" name="scope" rows="4" maxlength="2000" placeholder="Competitors, prices and social media in our market; a weekly summary for me">${esc(v('hire', 'scope', sel.scope))}</textarea><span class="hint">Their scope goes into their instructions. You can refine it any time under Memory → Instructions.</span></div>
    <div class="form-row"><div class="field"><label for="h-sup">Reports to</label><select id="h-sup" class="select" name="supervisor">${owners}</select></div>
    <div class="field"><label for="h-model">Model</label><select id="h-model" class="select" name="model">${MODELS.map((m) => `<option value="${m}" ${m === v('hire', 'model', sel.model || 'sonnet') ? 'selected' : ''}>${m}${m === 'sonnet' ? ' (balanced)' : m === 'haiku' ? ' (light, cheapest)' : ' (strongest, heaviest)'}</option>`).join('')}</select></div>
    <div class="field"><span class="lbl">Abilities</span><select class="select" name="preset">${sel.abilities ? `<option value="role" ${v('hire', 'preset', 'role') === 'role' ? 'selected' : ''}>What this role needs (${sel.abilities.length})</option>` : ''}<option value="default" ${v('hire', 'preset', sel.abilities ? 'role' : 'default') === 'default' ? 'selected' : ''}>Default set</option><option value="super" ${v('hire', 'preset', '') === 'super' ? 'selected' : ''}>Super agent (everything)</option></select></div></div>
    <div class="field"><span class="lbl">What you get</span>${gets}</div>
    <div class="save-bar"><button class="btn btn-primary" type="submit">${icon('plus')}Hire ${esc(v('hire', 'name', '') || 'them')}</button><span class="meta">They start within a minute. Their folder is created under ~/Staff/employees.</span></div></form>` : '';
  return `<header class="page-head"><div><h1>Hire someone</h1><p class="sub">Pick a role to start from. Every employee gets the whole toolbelt; the role sets the scope, the abilities and the model.</p></div></header>
    <div class="roles">${tiles}</div>${form}`;
};
function pickRole(id, rerender = true) {
  const x = S.roles.roles.find((y) => y.id === id); if (!x) return;
  S.hireRole = id;
  S.vals.hire = { name: x.names[0] || '', role: x.role, scope: x.scope, model: x.model || 'sonnet', preset: x.abilities ? 'role' : 'default', supervisor: v('hire', 'supervisor', S.data.me) };
  if (rerender) render(true);
}

// ---------------------------------------------------------------- settings
PAGES.settings = () => {
  const s = S.settings, d = S.data;
  if (!s) return `<p class="quiet">Loading…</p>`;
  const wd = v('settings', 'workdays', s.workdays);
  const days = DAYS.map((x) => `<label class="chip ${wd.includes(x) ? 'on' : ''}"><input class="sr" type="checkbox" name="workdays" value="${x}" ${wd.includes(x) ? 'checked' : ''}>${x}</label>`).join('');
  const times = Object.entries(JOB_LABELS).map(([k, l]) => `<div class="field"><label for="t-${k}">${l}</label><input id="t-${k}" class="input" name="jobs.${k}" value="${esc(v('settings', 'jobs.' + k, s.jobs[k]))}" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" inputmode="numeric" placeholder="08:30"></div>`).join('');
  const budget = Number(s.apify.monthly_budget_usd || 5), spent = Number(s.apify.spent || 0);
  const pct = budget ? Math.min(100, (spent / budget) * 100) : 0;
  const pending = d.pending.length ? `<div class="list">${d.pending.map((p) => `<div class="row row-3"><div><div class="title">${esc(p.name || 'Someone')} ${p.username ? `<span class="muted">@${esc(p.username)}</span>` : ''}</div><div class="meta">Telegram id ${esc(p.id)} · ${fmtTime(p.at)}</div></div><button class="btn btn-sm btn-primary" data-act="owner" data-id="${esc(p.id)}" data-do="approve" data-name="${esc(p.name || '')}">Make owner</button><button class="btn btn-sm" data-act="owner" data-id="${esc(p.id)}" data-do="ignore">Ignore</button></div>`).join('')}</div>` : '';
  return `<header class="page-head"><div><h1>Settings</h1></div></header>
  <div class="settings">
  <form class="settings" data-form="settings">
    <section><h2>Your business</h2><p class="desc">Every employee reads this before every run.</p>
      <div class="field"><label for="tn">Team name</label><input id="tn" class="input" name="team_name" maxlength="60" value="${esc(v('settings', 'team_name', s.team_name))}"></div>
      <div class="field"><label for="ab">About the business</label><textarea id="ab" class="textarea" name="about" rows="7" maxlength="6000" placeholder="What you do, for whom, what matters most right now, names they should know.">${esc(v('settings', 'about', s.about))}</textarea></div>
      <div class="field"><span class="lbl">Workdays</span><div class="chips">${days}</div><span class="hint">Routines run on these days.</span></div></section>
    <section><h2>Routine times</h2><p class="desc">Local time on this Mac. Each employee runs only the routines ticked in their abilities.</p><div class="times">${times}</div></section>
    <section><h2>Research budget</h2><p class="desc">Apify powers the social media, Maps and large-scale scrapers. ${s.apify.token ? 'Token set.' : 'No token yet: free account at apify.com, then run <code>staff secret apify</code> in Terminal.'}</p>
      <div class="usage-box"><div class="row2"><span>Spent this month</span><b class="num">${money(spent)} of ${money(budget)}</b></div><div class="meter ${pct >= 80 ? 'hot' : ''}"><i data-w="${pct}"></i></div></div>
      <div class="form-row"><div class="field"><label for="amb">Monthly budget (USD)</label><input id="amb" class="input" name="apify.monthly_budget_usd" inputmode="decimal" value="${esc(v('settings', 'apify.monthly_budget_usd', s.apify.monthly_budget_usd ?? 5))}"></div>
      <div class="field"><label for="amr">Max per run (USD)</label><input id="amr" class="input" name="apify.max_run_usd" inputmode="decimal" value="${esc(v('settings', 'apify.max_run_usd', s.apify.max_run_usd ?? 0.5))}"><span class="hint">Hard ceiling 2.00.</span></div></div></section>
    <section><h2>Sites their own scripts may reach</h2><p class="desc">Web search, the page reader, the browser and Apify work without this list; it only limits scripts employees write themselves.</p>
      <div class="field"><textarea class="textarea" name="network_domains" rows="3" placeholder="api.example.com&#10;*.example.org" aria-label="Allowed sites">${esc(v('settings', 'network_domains', s.network_domains.join('\n')))}</textarea></div></section>
    <div class="save-bar"><button class="btn btn-primary" type="submit">Save settings</button></div>
  </form>
  <section id="access"><h2>Access</h2><p class="desc">Owners can direct every employee. Only approve people you know.</p>
    <dl class="kv">${d.owners.map((o) => `<dt>${esc(o.name)}</dt><dd>${o.local ? 'this Mac only (pair on Telegram: message the bot, then approve yourself here)' : 'Telegram id ' + esc(o.id)}</dd>`).join('')}</dl>
    ${pending ? `<h3>Messaged your bot</h3>${pending}` : `<p class="meta">Nobody is waiting for approval.</p>`}</section>
  <section><h2>Connections</h2>
    <dl class="kv"><dt>Claude</dt><dd>${s.claude.ok ? `signed in (${esc(s.claude.note)})` : `<span class="badge danger">not signed in</span> run <code>claude auth login</code>`} · runs on ${s.auth === 'api_key' ? 'your API key' : 'your subscription'}</dd>
      <dt>Telegram bot</dt><dd>${s.telegram ? 'connected' : 'not set · <code>staff secret telegram</code>'}</dd>
      <dt>Team group</dt><dd>${s.group_id ? esc(s.group_id) : 'none · add the bot to a group as admin, then <code>staff group &lt;chat id&gt;</code>'}</dd>
      <dt>Service</dt><dd>${d.online ? 'running' : '<span class="badge danger">stopped</span> · <code>staff start</code>'} · panel on port ${s.port}</dd>
      <dt>Team folder</dt><dd><code>${esc(s.home)}</code></dd><dt>Kit</dt><dd><code>${esc(s.kit)}</code></dd></dl></section>
  <section><h2>Appearance</h2><div class="seg" role="group" aria-label="Appearance"><button data-act="theme" data-v="" class="${S.theme === '' ? 'on' : ''}">Match the Mac</button><button data-act="theme" data-v="light" class="${S.theme === 'light' ? 'on' : ''}">Light</button><button data-act="theme" data-v="dark" class="${S.theme === 'dark' ? 'on' : ''}">Dark</button></div></section>
  </div>`;
};

// ---------------------------------------------------------------- markdown (small, safe)
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return s;
}
function md(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  let out = '', i = 0;
  const isList = (l) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    if (/^```/.test(l)) { let j = i + 1, buf = []; while (j < lines.length && !/^```/.test(lines[j])) buf.push(lines[j++]); out += `<pre><code>${esc(buf.join('\n'))}</code></pre>`; i = j + 1; continue; }
    const h = l.match(/^(#{1,6})\s+(.*)$/);
    if (h) { const n = Math.min(h[1].length, 3); out += `<h${n}>${inline(h[2])}</h${n}>`; i++; continue; }
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(l)) { out += '<hr>'; i++; continue; }
    if (/^\s*\|/.test(l)) {
      const rows = []; while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
      out += '<table>' + body.map((r, k) => `<tr>${cells(r).map((c) => `<${k ? 'td' : 'th'}>${inline(c)}</${k ? 'td' : 'th'}>`).join('')}</tr>`).join('') + '</table>';
      continue;
    }
    if (/^\s*>/.test(l)) { const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, '')); out += `<blockquote>${inline(buf.join(' '))}</blockquote>`; continue; }
    if (isList(l)) {
      const ordered = /^\s*\d+[.)]/.test(l); const items = [];
      while (i < lines.length && (isList(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (isList(lines[i])) items.push(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '')); else items[items.length - 1] += ' ' + lines[i].trim();
        i++;
      }
      out += `<${ordered ? 'ol' : 'ul'}>${items.map((t) => { const task = t.match(/^\[([ xX])\]\s+(.*)$/); return task ? `<li class="task"><input type="checkbox" disabled ${task[1] !== ' ' ? 'checked' : ''}><span>${inline(task[2])}</span></li>` : `<li>${inline(t)}</li>`; }).join('')}</${ordered ? 'ol' : 'ul'}>`;
      continue;
    }
    const buf = []; while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*\||\s*>)/.test(lines[i]) && !isList(lines[i])) buf.push(lines[i++]);
    out += `<p>${inline(buf.join('\n')).replace(/\n/g, '<br>')}</p>`;
  }
  return out;
}

// ---------------------------------------------------------------- actions
async function order(body, okMsg) {
  const key = JSON.stringify(body);
  if (S.busy.has(key)) return;
  S.busy.add(key);
  try { const r = await api('/api/order', body); toast(okMsg || r.message); await refresh(false); }
  catch (e) { toast(e.message, 'err'); }
  finally { S.busy.delete(key); }
}

document.addEventListener('click', async (ev) => {
  const a = ev.target.closest('a[href]');
  if (a && a.getAttribute('href').startsWith('/') && !a.target && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey) { ev.preventDefault(); go(a.getAttribute('href')); return; }
  const b = ev.target.closest('[data-act]');
  if (!b) return;
  const act = b.dataset.act;
  if (act === 'theme') { setTheme(b.dataset.v); render(true); }
  else if (act === 'more') { const body = b.previousElementSibling; body.classList.remove('clamp'); b.remove(); }
  else if (act === 'role') { pickRole(b.dataset.role); }
  else if (act === 'name') { (S.vals.hire ||= {}).name = b.dataset.name; render(true); }
  else if (act === 'order') {
    const body = { kind: b.dataset.kind, employee_id: b.dataset.emp };
    if (b.dataset.from) body.job = $(b.dataset.from).value;
    b.disabled = true; await order(body); b.disabled = false;
  }
  else if (act === 'preset') { await order({ kind: 'set_abilities', employee_id: b.dataset.emp, preset: b.dataset.preset }); if (S.detailId === b.dataset.emp) await loadDetail(b.dataset.emp); render(true); }
  else if (act === 'retire') {
    if (confirm(`Retire ${b.dataset.name}? They stop working; their folder and memory are kept on this Mac.`)) { await order({ kind: 'retire', employee_id: b.dataset.emp }); go('/team'); }
  }
  else if (act === 'owner') {
    const name = b.dataset.do === 'approve' ? (prompt('Their name, as employees will call them:', b.dataset.name || '') || '').trim() : '';
    if (b.dataset.do === 'approve' && !name) return;
    try { const r = await api('/api/owner', { id: b.dataset.id, do: b.dataset.do, name }); toast(r.message); S.settings = await api('/api/settings'); await refresh(true); }
    catch (e) { toast(e.message, 'err'); }
  }
});

document.addEventListener('change', async (ev) => {
  const sel = ev.target.closest('select[data-field]');
  if (sel) { await order({ kind: 'set_field', employee_id: sel.dataset.emp, field: sel.dataset.field, value: sel.value }); return; }
  const chip = ev.target.closest('label.chip');
  if (chip) chip.classList.toggle('on', ev.target.checked);
});

document.addEventListener('input', (ev) => {
  const f = ev.target.closest('form[data-form]');
  if (!f || !ev.target.name) return;
  const key = f.dataset.form + (f.dataset.emp ? ':' + f.dataset.emp : '');
  const vals = (S.vals[key] ||= {});
  if (ev.target.type === 'checkbox') { const all = [...f.querySelectorAll(`input[name="${ev.target.name}"]:checked`)].map((x) => x.value); vals[ev.target.name] = all; }
  else vals[ev.target.name] = ev.target.value;
  if (ev.target.hasAttribute('data-grow')) grow(ev.target);
});

document.addEventListener('keydown', (ev) => {
  if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') { const f = ev.target.closest('form[data-form="message"]'); if (f) { ev.preventDefault(); f.requestSubmit(); } }
});

document.addEventListener('submit', async (ev) => {
  const f = ev.target.closest('form[data-form]');
  if (!f) return;
  ev.preventDefault();
  const kind = f.dataset.form, emp = f.dataset.emp;
  const fd = new FormData(f);
  const btn = f.querySelector('button[type="submit"]'); if (btn) btn.disabled = true;
  try {
    if (kind === 'message') {
      const text = (fd.get('text') || '').trim(); if (!text) return;
      const r = await api('/api/order', { kind: 'message', employee_id: emp, text });
      delete S.vals['message:' + emp]; f.querySelector('textarea').value = ''; toast(r.message);
      S.data = await api('/api/state'); await loadDetail(emp); render(true);
    } else if (kind === 'abilities') {
      const abilities = fd.getAll('abilities');
      const r = await api('/api/order', { kind: 'set_abilities', employee_id: emp, abilities });
      toast(r.message); await loadDetail(emp); await refresh(true);
    } else if (kind === 'rules') {
      const r = await api(`/api/employee/${emp}/rules`, { text: fd.get('text') || '' });
      toast(r.message); delete S.vals['rules:' + emp]; await loadDetail(emp); render(true);
    } else if (kind === 'hire') {
      const sel = S.roles.roles.find((x) => x.id === S.hireRole) || {};
      const body = { kind: 'hire', name: fd.get('name'), role: fd.get('role'), scope: fd.get('scope'), supervisor: fd.get('supervisor'), model: fd.get('model') };
      const preset = fd.get('preset');
      if (preset === 'role' && sel.abilities) body.abilities = sel.abilities; else body.preset = preset;
      const r = await api('/api/order', body);
      toast(r.message);
      const id = (r.message.match(/\/([a-z0-9-]+)$/) || [])[1];
      delete S.vals.hire; S.hireRole = null;
      S.data = await api('/api/state');
      go(id ? `/e/${id}?say=${encodeURIComponent(sel.first || '')}` : '/team');
    } else if (kind === 'settings') {
      const body = { team_name: fd.get('team_name'), about: fd.get('about'), workdays: fd.getAll('workdays'), network_domains: fd.get('network_domains'), jobs: {}, apify: {} };
      for (const k of Object.keys(JOB_LABELS)) body.jobs[k] = fd.get('jobs.' + k);
      body.apify.monthly_budget_usd = fd.get('apify.monthly_budget_usd'); body.apify.max_run_usd = fd.get('apify.max_run_usd');
      const r = await api('/api/settings', body);
      toast(r.message); delete S.vals.settings; S.settings = await api('/api/settings'); await refresh(true);
    }
  } catch (e) { toast(e.message, 'err'); }
  finally { if (btn) btn.disabled = false; }
});

// ---------------------------------------------------------------- polling
setInterval(async () => {
  if (document.hidden) return;
  try {
    S.data = await api('/api/state');
    const r = route();
    if (r.page === 'employee' && Date.now() - S.detailAt > 6000) await loadDetail(r.id);
    render(false);
  } catch (e) { /* keep the last view; the next poll retries */ }
}, 8000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(false).catch(() => {}); });

render(true);
