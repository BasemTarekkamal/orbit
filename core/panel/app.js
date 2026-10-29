/* Staffroom control panel. Plain JavaScript, no build step: it reads the JSON API in core/panel.py and
   renders each page as HTML. Polls every 8 seconds, every 2 while someone is working so you can watch
   them; never re-renders a form you're typing in, but keeps the live work view moving. */
'use strict';

// ---------------------------------------------------------------- utils
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const main = $('#main');
const side = $('#side');
const JOB_LABELS = { brief: 'Morning brief', standup: 'Standup', eod: 'End of day', scout: 'Self-improvement', evals: 'Weekly self-test' };
const RUN_LABELS = { ...JOB_LABELS, chat: 'Chat', first_day: 'First day', minutes: 'Meeting minutes', followup: 'Follow-up', bus: 'A colleague’s question' };
const MODELS = ['opus', 'sonnet', 'haiku'];
const NOTES = [['STATE.md', 'State'], ['TASKS.md', 'Tasks'], ['GOALS.md', 'Goals'], ['LESSONS.md', 'Lessons'], ['CLAUDE.md', 'Instructions']];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const CH = { telegram: 'Telegram', slack: 'Slack', discord: 'Discord' };
const CANT = ['Spend money or buy anything', 'Post, email or message anyone but you', 'Log in to accounts', 'See your passwords or private folders'];
const ACCESS = [
  ['web', 'Web search and reading', ['web', 'fetch']],
  ['social', 'TikTok, Instagram, Facebook, X, Reddit, YouTube, Maps', ['apify']],
  ['browser', 'Headless browser for hard pages', ['browser']],
  ['docs', 'Documents, scans and photos you send', ['documents', 'files']],
  ['watch', 'Watchers on pages and feeds', ['watchers']],
  ['calls', 'Call recordings and voice notes', ['meetings', 'voice']],
  ['remind', 'Reminders and follow-ups', ['reminders']],
  ['learn', 'Learns the skills you teach', ['learn']],
  ['tools', 'Builds its own small tools', ['build_tools']],
  ['brief', 'A brief every workday morning', ['brief']],
];
const COMING = ['Your own browser, acting as you', 'Email inbox', 'Google Docs and Notion', 'GitHub (private)', 'Live calls'];
const ALWAYS = ['telegram', 'team_room'];
const SLACK_MANIFEST = `display_information:
  name: Staffroom
  description: My AI team
features:
  app_home:
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: Staffroom
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - channels:history
      - channels:read
      - chat:write
      - files:read
      - files:write
      - groups:history
      - im:history
      - im:read
      - im:write
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.channels
      - message.groups
      - message.im
  interactivity:
    is_enabled: false
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false`;

const svg = (body, w = 1.8) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const I = {
  home: svg('<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/>'),
  users: svg('<circle cx="9" cy="8" r="3.5"/><path d="M3 20c.5-4 3-6 6-6s5.5 2 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.5c2.5.2 4 2 4.5 5.5"/>'),
  grid: svg('<path d="M4 7h16M4 12h16M4 17h16"/><circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none"/><circle cx="7" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="7" cy="17" r="1.2" fill="currentColor" stroke="none"/>'),
  sliders: svg('<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 2),
  chev: svg('<path d="m9 6 6 6-6 6"/>'),
  check: svg('<path d="m5 12.5 4.5 4.5L19 7.5"/>', 2.2),
  x: svg('<path d="M7 7l10 10M17 7 7 17"/>', 2),
  circle: svg('<circle cx="12" cy="12" r="7.5"/>'),
  alert: svg('<path d="M12 4 2.8 19.5h18.4L12 4Z"/><path d="M12 10v4M12 17h.01"/>'),
  clock: svg('<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.5"/>'),
  bell: svg('<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Z"/><path d="M10 20a2 2 0 0 0 4 0"/>'),
  pause: svg('<path d="M9 6v12M15 6v12"/>', 2),
  play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10-6.5z"/></svg>',
  user: svg('<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.6-4 3.4-6 7-6s6.4 2 7 6"/>'),
  gauge: svg('<path d="M4 16a8 8 0 1 1 16 0"/><path d="m12 16 4-5"/>'),
  file: svg('<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>'),
  send: svg('<path d="M4 12 20 4l-4 16-4-7z"/>', 1.9),
  list: svg('<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>', 2),
  phone: svg('<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="M11 18h2"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>'),
  manage: svg('<circle cx="12" cy="12" r="3"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>'),
};
const icon = (n) => I[n] || '';

function hue(id) { let h = 0; for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 8; }
function avatar(id, name, size = '') {
  const owner = !S.data || !S.data.employees.some((e) => e.id === id);
  return `<span class="avatar ${owner ? 'owner' : 'hue-' + hue(id)} ${size}" aria-hidden="true">${esc(String(name || id || '?').trim().charAt(0).toUpperCase())}</span>`;
}
function parseTs(ts) { if (!ts) return null; const d = new Date(String(ts).trim().replace(' ', 'T')); return isNaN(d) ? null : d; }
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
function mmss(s) { s = Math.max(0, Math.round(Number(s) || 0)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
function dur(s) { s = Math.round(Number(s) || 0); return s < 60 ? s + ' s' : Math.floor(s / 60) + ' min' + (s % 60 ? ' ' + (s % 60) + ' s' : ''); }
function sortedByTs(rows) { return rows.slice().sort((a, b) => String(a.ts).localeCompare(String(b.ts))); }
function linkify(s) {
  return s.replace(/https?:\/\/[^\s<]+/g, (u) => { const m = u.match(/^(.*?)([).,;:!?]*)$/); return `<a class="link" href="${m[1]}" target="_blank" rel="noopener noreferrer">${m[1]}</a>${m[2]}`; });
}
function store(get) { try { return get(); } catch (e) { return null; } }

// ---------------------------------------------------------------- state & api
const S = { data: null, detail: null, detailId: null, detailAt: 0, cat: null, roles: null, settings: null, file: null, fileLoading: '',
  skill: null, skillLoading: '', pair: null, job: null, situation: null, theme: store(() => localStorage.getItem('theme')) || '', lastHtml: '', vals: {},
  open: new Set(), busy: new Set() };

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
  store(() => (t ? localStorage.setItem('theme', t) : localStorage.removeItem('theme')));
  if (t) document.documentElement.setAttribute('data-theme', t); else document.documentElement.removeAttribute('data-theme');
}
setTheme(S.theme);

// ---------------------------------------------------------------- routing
function route() {
  const p = location.pathname.replace(/\/+$/, '') || '/';
  const q = new URLSearchParams(location.search);
  if (p === '/') return { page: 'today' };
  if (p === '/welcome') return { page: 'welcome' };
  if (p === '/connect') return { page: 'connect', ch: q.get('ch') || '' };
  if (p === '/team') return { page: 'team' };
  if (p === '/hire') return { page: 'hire', role: q.get('role') };
  if (p === '/abilities') return { page: 'abilities' };
  if (p === '/settings') return { page: 'settings' };
  const m = p.match(/^\/e\/([a-z0-9-]+)(?:\/([a-z]+))?$/);
  if (m) {
    const alias = { memory: 'knowledge', skills: 'knowledge', activity: 'work', abilities: 'manage' };   // older links
    const tab = alias[m[2]] || m[2] || 'work';
    if (!['chat', 'knowledge', 'work', 'manage'].includes(tab)) return { page: 'missing' };
    let f = q.get('f') || '';
    if (m[2] === 'memory' && f && !f.includes(':')) f = 'note:' + f;
    return { page: 'employee', id: m[1], tab, f, v: m[2] === 'activity' ? 'activity' : q.get('v') || '' };
  }
  return { page: 'missing' };
}
function go(path, replace) { if (replace) history.replaceState(null, '', path); else history.pushState(null, '', path); render(true); }
window.addEventListener('popstate', () => render(true));

// ---------------------------------------------------------------- render
async function render(nav) {
  let r = route();
  if (!S.data) {
    try { S.data = await api('/api/state'); }
    catch (e) { main.innerHTML = `<div class="empty"><b>Can't reach the panel.</b><p>${esc(e.message)}</p></div>`; return; }
  }
  const setup = S.data.setup || {};
  if (setup.welcome && !['welcome', 'connect', 'settings'].includes(r.page)) { history.replaceState(null, '', '/welcome'); r = route(); nav = true; }
  else if (r.page === 'welcome' && !setup.welcome) { history.replaceState(null, '', '/'); r = route(); nav = true; }
  try {
    if (r.page === 'employee' && (S.detailId !== r.id || !S.detail || nav)) await loadDetail(r.id);
    if ((r.page === 'abilities' || (r.page === 'employee' && r.tab === 'manage')) && !S.cat) S.cat = await api('/api/abilities');
    if ((r.page === 'hire' || r.page === 'welcome') && !S.roles) S.roles = await api('/api/roles');
    if (r.page === 'settings' && (nav || !S.settings)) S.settings = await api('/api/settings');
  } catch (e) { toast(e.message, 'err'); }
  document.body.classList.toggle('solo', r.page === 'welcome');
  renderSide(r);
  const active = document.activeElement;
  const inMain = !!active && main.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName);
  if (inMain && !nav && (active.value || active.tagName === 'SELECT' || active.type === 'checkbox')) { patchLive(); return; }
  const focusId = inMain ? active.id : '';
  const chat = r.page === 'employee' && r.tab === 'chat';
  const cm = chat && $('.chat-main', main);
  const following = !!cm && cm.getBoundingClientRect().bottom <= window.innerHeight + 60;   // you're at the latest message
  const html = (PAGES[r.page] || PAGES.missing)(r);
  if (nav || html !== S.lastHtml) {
    const y = window.scrollY;
    main.innerHTML = html;
    S.lastHtml = html;
    afterRender(r, nav);
    if (chat && (nav || following)) followChat(); else window.scrollTo(0, nav ? 0 : y);
    if (focusId) { const el = document.getElementById(focusId); if (el) el.focus({ preventScroll: true }); }
  }
  ticks();
  document.title = titleFor(r);
}
function titleFor(r) {
  const t = S.data.team_name;
  if (r.page === 'employee') { const e = S.data.employees.find((x) => x.id === r.id); return (e ? e.name : 'Employee') + ' · ' + t; }
  return ({ today: 'Today', team: 'Team', hire: 'Hire', abilities: 'Abilities', settings: 'Settings', welcome: 'Welcome', connect: 'Your phone' }[r.page] || 'Staffroom') + ' · ' + t;
}
function followChat() {          // the end of the conversation (latest message, live work, the box) at the bottom of the window
  const cm = $('.chat-main', main);
  if (!cm) return;
  const bottom = cm.getBoundingClientRect().bottom + window.scrollY;
  window.scrollTo(0, Math.max(0, bottom - window.innerHeight + 12));
}
function patchLive() {           // while you type: only the live work view and timers move
  document.querySelectorAll('[data-live-slot]').forEach((el) => { const h = liveCard(el.dataset.liveSlot); if (el.innerHTML !== h) el.innerHTML = h; });
  ticks();
}
function ticks() {
  const now = Date.now();
  document.querySelectorAll('[data-since]').forEach((el) => { const d = parseTs(el.dataset.since); if (d) el.textContent = mmss((now - d.getTime()) / 1000); });
}
setInterval(ticks, 1000);

function renderSide(r) {
  const d = S.data;
  const on = (p) => (r.page === p ? 'on' : '');
  const emps = d.employees.map((e) => {
    const live = (d.live || {})[e.id];
    const st = e.status === 'paused' ? 'paused' : live || e.doing ? 'working' : 'active';
    return `<a class="emp ${r.page === 'employee' && r.id === e.id ? 'on' : ''}" href="/e/${e.id}"><i class="dot ${st}"></i><span>${esc(e.name)}</span><small>${live || e.doing ? 'working' : e.status === 'paused' ? 'paused' : ''}</small></a>`;
  }).join('');
  const u = d.usage || {};
  const meters = ['five_hour', 'seven_day'].filter((k) => k in u).map((k) => {
    const pct = Math.max(0, Math.min(100, u[k]));
    return `<div class="row"><span>${k === 'five_hour' ? '5-hour limit' : 'Weekly limit'}</span><span class="num">${Math.round(pct)}%</span></div><div class="meter ${pct >= 80 ? 'hot' : ''}"><i data-w="${pct}"></i></div>`;
  }).join('');
  const today = d.employees.reduce((a, e) => a + e.use_today, 0);
  side.innerHTML = `
    <div class="brand"><img src="/icon.svg" alt=""><div><b>${esc(d.team_name)}${d.demo ? ' <span class="badge accent">demo</span>' : ''}</b><span class="meta"><i class="dot ${d.online ? 'active' : 'off'}"></i>${d.online ? 'Running' : 'Service stopped'}</span></div></div>
    <nav class="nav">
      <a href="/" class="${on('today')}">${icon('home')}Today</a>
      <a href="/team" class="${on('team') || on('abilities')}">${icon('users')}Team</a>
      <a href="/settings" class="${on('settings') || on('connect')}">${icon('sliders')}Settings</a>
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
  if (r.page === 'employee' && r.tab === 'work' && r.v === 'files' && r.f) ensureFile(r.id, r.f);
  if (r.page === 'employee' && r.tab === 'knowledge' && /^(own|team|kit):/.test(r.f)) { const i = r.f.indexOf(':'); ensureSkill(r.id, r.f.slice(0, i), r.f.slice(i + 1)); }
  if (nav && r.page === 'welcome') { const f = $('#w-name'); if (f) f.focus(); }
}
function grow(ta) { ta.style.height = 'auto'; ta.style.height = Math.min(240, ta.scrollHeight + 2) + 'px'; }
function v(form, name, dflt) { const f = S.vals[form]; return f && name in f ? f[name] : dflt; }
const loading = `<p class="quiet">Loading…</p>`;

// ---------------------------------------------------------------- shared pieces
function liveCard(id) {
  const L = (S.data.live || {})[id];
  if (!L) return '';
  const e = S.data.employees.find((x) => x.id === id);
  const steps = L.steps || [];
  const earlier = (L.count || steps.length) - steps.length;
  const items = steps.length ? steps.map((s, i) => `<li class="${i === steps.length - 1 ? 'now' : ''}"><span>${esc(s.text)}</span></li>`).join('') : '<li class="now"><span>Getting started…</span></li>';
  return `<div class="live"><div class="live-head"><i class="dot working"></i><b>${esc(e ? e.name : id)} is working</b><span class="meta">${esc(L.doing || '')} · <span class="num" data-since="${esc(L.started)}"></span></span></div>
    ${earlier > 0 ? `<p class="meta earlier">${plural(earlier, 'earlier step')}</p>` : ''}<ol class="steps">${items}</ol></div>`;
}
function lastStep(id) { const L = (S.data.live || {})[id]; if (!L) return ''; const s = L.steps || []; return s.length ? s[s.length - 1].text : 'Getting started…'; }
function receiptHtml(rc, key) {
  const steps = (rc && rc.steps) || [];
  if (!steps.length) return '';
  return `<details class="receipt" data-key="${esc(key)}" ${S.open.has(key) ? 'open' : ''}><summary>${icon('list')}How I did it · ${plural(steps.length, 'step')}${rc.secs ? ' · ' + dur(rc.secs) : ''}</summary>
    <ol class="steps done">${steps.map((s) => `<li><span>${esc(s.text)}</span><span class="t num">${mmss(s.t)}</span></li>`).join('')}</ol></details>`;
}
function bodyHtml(text, empId) {
  if (!empId) return linkify(esc(String(text || '')));          // people's own words, as typed
  // An employee's answer: their formatting rendered, and lines starting with → as suggestions to click.
  const out = []; let buf = [], chips = [];
  const flushText = () => { if (buf.length) { out.push(md(buf.join('\n'))); buf = []; } };
  const flushChips = () => { if (chips.length) { out.push(`<div class="chips try-row">${chips.join('')}</div>`); chips = []; } };
  for (const line of String(text || '').split('\n')) {
    const m = line.match(/^\s*(?:→|->)\s*(.+)$/);
    if (m) { flushText(); const t = m[1].trim(); chips.push(`<button type="button" class="chip try" data-act="try" data-emp="${esc(empId)}" data-text="${esc(t)}">${esc(t)}</button>`); continue; }
    flushChips();
    buf.push(line);
  }
  flushText(); flushChips();
  return out.join('');
}
function statusHtml(e) {
  if (!S.data.online) return `<span class="status"><i class="dot off"></i>Offline</span>`;
  if (e.status === 'paused') return `<span class="status"><i class="dot paused"></i>Paused</span>`;
  if ((S.data.live || {})[e.id] || e.doing) return `<span class="status"><i class="dot working"></i>Working</span>`;
  return `<span class="status"><i class="dot active"></i>Idle</span>`;
}
function empNow(e) {
  if (e.status === 'paused') return 'Paused';
  if ((S.data.live || {})[e.id]) return lastStep(e.id);
  if (e.next_job) return `Next: ${e.next_job} · ${fmtTime(e.next_job_at)}`;
  return e.last_run ? `Last run ${fmtTime(e.last_run)}` : 'Hasn’t run yet';
}
function nameOf(id) { if (id === 'team') return 'Team'; const e = S.data.employees.find((x) => x.id === id); return e ? e.name : id; }
function channelBadge(c) { return c && c !== 'bus' ? `<span class="badge">${{ panel: 'Panel', telegram: 'Telegram', slack: 'Slack', discord: 'Discord', group: 'Team chat', job: 'Routine', skill: 'Skill', hq: 'Panel' }[c] || esc(c)}</span>` : ''; }
function withDays(rows, fn, skipToday) {
  let last = '', out = '';
  for (const r of rows) {
    const t = parseTs(r.ts); const l = t ? dayLabel(t) : '';
    if (l !== last) { if (!(skipToday && l === 'Today' && !last)) out += `<div class="day-sep">${esc(l)}</div>`; last = l; }
    out += fn(r);
  }
  return out;
}

// ---------------------------------------------------------------- pages
const PAGES = {};
PAGES.missing = () => `<div class="empty"><b>No such page.</b><p><a class="link" href="/">Back to Today</a></p></div>`;

// ---- welcome: the first minutes, before there's a team
PAGES.welcome = () => {
  const st = S.data.setup || {};
  const step = st.owner ? 2 : 1;
  const steps = `<ol class="w-steps"><li class="${step > 1 ? 'done' : 'on'}">You</li><li class="${step === 2 ? 'on' : ''}">Their job</li><li>Your phone</li></ol>`;
  const brand = `<div class="w-brand"><img src="/icon.svg" alt=""><span>Staffroom</span></div>`;
  if (step === 1) {
    return `<div class="welcome">${brand}<h1>Build your first AI employee.</h1>
      <p class="lede">Your AI team. Your work, handled. On the Claude plan you already have, on this Mac.</p>${steps}
      <form class="form w-card" data-form="welcome">
        <div class="field"><label for="w-name">Your first name</label><input id="w-name" class="input lg" name="name" required maxlength="40" autocomplete="given-name" placeholder="Alex" value="${esc(v('welcome', 'name', ''))}"></div>
        <div class="field"><label for="w-team">Your business or your work</label><input id="w-team" class="input lg" name="team_name" maxlength="60" placeholder="Northwind Coffee" value="${esc(v('welcome', 'team_name', ''))}"></div>
        <div class="field"><label for="w-about">What you do, for whom, and what matters right now</label><textarea id="w-about" class="textarea" name="about" rows="4" maxlength="6000" placeholder="I'm a product designer at a fintech. I review designs against PRDs all day and I'm behind on three threads.">${esc(v('welcome', 'about', ''))}</textarea>
          <span class="hint">Every employee reads this first. Any language.</span></div>
        <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit">Continue</button></div>
      </form></div>`;
  }
  if (!S.roles) return loading;
  const sit = situationOf();
  const h1 = sit ? 'What should they take off your plate?' : 'What do you do?';
  return `<div class="welcome wide">${brand}<h1>${h1}</h1>${steps}${jobPicker('welcome')}</div>`;
};

function situationOf() { return (S.roles.situations || []).find((x) => x.id === S.situation) || null; }
function jobPicker(from) {
  const roles = S.roles.roles, sits = S.roles.situations || [];
  const sit = situationOf();
  if (!sit) {
    return `<div class="jobs sits">${sits.map((x) => `<button type="button" class="job" data-act="situation" data-id="${x.id}"><b>${esc(x.title)}</b><span>${esc(x.blurb)}</span></button>`).join('')}</div>`;
  }
  const order = sit.jobs.map((id) => roles.find((r) => r.id === id)).filter(Boolean);
  const cards = order.map((x) => `<button type="button" class="job ${S.job === x.id ? 'on' : ''}" data-act="job" data-role="${x.id}" aria-pressed="${S.job === x.id}"><b>${esc(x.title)}</b><span>${esc(x.role || 'Your own job')}</span></button>`).join('');
  const back = `<p class="meta sit-line">${esc(sit.title)} · <a class="link" href="#" data-act="situation" data-id="">change</a>${sit.id === 'other' ? '' : ` · <a class="link" href="#" data-act="situation" data-id="other">all jobs</a>`}</p>`;
  const sel = roles.find((x) => x.id === S.job);
  if (!sel) return back + `<div class="jobs">${cards}</div>`;
  const custom = sel.id === 'blank';
  const name = v('hire', 'name', sel.names[0] || '');
  const on = new Set(v('hire', 'access', null) || ACCESS.filter(([, , ids]) => !sel.abilities || ids.some((a) => sel.abilities.includes(a))).map(([k]) => k));
  const access = `<div class="field"><span class="lbl">What they get access to</span><div class="chips">${ACCESS.map(([k, l]) => `<label class="chip ${on.has(k) ? 'on' : ''}"><input class="sr" type="checkbox" name="access" value="${k}" ${on.has(k) ? 'checked' : ''}>${esc(l)}</label>`).join('')}</div>
    <span class="hint">Always: memory, the safety guard, your chat. Coming: ${COMING.join(' · ')}. Until then they prepare and you send.</span></div>`;
  const status = sel.today ? `<p class="small status-line">${esc(sel.today)}${sel.soon ? ` <span class="faint">Soon: ${esc(sel.soon)}</span>` : ''}</p>` : '';
  const model = v('hire', 'model', sel.model || 'sonnet');
  const form = `<form class="w-card hire-bar" data-form="hire" data-from="${from}">
      <div class="form-row"><div class="field"><label for="h-name">Their name</label><input id="h-name" class="input lg" name="name" required maxlength="60" value="${esc(name)}" placeholder="Sara">
        ${sel.names.length ? `<div class="chips">${sel.names.map((n) => `<button type="button" class="chip ${name === n ? 'on' : ''}" data-act="name" data-name="${esc(n)}">${esc(n)}</button>`).join('')}</div>` : ''}</div>
      ${custom ? `<div class="field"><label for="h-role">Job title</label><input id="h-role" class="input lg" name="role" required maxlength="120" value="${esc(v('hire', 'role', ''))}" placeholder="Bookkeeper"></div>` : ''}</div>
      ${custom ? `<div class="field"><label for="h-scope">The job, in your own words</label><textarea id="h-scope" class="textarea" name="scope" rows="3" required maxlength="2000" placeholder="Keep my books from the bank statements I send each month: sort every line, flag anything odd, send me a one-page summary.">${esc(v('hire', 'scope', ''))}</textarea></div>` : status}
      ${access}
      <details class="adv"><summary>Job title, scope and model</summary><div class="form mt">
        ${custom ? '' : `<div class="field"><label for="h-role">Job title</label><input id="h-role" class="input" name="role" maxlength="120" value="${esc(v('hire', 'role', sel.role))}"></div>
        <div class="field"><label for="h-scope">What they own</label><textarea id="h-scope" class="textarea" name="scope" rows="3" maxlength="2000">${esc(v('hire', 'scope', sel.scope))}</textarea></div>`}
        <div class="field"><label for="h-model">Model</label><select id="h-model" class="select auto" name="model">${MODELS.map((m) => `<option value="${m}" ${m === model ? 'selected' : ''}>${m}${m === 'sonnet' ? ' (balanced)' : m === 'haiku' ? ' (lightest on your plan)' : ' (strongest, heaviest)'}</option>`).join('')}</select></div>
      </div></details>
      <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit" data-hire-label>${icon('plus')}Hire ${esc(name || 'them')}</button><span class="meta">They start with a real first task, in about a minute.</span></div>
    </form>`;
  return back + `<div class="jobs">${cards}</div>${form}`;
}
function pickJob(id, rerender = true) {
  const x = S.roles.roles.find((y) => y.id === id); if (!x) return;
  S.job = id;
  S.vals.hire = { name: x.names[0] || '', role: x.role, scope: x.scope, model: x.model || 'sonnet', supervisor: v('hire', 'supervisor', S.data.me) };
  if (rerender) render(true).then(() => { const f = $('.hire-bar'); if (f) f.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); });
}

// ---- connect: put the team on your phone
PAGES.connect = (r) => {
  const ch = CH[r.ch] ? r.ch : (S.pair && S.pair.channel) || 'telegram';
  const on = (S.data.setup || {}).channels || [];
  const pick = `<div class="seg big" role="tablist" aria-label="Channel">${Object.entries(CH).map(([k, l]) => `<button data-act="ch" data-v="${k}" class="${ch === k ? 'on' : ''}" role="tab" aria-selected="${ch === k}">${l}${on.includes(k) ? ' ✓' : k === 'telegram' ? ' <span class="faint">quickest</span>' : ''}</button>`).join('')}</div>`;
  const P = S.pair && S.pair.channel === ch ? S.pair : null;
  let body;
  if (P && P.paired) body = pairedView(P);
  else if (P && P.code) body = pairView(P);
  else if (on.includes(ch)) body = connectedView(ch);
  else body = howTo(ch);
  return `<div class="connect"><header class="page-head"><div><h1>Your team on your phone</h1><p class="sub">Talk to them from Telegram, Slack or Discord through a bot that's yours, voice notes included. Only you, and people you approve, can use it.</p></div></header>
    ${pick}<div class="mt-lg">${body}</div></div>`;
};
function tokenForm(kind, fields) {
  return `<form class="connect-form" data-form="connect" data-kind="${kind}">${fields.map(([name, ph, label]) => `<div class="field"><label for="c-${kind}-${name}">${label}</label><input id="c-${kind}-${name}" class="input lg mono" name="${name}" required autocomplete="off" spellcheck="false" placeholder="${ph}"></div>`).join('')}
    <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit">Connect</button><span class="meta">The token stays on this Mac, in your team's private folder. It never goes through a chat.</span></div></form>`;
}
function howTo(ch) {
  if (ch === 'telegram') {
    return `<ol class="howto">
      <li><div><b>Open Telegram and find @BotFather</b><p class="muted">Telegram's official bot maker, with a blue check. <a class="link" href="https://t.me/BotFather" target="_blank" rel="noopener">Open it</a></p></div></li>
      <li><div><b>Send /newbot</b><p class="muted">Pick any name (“${esc(S.data.team_name)} Team”), then a username that ends in “bot”.</p></div></li>
      <li><div><b>Paste the token it sends you</b><p class="muted">A long line that looks like 123456789:AAH…</p>${tokenForm('telegram', [['token', '123456789:AA…', 'Bot token']])}</div></li></ol>`;
  }
  if (ch === 'slack') {
    return `<ol class="howto">
      <li><div><b>Create the app from this manifest</b><p class="muted">Go to <a class="link" href="https://api.slack.com/apps" target="_blank" rel="noopener">api.slack.com/apps</a> → Create New App → From a manifest → pick your workspace → paste this → Create.</p>
        <div class="copybox"><pre class="raw" id="slack-manifest">${esc(SLACK_MANIFEST)}</pre><button type="button" class="btn btn-sm" data-act="copy" data-from="#slack-manifest">${icon('copy')}Copy</button></div></div></li>
      <li><div><b>Install it, then copy two tokens</b><p class="muted">Install to Workspace, then copy the <b>Bot User OAuth Token</b> (xoxb-…). Under Basic Information → App-Level Tokens, generate one with the scope <code>connections:write</code> (xapp-…).</p>
        ${tokenForm('slack', [['token', 'xoxb-…', 'Bot User OAuth Token'], ['app_token', 'xapp-…', 'App-Level Token']])}</div></li></ol>`;
  }
  return `<ol class="howto">
    <li><div><b>Create the bot</b><p class="muted"><a class="link" href="https://discord.com/developers/applications" target="_blank" rel="noopener">discord.com/developers</a> → New Application → Bot → Reset Token, and copy it. On the same page, turn on <b>Message Content Intent</b>.</p></div></li>
    <li><div><b>Add it to your server</b><p class="muted">OAuth2 → URL Generator: tick “bot”, then View Channels, Send Messages, Read Message History and Attach Files. Open the link it makes and pick your server.</p></div></li>
    <li><div><b>Paste the token</b>${tokenForm('discord', [['token', 'MTIz…', 'Bot token']])}</div></li></ol>`;
}
function pairView(P) {
  const how = P.channel === 'telegram' ? '' : `<p class="muted">${P.channel === 'slack' ? 'In Slack, open your app under Apps (the Messages tab) and send it this code:' : 'Message your bot (find it in your server’s member list) and send it this code:'}</p>`;
  return `<div class="w-card pair"><p><b>${CH[P.channel]} connected${P.bot ? ' as ' + esc(P.bot) : ''}.</b> One last step, so the bot knows it's you.</p>
    ${P.link ? `<div><a class="btn btn-primary btn-lg" href="${esc(P.link)}" target="_blank" rel="noopener">${icon('phone')}Open Telegram and press Start</a></div><p class="muted">Or send this code to ${esc(P.bot)}:</p>` : how}
    <div class="code num" aria-label="Pairing code">${esc(P.code.slice(0, 3) + ' ' + P.code.slice(3))}</div>
    <p class="waiting"><i class="dot working"></i>Waiting for your message. The code works once, for 30 minutes.</p></div>`;
}
function pairedView(P) {
  const first = S.data.employees[0];
  return `<div class="w-card pair ok"><p class="big">${icon('check')}You're connected, ${esc(P.who || S.data.me)}.</p>
    <p class="muted">Message your team from ${CH[P.channel]}: just type, or send a voice note${first ? `, and ${esc(first.name)} answers there` : ''}.</p>
    <div class="save-bar"><a class="btn btn-primary" href="${first ? '/e/' + first.id : '/'}">${first ? 'Back to ' + esc(first.name) : 'Go to Today'}</a></div></div>`;
}
function connectedView(ch) {
  return `<div class="w-card pair"><p><b>${CH[ch]} is connected.</b> ${(S.data.setup || {}).paired ? 'Your team answers you there.' : 'Pair your phone so the bot knows it’s you.'}</p>
    <div class="save-bar"><button class="btn ${(S.data.setup || {}).paired ? '' : 'btn-primary'}" data-act="pair" data-v="${ch}">${icon('phone')}${(S.data.setup || {}).paired ? 'Pair another device' : 'Pair my phone'}</button></div>
    <details class="adv"><summary>Use a different bot</summary><div class="mt">${howTo(ch)}</div></details></div>`;
}

// ---- today
PAGES.today = () => {
  const d = S.data, emps = d.employees, h = new Date().getHours();
  const greet = h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const live = Object.keys(d.live || {}).map((id) => emps.find((e) => e.id === id)).filter(Boolean);
  const date = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  let sub = date;
  if (!emps.length) sub += ' · no employees yet';
  else sub += ` · ${plural(emps.length, 'employee')} · ${live.length ? live.length + ' working' : 'all idle'}`;
  if (!d.online) sub += ' · <span class="badge danger">service stopped</span>';
  const demo = d.demo ? `<div class="demo-bar"><b>A pretend team, to look around.</b> The business, the people and their findings are invented (links end in .example) and the replies are canned: no Claude run, no bot. Chat with someone anyway, teach a skill, change abilities. Your own team: paste the one line from the README into the Claude app, or run <code>install.sh</code>.</div>` : '';
  const todo = d.checklist.filter((c) => !c.done && !c.optional);
  const setup = todo.length ? `<div class="setup"><h2>Finish setting up</h2><ol>${d.checklist.filter((c) => !c.done).map((c) => `
    <li>${icon('circle')}<div><span>${esc(c.title)}${c.optional ? ' <span class="meta">optional</span>' : ''}</span><div class="how">${esc(c.how)}</div></div>${c.href ? `<a class="btn btn-sm ${c.optional ? '' : 'btn-primary'}" href="${esc(c.href)}">${esc(c.cta)}</a>` : '<span></span>'}</li>`).join('')}</ol></div>` : '';
  const nowSec = live.length ? `<section><div class="sec-head"><h2>Working now</h2></div><div class="list now-list">${live.map((e) => {
    const L = d.live[e.id];
    return `<a class="row" href="/e/${e.id}">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)} <span class="meta">${esc(L.doing || '')}</span></div><div class="now-step"><i class="dot working"></i>${esc(lastStep(e.id))}</div></div><span class="meta num" data-since="${esc(L.started)}"></span></a>`;
  }).join('')}</div></section>` : '';
  const kinds = { owner: 'user', failed: 'alert', paused: 'pause', waiting: 'clock', reminder: 'bell', usage: 'gauge' };
  const needs = d.needs.length ? `<div class="list needs">${d.needs.map((n) => `
    <a class="row ${n.kind}" href="${esc(n.href)}"><span class="k">${icon(kinds[n.kind] || 'alert')}</span><div><div class="title">${esc(n.title)}</div><div class="meta">${esc(n.detail)}</div></div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`).join('')}</div>`
    : `<p class="quiet">Nothing needs you right now.</p>`;
  const now = new Date();
  let feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && sameDay(t, now); });
  if (feed.length < 4) { const y = new Date(now); y.setDate(now.getDate() - 1); feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && (sameDay(t, now) || sameDay(t, y)); }); }
  const timeline = feed.length ? `<div class="timeline">${withDays(feed.slice(-40), tlItem, true)}</div>`
    : `<div class="empty"><b>Quiet so far.</b><p>${emps.length ? 'What your team says to you and to each other shows up here.' : 'Hire your first employee and their work shows up here.'}</p></div>`;
  const mini = emps.length ? `<div class="list mini">${emps.map((e) => `<a class="row" href="/e/${e.id}">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)}</div><div class="meta">${esc(empNow(e))}</div></div>${statusHtml(e)}</a>`).join('')}</div>`
    : `<p class="quiet">No employees yet. <a class="link" href="/hire">Hire someone</a>.</p>`;
  const useToday = emps.reduce((a, e) => a + e.use_today, 0), use7 = emps.reduce((a, e) => a + e.use_7d, 0);
  const u = d.usage || {};
  const usage = `<div class="usage-box"><div class="row2"><span>Today</span><b class="num">≈${money(useToday)}</b></div><div class="row2"><span>Last 7 days</span><b class="num">≈${money(use7)}</b></div>
    ${['five_hour', 'seven_day'].filter((k) => k in u).map((k) => `<div class="row2"><span>${k === 'five_hour' ? '5-hour limit' : 'Weekly limit'}</span><b class="num">${Math.round(u[k])}% used</b></div>`).join('')}
    <p class="meta">What the runs would cost on the API. Nothing extra is billed: they use your Claude plan's limits.</p></div>`;
  return `${demo}<header class="greet"><h1>${greet}, ${esc(d.me)}.</h1><p class="sub">${sub}</p></header>${setup}
    <div class="cols"><div>${nowSec}
      <section><div class="sec-head"><h2>Needs you</h2>${d.needs.length ? `<span class="meta">${d.needs.length}</span>` : ''}</div>${needs}</section>
      <section><div class="sec-head"><h2>Today</h2><span class="meta">the team room</span></div>${timeline}</section>
    </div><aside>
      <section><div class="sec-head"><h2>Team</h2><a class="link small" href="/team">All</a></div>${mini}</section>
      <section><div class="sec-head"><h2>Plan use</h2></div>${usage}</section>
    </aside></div>`;
};
function tlItem(f) {
  const long = (f.body || '').length > 600;
  const emp = S.data.employees.some((e) => e.id === f.from_id) ? f.from_id : '';
  return `<div class="tl">${avatar(f.from_id, f.from_name)}<div><div class="head"><b>${esc(f.from_name)}</b><span>→ ${esc(nameOf(f.to_id))}</span><span>·</span><span>${fmtTime(f.ts)}</span>${channelBadge(f.channel)}</div>
    <div class="body${emp ? ' md rich' : ''}${long ? ' clamp' : ''}">${bodyHtml(f.body, emp)}</div>${long ? `<button class="btn btn-ghost btn-sm more" data-act="more">Show more</button>` : ''}${emp ? receiptHtml(f.receipt, 'feed:' + f.id) : ''}</div></div>`;
}

// ---- team
PAGES.team = () => {
  const d = S.data, emps = d.employees;
  const working = emps.filter((e) => (d.live || {})[e.id] || e.doing).length;
  const rows = emps.map((e) => `<a class="row team-row" href="/e/${e.id}">
    <div class="who">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)}</div><div class="meta">${esc(e.role)} · reports to ${esc(e.supervisor)}</div></div></div>
    ${statusHtml(e)}<div class="c-next small muted">${esc(empNow(e))}</div>
    <div class="c-today small muted num">${e.runs_today ? `${plural(e.runs_today, 'run')} · ≈${money(e.use_today)}` : 'No runs today'}${e.failures_today ? ` · <span class="badge danger">${e.failures_today} failed</span>` : ''}</div>
    <div class="c-model small muted">${esc(e.model)}</div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`).join('');
  const ts = d.team_skills || [];
  const skills = emps.length ? `<section class="mt-lg"><div class="sec-head"><h2>Team skills</h2><span class="meta">${ts.length ? `${ts.length} shared · every employee uses them` : 'shared by employees, used by all'}</span></div>
    ${ts.length ? `<div class="list">${ts.map((s) => `<a class="row row-2" href="/e/${esc(s.shared_from || emps[0].id)}/knowledge?f=team:${esc(s.name)}"><div><div class="title">${esc(s.name)}</div><div class="meta">${esc(s.description)}</div></div><span class="meta">shared by ${esc(nameOf(s.shared_from || ''))}</span></a>`).join('')}</div>`
      : `<p class="quiet">None yet. When an employee learns something every colleague should know, they share it here (or you do, from their Knowledge tab).</p>`}</section>` : '';
  return `<header class="page-head"><div><h1>Team</h1><p class="sub">${emps.length ? `${plural(emps.length, 'employee')}${working ? ` · ${working} working` : ''}` : 'Nobody works here yet.'}</p></div>
    <div class="actions">${emps.length ? `<a class="btn" href="/abilities">${icon('grid')}Compare abilities</a>` : ''}<a class="btn btn-primary" href="/hire">${icon('plus')}Hire someone</a></div></header>
    ${emps.length ? `<div class="list">${rows}</div>` : `<div class="empty"><b>Your first employee is one click away.</b><p><a class="link" href="/hire">Pick what they should do</a>: they come with the whole toolbelt, a memory, and a morning brief.</p></div>`}${skills}`;
};

// ---- employee
PAGES.employee = (r) => {
  const e = S.data.employees.find((x) => x.id === r.id);
  if (!e) return `<div class="empty"><b>No employee called “${esc(r.id)}”.</b><p><a class="link" href="/team">Back to the team</a></p></div>`;
  const dt = S.detail && S.detailId === r.id ? S.detail : null;
  const nKnow = dt ? dt.skills.own.length + dt.skills.team.length : '';
  const tabs = [['work', 'Work', ''], ['chat', 'Chat', ''], ['knowledge', 'Knowledge', nKnow || ''], ['manage', 'Manage', '']];
  const body = { chat: tabChat, knowledge: tabKnowledge, work: tabWork, manage: tabManage }[r.tab](e, dt, r);
  return `<header class="emp-head">${avatar(e.id, e.name, 'lg')}<div class="id"><h1>${esc(e.name)}</h1><div class="sub"><span>${esc(e.role)}</span><span>·</span><span>reports to ${esc(e.supervisor)}</span><span>·</span>${statusHtml(e)}</div></div></header>
    <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="/e/${e.id}/${k}" class="${r.tab === k ? 'on' : ''}">${l}${n !== '' ? `<small>${esc(n)}</small>` : ''}</a>`).join('')}</nav>${body}`;
};

function tabChat(e, dt) {
  const rows = dt ? dt.chat : [];
  const live = (S.data.live || {})[e.id];
  const thread = rows.length ? `<div class="thread">${withDays(rows, (m) => msgHtml(m, e))}</div>`
    : live ? '' : `<div class="empty"><b>Say hello to ${esc(e.name)}.</b><p>Ask for anything in their scope, in any language, or pick a suggestion.</p></div>`;
  const tries = (dt && dt.try) || [];
  const setup = S.data.setup || {};
  const phone = setup.paired
    ? `<section><h3>On your phone</h3><p class="muted small"><code>/${esc(e.id)}</code> on Telegram, <code>@${esc(e.id)}</code> on Slack or Discord. Voice notes work.</p></section>`
    : `<section class="phone-cta"><h3>On your phone</h3><a class="btn btn-sm" href="/connect">${icon('phone')}Connect your phone</a></section>`;
  const rail = `<aside class="rail">
    <section><h3>Try asking</h3><div class="chips col">${tries.map((t) => `<button type="button" class="chip try" data-act="try" data-emp="${e.id}" data-text="${esc(t)}">${esc(t)}</button>`).join('')}
      <button type="button" class="chip try" data-act="try" data-emp="${e.id}" data-text="From now on, ">“From now on, …” teaches a skill</button></div></section>
    <section><h3>Never</h3><ul class="cant">${CANT.map((c) => `<li>${icon('x')}<span>${esc(c)}</span></li>`).join('')}</ul></section>
    ${phone}</aside>`;
  return `<div class="chat"><div class="chat-main">${thread}<div data-live-slot="${e.id}">${liveCard(e.id)}</div>
    <form class="composer" data-form="message" data-emp="${e.id}"><div class="box"><textarea id="composer-${e.id}" name="text" data-grow rows="1" placeholder="Message ${esc(e.name)}…" aria-label="Message" maxlength="4000">${esc(v('message:' + e.id, 'text', ''))}</textarea>
    <div class="bar"><span class="meta">Enter to send · Shift+Enter for a new line</span><button class="btn btn-primary btn-sm" type="submit">${icon('send')}Send</button></div></div></form></div>${rail}</div>`;
}
function msgHtml(m, e) {
  const owner = m.from_id !== e.id;
  const to = m.to_id && m.to_id !== e.id && m.to_id !== 'owner' ? `<span>→ ${esc(nameOf(m.to_id))}</span>` : '';
  const key = 'msg:' + (m.id || m.ts);
  return `<div class="msg ${owner ? 'owner' : ''}">${avatar(m.from_id, m.from_name, 'sm')}<div><div class="head"><b>${esc(m.from_name)}</b>${to}<span>${hm(parseTs(m.ts) || new Date())}</span>${channelBadge(m.channel)}</div>
    <div class="body${owner ? '' : ' md rich'}">${bodyHtml(m.body, owner ? '' : e.id)}</div>${owner ? '' : receiptHtml(m.receipt, key)}</div></div>`;
}

function tabKnowledge(e, dt, r) {
  if (!dt) return loading;
  const sel = r.f || 'note:STATE.md';
  const sk = dt.skills;
  const link = (key, label, extra = '') => `<a href="/e/${e.id}/knowledge?f=${encodeURIComponent(key)}" class="${sel === key ? 'on' : ''}">${icon('file')}<span>${esc(label)}${extra}</span></a>`;
  const group = (title, rows, where) => rows.length ? `<h3>${title}</h3>${rows.map((s) => link(where + ':' + s.name, s.name, s.problem ? '<i class="dot paused" title="not loading"></i>' : '')).join('')}` : '';
  const list = `<h3>Notes they keep</h3>${NOTES.map(([f, l]) => link('note:' + f, l)).join('')}${group('Skills they learned', sk.own, 'own')}${group('Team skills', sk.team, 'team')}${group('Playbooks for their abilities', sk.kit, 'kit')}`;
  let preview;
  if (sel === 'teach') preview = teachForm(e);
  else if (sel.startsWith('note:')) preview = notePreview(e, dt, sel.slice(5));
  else preview = skillPreview(e, sel);
  return `<div class="ab-bar"><a class="btn btn-primary" href="/e/${e.id}/knowledge?f=teach">${icon('plus')}Teach a skill</a><span class="meta">Notes they keep, skills they learned or were taught, and playbooks for their abilities. All loaded on every run.</span></div>
    <div class="work"><div class="files">${list}</div><div class="preview">${preview}</div></div>`;
}
function notePreview(e, dt, f) {
  const text = dt.memory[f] || '';
  let extra = '';
  if (f === 'CLAUDE.md') {
    const i = text.indexOf('## Role-specific rules');
    const rules = i >= 0 ? text.slice(i + '## Role-specific rules'.length).trim() : '';
    extra = `<hr><form class="form prose" data-form="rules" data-emp="${e.id}"><div class="field"><label for="rules">Rules you set</label><textarea id="rules" class="textarea" name="text" rows="6" placeholder="One rule per line. Example: Reply in Arabic. Always give three options. Never contact suppliers yourself.">${esc(v('rules:' + e.id, 'text', rules.startsWith('_') ? '' : rules))}</textarea><span class="hint">Saved into their instructions; they follow it on every run.</span></div><div class="save-bar"><button class="btn btn-primary" type="submit">Save rules</button></div></form>`;
  }
  return `<div class="md">${md(text) || '<p class="quiet">Empty so far. They fill it in as they work.</p>'}</div>${extra}`;
}
function skillWho(d, where) {
  if (where === 'kit') return 'kit playbook';
  if (d.how === 'panel' || d.how === 'taught') return 'taught by ' + esc(d.by || 'an owner');
  if (where === 'team') return 'shared by ' + esc(nameOf(d.shared_from || ''));
  return 'worked out on their own';
}
function skillPreview(e, sel) {
  const i = sel.indexOf(':'), where = sel.slice(0, i), name = sel.slice(i + 1);
  const key = e.id + ':' + where + ':' + name;
  if (!(S.skill && S.skill.key === key)) return `<p class="quiet">Loading ${esc(name)}…</p>`;
  const d = S.skill.data;
  if (d.error) return `<div class="empty"><b>Couldn't open it.</b><p>${esc(d.error)}</p></div>`;
  const meta = [skillWho(d, where), d.at ? fmtTime(d.at) : '', d.updated ? 'edited ' + fmtTime(d.updated) : ''].filter(Boolean).join(' · ');
  if (where === 'kit') return `<div class="path"><span>${esc(name)}</span><span>kit playbook · read-only</span></div><div class="md">${md(d.text)}</div>`;
  return `<form class="form" data-form="skill" data-emp="${e.id}" data-where="${where}" data-name="${esc(name)}">
    <div class="path"><span>${esc(name)}</span><span>${meta}</span></div>
    ${d.problem ? `<p class="err small">Not loading until fixed: ${esc(d.problem)}</p>` : ''}
    <div class="field"><textarea id="skill-text" class="textarea mono" name="text" rows="18" aria-label="Skill text">${esc(v('skill:' + key, 'text', d.text))}</textarea><span class="hint">When to use it, the steps, the checks before answering, an example. They use it whenever it applies.</span></div>
    <div class="save-bar"><button class="btn btn-primary" type="submit">Save</button>${where === 'own' ? `<button class="btn" type="button" data-act="skill" data-do="share" data-emp="${e.id}" data-where="own" data-name="${esc(name)}">Share with the team</button>` : ''}<button class="btn btn-ghost btn-danger" type="button" data-act="skill" data-do="remove" data-emp="${e.id}" data-where="${where}" data-name="${esc(name)}">${where === 'team' ? 'Remove from the team' : 'Remove'}</button></div></form>`;
}
function teachForm(e) {
  return `<form class="form" data-form="teach" data-emp="${e.id}">
    <div class="path"><span>Teach ${esc(e.name)} a skill</span></div>
    <p class="muted small">Or just tell them in chat: “From now on, when I ask for X, do Y.” They write the skill themselves.</p>
    <div class="form-row"><div class="field"><label for="sk-name">Name</label><input id="sk-name" class="input" name="name" required pattern="[a-z0-9][a-z0-9-]{1,63}" maxlength="64" placeholder="monday-competitor-digest" value="${esc(v('teach:' + e.id, 'name', ''))}"><span class="hint">Lowercase letters, digits, dashes.</span></div>
    <div class="field"><label for="sk-desc">What it's for and when to use it</label><input id="sk-desc" class="input" name="description" required minlength="12" maxlength="1024" placeholder="How I want the Monday digest. Use when I ask for the digest." value="${esc(v('teach:' + e.id, 'description', ''))}"></div></div>
    <div class="field"><label for="sk-text">How to do it</label><textarea id="sk-text" class="textarea" name="text" rows="12" required placeholder="When to use it&#10;…&#10;&#10;Steps&#10;1. …&#10;2. …&#10;&#10;Checks before answering&#10;- …">${esc(v('teach:' + e.id, 'text', ''))}</textarea><span class="hint">Plain words are fine. Never put a password or token in a skill.</span></div>
    <div class="save-bar"><button class="btn btn-primary" type="submit">Teach ${esc(e.name)}</button><span class="meta">They use it from their next run.</span></div></form>`;
}
async function ensureSkill(emp, where, name) {
  const key = emp + ':' + where + ':' + name;
  if ((S.skill && S.skill.key === key) || S.skillLoading === key) return;
  S.skillLoading = key;
  try { S.skill = { key, data: await api(`/api/skill?emp=${encodeURIComponent(emp)}&where=${encodeURIComponent(where)}&name=${encodeURIComponent(name)}`) }; }
  catch (e) { S.skill = { key, data: { error: e.message } }; }
  S.skillLoading = '';
  render(false);
}

function tabWork(e, dt, r) {
  if (!dt) return loading;
  const activity = r.v === 'activity', files = r.v === 'files';
  const subs = `<div class="subtabs"><a href="/e/${e.id}/work" class="${activity || files ? '' : 'on'}">Latest</a><a href="/e/${e.id}/work?v=files" class="${files ? 'on' : ''}">Files${dt.files.length ? ' · ' + dt.files.length : ''}</a><a href="/e/${e.id}/work?v=activity" class="${activity ? 'on' : ''}">Activity${dt.runs.length ? ' · ' + dt.runs.length : ''}</a></div>`;
  if (activity) return subs + runsHtml(dt);
  if (!files) {                                   // the latest results, newest first, with the live view on top
    const live = liveCard(e.id);
    const mine = dt.chat.filter((m) => m.from_id === e.id).slice(-5).reverse();
    const results = mine.length ? `<div class="results">${mine.map((m) => `<article class="result"><div class="head"><span>${fmtTime(m.ts)}</span>${m.to_id && m.to_id !== 'owner' && m.to_id !== e.id ? `<span>→ ${esc(nameOf(m.to_id))}</span>` : ''}${channelBadge(m.channel)}</div><div class="body md rich">${bodyHtml(m.body, e.id)}</div>${receiptHtml(m.receipt, 'res:' + (m.id || m.ts))}</article>`).join('')}</div>`
      : live ? '' : `<div class="empty"><b>Nothing yet.</b><p>${esc(e.name)}'s results show up here as they finish.</p></div>`;
    return subs + `<div class="chat"><div class="chat-main"><div data-live-slot="${e.id}">${live}</div>${results}
      <form class="composer" data-form="message" data-emp="${e.id}"><div class="box"><textarea id="composer-${e.id}" name="text" data-grow rows="1" placeholder="Tell ${esc(e.name)} something…" aria-label="Message" maxlength="4000">${esc(v('message:' + e.id, 'text', ''))}</textarea>
      <div class="bar"><span class="meta">Enter to send</span><button class="btn btn-primary btn-sm" type="submit">${icon('send')}Send</button></div></div></form></div>
      <aside class="rail"><section><h3>Try asking</h3><div class="chips col">${(dt.try || []).map((t) => `<button type="button" class="chip try" data-act="try" data-emp="${e.id}" data-text="${esc(t)}">${esc(t)}</button>`).join('')}</div></section></aside></div>`;
  }
  if (!dt.files.length) return subs + `<div class="empty"><b>No files yet.</b><p>Files ${esc(e.name)} writes (research notes, scrapes, tools, the growth log) appear here, readable in place.</p></div>`;
  const groups = {};
  for (const f of dt.files) { const g = f.path.split('/')[0]; (groups[g] ||= []).push(f); }
  const list = Object.entries(groups).map(([g, fs]) => `<h3>${esc(g)}</h3>${fs.slice(0, 60).map((f) => f.text
    ? `<a href="/e/${e.id}/work?v=files&f=${encodeURIComponent(f.path)}" class="${r.f === f.path ? 'on' : ''}" title="${esc(f.path)} · ${fmtTime(f.mtime)}">${icon('file')}<span>${esc(f.path.slice(g.length + 1))}</span></a>`
    : `<span class="faint small pad">${esc(f.path.slice(g.length + 1))}</span>`).join('')}`).join('');
  let preview = `<div class="empty"><p>Pick a file to read it here. Newest first.</p></div>`;
  if (r.f) {
    const key = e.id + ':' + r.f;
    if (S.file && S.file.key === key) {
      const t = S.file.data.text;
      preview = `<div class="path"><span>${esc(r.f)}</span><span>${S.file.data.truncated ? 'first 400 KB' : ''}</span></div>${/\.md$/i.test(r.f) ? `<div class="md">${md(t)}</div>` : `<pre class="raw">${esc(t)}</pre>`}`;
    } else preview = `<p class="quiet">Loading ${esc(r.f)}…</p>`;
  }
  return subs + `<div class="work"><div class="files">${list}</div><div class="preview">${preview}</div></div>`;
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
function runsHtml(dt) {
  if (!dt.runs.length) return `<div class="empty"><b>No runs yet.</b><p>Every chat, routine and colleague question is logged here, with how it was done, how long it took and its plan use.</p></div>`;
  const head = `<div class="run-head"><span>When</span><span>What</span><span>Model</span><span class="num">Time</span><span class="num">Plan use</span><span>Result</span></div>`;
  return `<div class="runs">${head}${dt.runs.map((x) => {
    const steps = x.steps || [];
    const cells = `<span class="num">${fmtTime(x.ts)}</span><span>${esc(RUN_LABELS[x.job] || x.job)}</span><span class="muted">${esc(x.model || '')}</span><span class="num">${dur(x.secs)}</span><span class="num">≈${money(x.cost_usd)}</span><span class="${x.ok ? 'muted' : 'err'}">${x.ok ? (steps.length ? plural(steps.length, 'step') : 'ok') : esc(x.error || 'failed')}</span>`;
    const key = 'run:' + x.ts;
    return steps.length ? `<details class="run" data-key="${esc(key)}" ${S.open.has(key) ? 'open' : ''}><summary>${cells}</summary><ol class="steps done">${steps.map((s) => `<li><span>${esc(s.text)}</span><span class="t num">${mmss(s.t)}</span></li>`).join('')}</ol></details>`
      : `<div class="run"><div class="sum">${cells}</div></div>`;
  }).join('')}</div>`;
}

function tabManage(e, dt) {
  if (!S.cat || !dt) return loading;
  const paused = e.status === 'paused';
  const jobs = Object.entries(JOB_LABELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
  const models = MODELS.map((m) => `<option value="${m}" ${m === e.model ? 'selected' : ''}>${m}${m === 'sonnet' ? ' (balanced)' : m === 'haiku' ? ' (lightest on your plan)' : ' (strongest, heaviest)'}</option>`).join('');
  const on = new Set(dt.abilities);
  const groups = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<div class="ab-group"><h3>${esc(g)}</h3>${items.map((a) => a.locked
      ? `<div class="ab">${icon('check')}<div><div class="n">${esc(a.name)}<span class="badge">always on</span></div><div class="d">${esc(a.description)}</div></div></div>`
      : `<label class="ab"><input type="checkbox" name="abilities" value="${a.id}" ${on.has(a.id) ? 'checked' : ''} form="ab-${e.id}"><div><div class="n">${esc(a.name)}${a.paid ? '<span class="badge warn">paid</span>' : ''}${a.job ? '<span class="badge">routine</span>' : ''}</div><div class="d">${esc(a.description)}</div></div></label>`).join('')}</div>`;
  }).join('');
  return `<div class="manage">
    <section><h2>Status</h2><p class="desc">${paused ? `${esc(e.name)} is paused: no chats or routines until you resume.` : `${esc(e.name)} is working normally.`}</p>
      <div class="save-bar"><button class="btn" data-act="order" data-kind="${paused ? 'resume' : 'pause'}" data-emp="${e.id}">${icon(paused ? 'play' : 'pause')}${paused ? 'Resume' : 'Pause'}</button></div></section>
    <section><h2>Run a routine now</h2><p class="desc">The result shows up in the chat and the team room.</p>
      <div class="save-bar"><select class="select auto" id="run-job" aria-label="Routine">${jobs}</select><button class="btn" data-act="order" data-kind="run_job" data-emp="${e.id}" data-from="#run-job" ${paused ? 'disabled' : ''}>Run now</button></div></section>
    <section><h2>Model</h2><p class="desc">${esc(e.name)} switches to the lightest model on their own when your plan is nearly used up.</p><div><select class="select auto" data-field="model" data-emp="${e.id}" aria-label="Model">${models}</select></div></section>
    <section><h2>Abilities</h2><p class="desc">What ${esc(e.name)} may do. These are locks: anything off is blocked, whatever anyone says in chat. Changes apply on their next run.</p>
      <form id="ab-${e.id}" data-form="abilities" data-emp="${e.id}"><div class="ab-bar"><button class="btn btn-primary" type="submit">Save</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super agent</button><span class="meta">${on.size} of ${S.cat.abilities.length} on</span></div></form>
      <div class="ab-groups">${groups}</div></section>
    <section><h2>Retire</h2><p class="desc">They stop working; their folder and memory stay on this Mac.</p><div><button class="btn btn-danger" data-act="retire" data-emp="${e.id}" data-name="${esc(e.name)}">Retire ${esc(e.name)}…</button></div></section>
  </div>`;
}

// ---- abilities matrix
PAGES.abilities = () => {
  const d = S.data, emps = d.employees;
  if (!S.cat) return loading;
  if (!emps.length) return `<header class="page-head"><div><h1>Abilities</h1></div></header><div class="empty"><b>Hire someone first.</b><p>Their abilities appear here as a column of checkboxes.</p></div>`;
  const head = emps.map((e) => `<th><div>${esc(e.name)}</div><div class="acts"><button class="btn btn-sm btn-primary" type="submit" form="mx-${e.id}">Save</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super</button></div></th>`).join('');
  const rows = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<tr class="g"><th colspan="${emps.length + 1}">${esc(g)}</th></tr>` + items.map((a) => `<tr><td><div>${esc(a.name)}${a.paid ? ' <span class="badge warn">paid</span>' : ''}</div><div class="d">${esc(a.description)}</div></td>${emps.map((e) => a.locked
      ? `<td class="c" title="Always on">${icon('check')}</td>`
      : `<td class="c"><input type="checkbox" form="mx-${e.id}" name="abilities" value="${a.id}" ${(e.abilities || []).includes(a.id) ? 'checked' : ''} aria-label="${esc(a.name)} for ${esc(e.name)}"></td>`).join('')}</tr>`).join('');
  }).join('');
  return `<header class="page-head"><div><h1>Abilities</h1><p class="sub">Tick what each employee may do. <b>Default</b> is a capable, low-cost setup; <b>Super agent</b> ticks everything. Changes apply on their next run.</p></div><div class="actions"><a class="btn" href="/team">Back to the team</a></div></header>
    ${emps.map((e) => `<form id="mx-${e.id}" data-form="abilities" data-emp="${e.id}"></form>`).join('')}
    <div class="matrix-wrap"><table class="matrix"><thead><tr><th>Ability</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
};

// ---- hire
PAGES.hire = (r) => {
  if (!S.roles) return loading;
  if (r.role && !S.job) { S.situation = S.situation || 'other'; pickJob(r.role, false); }
  const sit = situationOf();
  return `<header class="page-head"><div><h1>${sit ? 'What should they take off your plate?' : 'Build an AI employee.'}</h1><p class="sub">${sit ? 'Pick a job; they start with a real first task.' : 'First, what do you do?'}</p></div></header>${jobPicker('hire')}`;
};

// ---- settings
PAGES.settings = () => {
  const s = S.settings, d = S.data;
  if (!s) return loading;
  const wd = v('settings', 'workdays', s.workdays);
  const days = DAYS.map((x) => `<label class="chip ${wd.includes(x) ? 'on' : ''}"><input class="sr" type="checkbox" name="workdays" value="${x}" ${wd.includes(x) ? 'checked' : ''}>${x}</label>`).join('');
  const times = Object.entries(JOB_LABELS).map(([k, l]) => `<div class="field"><label for="t-${k}">${l}</label><input id="t-${k}" class="input" name="jobs.${k}" value="${esc(v('settings', 'jobs.' + k, s.jobs[k]))}" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" inputmode="numeric" placeholder="08:30"></div>`).join('');
  const budget = Number(s.apify.monthly_budget_usd || 5), spent = Number(s.apify.spent || 0);
  const pct = budget ? Math.min(100, (spent / budget) * 100) : 0;
  const real = d.owners.filter((o) => !o.local);
  const pending = d.pending.length ? `<div class="list">${d.pending.map((p) => `<div class="row row-3"><div><div class="title">${esc(p.name || 'Someone')} ${p.username ? `<span class="muted">@${esc(p.username)}</span>` : ''}</div><div class="meta">${esc(CH[p.channel] || 'Chat')} id ${esc(String(p.id).replace(/^[a-z]+:/, ''))} · ${fmtTime(p.at)}</div></div>
    <span class="status"><button class="btn btn-sm btn-primary" data-act="owner" data-id="${esc(p.id)}" data-do="approve" data-name="${esc(p.name || '')}">Make owner</button>${real.length ? `<select class="select auto" data-into="${esc(p.id)}" aria-label="Same person as"><option value="">Same person as…</option>${real.map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('')}</select>` : ''}</span>
    <button class="btn btn-sm" data-act="owner" data-id="${esc(p.id)}" data-do="ignore">Ignore</button></div>`).join('')}</div>` : '';
  const chans = Object.entries(CH).map(([k, l]) => { const c = s.channels[k] || {}; return `<div class="row row-2"><div><div class="title">${l}</div><div class="meta">${c.on ? 'connected' + (c.team_chat ? ' · team chat ' + esc(c.team_chat) : '') : 'not connected'}</div></div><a class="btn btn-sm" href="/connect?ch=${k}">${c.on ? 'Manage' : 'Connect'}</a></div>`; }).join('');
  const orders = d.orders.slice(-15).reverse();
  return `<header class="page-head"><div><h1>Settings</h1></div></header>
  <div class="settings">
  <form class="settings" data-form="settings">
    <section><h2>Your business</h2><p class="desc">Every employee reads this before they work.</p>
      <div class="field"><label for="tn">Team name</label><input id="tn" class="input" name="team_name" maxlength="60" value="${esc(v('settings', 'team_name', s.team_name))}"></div>
      <div class="field"><label for="ab">About the business</label><textarea id="ab" class="textarea" name="about" rows="7" maxlength="6000" placeholder="What you do, for whom, what matters most right now, names they should know.">${esc(v('settings', 'about', s.about))}</textarea></div>
      <div class="field"><span class="lbl">Workdays</span><div class="chips">${days}</div><span class="hint">Routines run on these days.</span></div></section>
    <section><h2>Routine times</h2><p class="desc">Local time on this Mac. Each employee runs only the routines ticked in their abilities.</p><div class="times">${times}</div></section>
    <section id="research"><h2>Research budget</h2><p class="desc">Apify reads TikTok, Instagram, Facebook, YouTube, X and Google Maps for your employees. Paid per use, never beyond this budget.</p>
      <div class="usage-box"><div class="row2"><span>Spent this month</span><b class="num">${money(spent)} of ${money(budget)}</b></div><div class="meter ${pct >= 80 ? 'hot' : ''}"><i data-w="${pct}"></i></div></div>
      <div class="form-row"><div class="field"><label for="amb">Monthly budget (USD)</label><input id="amb" class="input" name="apify.monthly_budget_usd" inputmode="decimal" value="${esc(v('settings', 'apify.monthly_budget_usd', s.apify.monthly_budget_usd ?? 5))}"></div>
      <div class="field"><label for="amr">Max per run (USD)</label><input id="amr" class="input" name="apify.max_run_usd" inputmode="decimal" value="${esc(v('settings', 'apify.max_run_usd', s.apify.max_run_usd ?? 0.5))}"><span class="hint">Hard ceiling 2.00.</span></div></div></section>
    <details class="adv"><summary>Advanced</summary><section class="mt"><h2>Sites their own scripts may reach</h2><p class="desc">Web search, the page reader, the browser and Apify work without this list; it only limits scripts employees write themselves.</p>
      <div class="field"><textarea class="textarea" name="network_domains" rows="3" placeholder="api.example.com&#10;*.example.org" aria-label="Allowed sites">${esc(v('settings', 'network_domains', s.network_domains.join('\n')))}</textarea></div></section></details>
    <div class="save-bar"><button class="btn btn-primary" type="submit">Save settings</button></div>
  </form>
  <section><h2>Apify token</h2><p class="desc">${s.apify.token ? 'Connected.' : 'A free account at <a class="link" href="https://console.apify.com/sign-up" target="_blank" rel="noopener">apify.com</a> includes monthly credit. Copy your API token from Settings → Integrations there.'}</p>
    <form class="connect-form row-form" data-form="connect" data-kind="apify"><input id="c-apify" class="input mono" name="token" required autocomplete="off" spellcheck="false" placeholder="${s.apify.token ? 'Paste a new token to replace it' : 'apify_api_…'}"><button class="btn" type="submit">${s.apify.token ? 'Replace' : 'Add'}</button></form></section>
  <section id="channels"><h2>Chat channels</h2><p class="desc">Your employees answer you through bots you create. Each one talks only to your bots.</p><div class="list">${chans}</div></section>
  <section id="access"><h2>Access</h2><p class="desc">Owners can direct every employee. Only approve people you know.</p>
    <dl class="kv">${d.owners.map((o) => `<dt>${esc(o.name)}</dt><dd>${o.local ? 'this Mac only · <a class="link" href="/connect">connect your phone</a>' : esc((o.addresses || []).join(' · '))}</dd>`).join('')}</dl>
    ${pending ? `<h3>Messaged your bot</h3>${pending}` : `<p class="meta">Nobody is waiting for approval.</p>`}</section>
  <section><h2>Appearance</h2><div class="seg" role="group" aria-label="Appearance"><button data-act="theme" data-v="" class="${S.theme === '' ? 'on' : ''}">Match the Mac</button><button data-act="theme" data-v="light" class="${S.theme === 'light' ? 'on' : ''}">Light</button><button data-act="theme" data-v="dark" class="${S.theme === 'dark' ? 'on' : ''}">Dark</button></div></section>
  <section><h2>About this install</h2>
    <dl class="kv"><dt>Claude</dt><dd>${s.claude.ok ? `signed in (${esc(s.claude.note)})` : '<span class="badge danger">not signed in</span> ask Claude: “Sign in Claude Code for my Staffroom.”'} · runs on ${s.auth === 'api_key' ? 'your API key' : 'your subscription'}</dd>
      <dt>Service</dt><dd>${d.online ? 'running' : '<span class="badge danger">stopped</span>'} · panel on port ${s.port}</dd>
      <dt>Team folder</dt><dd><code>${esc(s.home)}</code></dd><dt>Kit</dt><dd><code>${esc(s.kit)}</code></dd></dl></section>
  <section><h2>History</h2>${orders.length ? `<div class="list mini">${orders.map((o) => `<div class="row row-2"><div><div class="small">${esc(o.summary)}</div><div class="meta">${esc(o.by)} · ${fmtTime(o.ts)}${o.result ? ' · ' + esc(o.result) : ''}</div></div><span class="badge ${o.status === 'failed' ? 'danger' : ''}">${esc(o.status)}</span></div>`).join('')}</div>` : '<p class="quiet">Nothing yet.</p>'}</section>
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
    if (/^```/.test(l)) { let j = i + 1; const buf = []; while (j < lines.length && !/^```/.test(lines[j])) buf.push(lines[j++]); out += `<pre><code>${esc(buf.join('\n'))}</code></pre>`; i = j + 1; continue; }
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
async function sendMessage(f) {
  const emp = f.dataset.emp, ta = f.querySelector('textarea');
  const text = (ta.value || '').trim();
  if (!text || S.busy.has('send:' + emp)) return;
  S.busy.add('send:' + emp);
  try {
    await api('/api/order', { kind: 'message', employee_id: emp, text });
    delete S.vals['message:' + emp]; ta.value = ''; grow(ta);
    S.data = await api('/api/state'); await loadDetail(emp); await render(true);
    const box = document.getElementById('composer-' + emp); if (box) box.focus({ preventScroll: true });
  } catch (e) { toast(e.message, 'err'); }
  finally { S.busy.delete('send:' + emp); }
  schedule();
}

document.addEventListener('click', async (ev) => {
  const a = ev.target.closest('a[href]');
  if (a && a.getAttribute('href').startsWith('/') && !a.target && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey) { ev.preventDefault(); go(a.getAttribute('href')); return; }
  const b = ev.target.closest('[data-act]');
  if (!b) return;
  const act = b.dataset.act;
  if (act === 'theme') { setTheme(b.dataset.v); render(true); }
  else if (act === 'more') { const body = b.previousElementSibling; body.classList.remove('clamp'); b.remove(); }
  else if (act === 'job') { pickJob(b.dataset.role); }
  else if (act === 'situation') { ev.preventDefault(); S.situation = b.dataset.id || null; S.job = null; delete S.vals.hire; render(true); }
  else if (act === 'name') { (S.vals.hire ||= {}).name = b.dataset.name; render(true); }
  else if (act === 'try') {
    const emp = b.dataset.emp;
    if (!document.getElementById('composer-' + emp)) { (S.vals['message:' + emp] ||= {}).text = b.dataset.text; go('/e/' + emp); return; }
    const ta = document.getElementById('composer-' + emp);
    if (ta) { ta.value = b.dataset.text; (S.vals['message:' + emp] ||= {}).text = ta.value; grow(ta); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
  }
  else if (act === 'ch') { S.pair = S.pair && S.pair.channel === b.dataset.v ? S.pair : null; go('/connect?ch=' + b.dataset.v, true); }
  else if (act === 'pair') {
    try { S.pair = { ...(await api('/api/pairing', { channel: b.dataset.v })), channel: b.dataset.v }; render(true); schedule(); }
    catch (e) { toast(e.message, 'err'); }
  }
  else if (act === 'copy') {
    const src = $(b.dataset.from);
    try { await navigator.clipboard.writeText(src.textContent); toast('Copied'); }
    catch (e) { const range = document.createRange(); range.selectNodeContents(src); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range); toast('Selected: press ⌘C to copy'); }
  }
  else if (act === 'order') {
    const body = { kind: b.dataset.kind, employee_id: b.dataset.emp };
    if (b.dataset.from) body.job = $(b.dataset.from).value;
    b.disabled = true; await order(body); b.disabled = false; schedule();
  }
  else if (act === 'preset') { await order({ kind: 'set_abilities', employee_id: b.dataset.emp, preset: b.dataset.preset }); if (S.detailId === b.dataset.emp) await loadDetail(b.dataset.emp); render(true); }
  else if (act === 'retire') {
    if (confirm(`Retire ${b.dataset.name}? They stop working; their folder and memory are kept on this Mac.`)) { await order({ kind: 'retire', employee_id: b.dataset.emp }); go('/team'); }
  }
  else if (act === 'skill') {
    const { emp, where, name } = b.dataset;
    if (b.dataset.do === 'remove' && !confirm(`Remove the skill “${name}”${where === 'team' ? ' from the team' : ''}? They stop using it on their next run.`)) return;
    try {
      const r = await api('/api/skill', { emp, where, name, do: b.dataset.do }); toast(r.message);
      S.skill = null; await loadDetail(emp); S.data = await api('/api/state');
      go(b.dataset.do === 'remove' ? `/e/${emp}/knowledge` : `/e/${emp}/knowledge?f=${b.dataset.do === 'share' ? 'team' : where}:${name}`);
    } catch (e) { toast(e.message, 'err'); }
  }
  else if (act === 'owner') {
    const name = b.dataset.do === 'approve' ? (prompt('Their name, as employees will call them:', b.dataset.name || '') || '').trim() : '';
    if (b.dataset.do === 'approve' && !name) return;
    try { const r = await api('/api/owner', { id: b.dataset.id, do: b.dataset.do, name }); toast(r.message); S.settings = await api('/api/settings'); await refresh(true); }
    catch (e) { toast(e.message, 'err'); }
  }
});

document.addEventListener('toggle', (ev) => {              // keep "How I did it" open across refreshes
  const d = ev.target;
  if (d.tagName === 'DETAILS' && d.dataset.key) { if (d.open) S.open.add(d.dataset.key); else S.open.delete(d.dataset.key); }
}, true);

document.addEventListener('change', async (ev) => {
  const sel = ev.target.closest('select[data-field]');
  if (sel) { await order({ kind: 'set_field', employee_id: sel.dataset.emp, field: sel.dataset.field, value: sel.value }); return; }
  const into = ev.target.closest('select[data-into]');
  if (into && into.value) {
    try { const r = await api('/api/owner', { id: into.dataset.into, do: 'approve', into: into.value }); toast(r.message); S.settings = await api('/api/settings'); await refresh(true); }
    catch (e) { toast(e.message, 'err'); }
    return;
  }
  const chip = ev.target.closest('label.chip');
  if (chip) chip.classList.toggle('on', ev.target.checked);
});

document.addEventListener('input', (ev) => {
  const f = ev.target.closest('form[data-form]');
  if (!f || !ev.target.name) return;
  const key = f.dataset.form + (f.dataset.emp ? ':' + f.dataset.emp : '') + (f.dataset.form === 'skill' ? ':' + f.dataset.where + ':' + f.dataset.name : '');
  const vals = (S.vals[key] ||= {});
  if (ev.target.type === 'checkbox') vals[ev.target.name] = [...f.querySelectorAll(`input[name="${ev.target.name}"]:checked`)].map((x) => x.value);
  else vals[ev.target.name] = ev.target.value;
  if (ev.target.hasAttribute('data-grow')) grow(ev.target);
  if (f.dataset.form === 'hire' && ev.target.name === 'name') { const btn = f.querySelector('[data-hire-label]'); if (btn) btn.innerHTML = `${icon('plus')}Hire ${esc(ev.target.value.trim() || 'them')}`; }
});

document.addEventListener('keydown', (ev) => {
  const f = ev.target.closest && ev.target.closest('form[data-form="message"]');
  if (!f || ev.target.tagName !== 'TEXTAREA' || ev.isComposing || ev.keyCode === 229) return;     // IME (Arabic, CJK) composing: leave Enter alone
  if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey || !ev.shiftKey)) { ev.preventDefault(); sendMessage(f); }
});

document.addEventListener('submit', async (ev) => {
  const f = ev.target.closest('form[data-form]');
  if (!f) return;
  ev.preventDefault();
  const kind = f.dataset.form, emp = f.dataset.emp;
  if (kind === 'message') { sendMessage(f); return; }
  const fd = new FormData(f);
  const btn = f.querySelector('button[type="submit"]'); if (btn) btn.disabled = true;
  try {
    if (kind === 'welcome') {
      await api('/api/welcome', { name: fd.get('name'), team_name: fd.get('team_name'), about: fd.get('about') });
      delete S.vals.welcome; S.data = await api('/api/state'); await render(true);
    } else if (kind === 'hire') {
      const sel = S.roles.roles.find((x) => x.id === S.job) || {};
      const body = { kind: 'hire', name: fd.get('name'), role: fd.get('role') || sel.role, scope: fd.get('scope') || sel.scope,
        supervisor: fd.get('supervisor') || S.data.me, model: fd.get('model') || sel.model || 'sonnet' };
      const picked = new Set(fd.getAll('access'));
      body.abilities = ALWAYS.concat(...ACCESS.filter(([k]) => picked.has(k)).map(([, , ids]) => ids));
      const r = await api('/api/order', body);
      const id = (r.message.match(/\/([a-z0-9-]+)$/) || [])[1];
      delete S.vals.hire; S.job = null;
      S.data = await api('/api/state');
      go(id ? `/e/${id}` : '/team');
      schedule();
    } else if (kind === 'connect') {
      const r = await api('/api/connect', { kind: f.dataset.kind, token: fd.get('token'), app_token: fd.get('app_token') });
      toast(r.message);
      if (f.dataset.kind === 'apify') { S.settings = await api('/api/settings'); await refresh(true); }
      else { S.pair = r; S.data = await api('/api/state'); render(true); schedule(); }
    } else if (kind === 'abilities') {
      const r = await api('/api/order', { kind: 'set_abilities', employee_id: emp, abilities: fd.getAll('abilities') });
      toast(r.message); await loadDetail(emp); await refresh(true);
    } else if (kind === 'skill') {
      const r = await api('/api/skill', { emp, where: f.dataset.where, name: f.dataset.name, do: 'save', text: fd.get('text') || '' });
      toast(r.message); delete S.vals['skill:' + emp + ':' + f.dataset.where + ':' + f.dataset.name]; S.skill = null; await loadDetail(emp); render(true);
    } else if (kind === 'teach') {
      const name = String(fd.get('name') || '').trim().toLowerCase();
      const r = await api('/api/skill', { emp, do: 'create', name, description: fd.get('description') || '', text: fd.get('text') || '' });
      toast(r.message); delete S.vals['teach:' + emp]; await loadDetail(emp); S.data = await api('/api/state');
      go(`/e/${emp}/knowledge?f=own:${name}`);
    } else if (kind === 'rules') {
      const r = await api(`/api/employee/${emp}/rules`, { text: fd.get('text') || '' });
      toast(r.message); delete S.vals['rules:' + emp]; await loadDetail(emp); render(true);
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

// ---------------------------------------------------------------- polling (faster while someone works)
let timer = null;
function waitingToPair() { return route().page === 'connect' && S.pair && S.pair.code && !S.pair.paired; }
function schedule() {
  clearTimeout(timer);
  const fast = S.data && (Object.keys(S.data.live || {}).length || waitingToPair());
  timer = setTimeout(tick, document.hidden ? 15000 : fast ? 2000 : 8000);
}
async function tick() {
  if (!document.hidden) {
    try {
      S.data = await api('/api/state');
      const r = route();
      if (r.page === 'employee' && Date.now() - S.detailAt > 2500) await loadDetail(r.id);
      if (waitingToPair()) {
        const p = await api('/api/pairing');
        if (p.paired) { S.pair = { ...S.pair, ...p, code: null }; toast('Your phone is connected'); }
        else S.pair = { ...S.pair, ...p, channel: S.pair.channel, link: p.link || S.pair.link };
      }
      await render(false);
    } catch (e) { /* keep the last view; the next poll retries */ }
  }
  schedule();
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) { refresh(false).catch(() => {}); schedule(); } });

render(true).then(schedule);
