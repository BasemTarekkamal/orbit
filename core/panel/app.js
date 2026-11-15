/* Orbit Mission Control (the control panel). Plain JavaScript, no build step: it reads the JSON API in core/panel.py and
   renders each page as HTML. Polls every 8 seconds, every 2 while someone is working so you can watch
   them; never re-renders a form you're typing in, but keeps the live work view moving. */
'use strict';

// ---------------------------------------------------------------- utils
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const main = $('#main');
const side = $('#side');
const JOB_LABELS = { brief: 'Morning brief', standup: 'Standup', initiative: 'Initiative', eod: 'End of day', review: 'Weekly review', scout: 'Self-improvement', evals: 'Weekly self-test' };
const RUN_LABELS = { ...JOB_LABELS, chat: 'Chat', first_day: 'First day', minutes: 'Meeting minutes', followup: 'Follow-up', bus: 'A colleague’s question' };
const MODELS = ['opus', 'sonnet', 'haiku'];
const NOTES = [['STATE.md', 'State'], ['TASKS.md', 'Tasks'], ['GOALS.md', 'Goals'], ['LESSONS.md', 'Lessons'], ['EXPERIENCE.md', 'Experience'], ['CLAUDE.md', 'Instructions']];
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const CH = { telegram: 'Telegram', slack: 'Slack', discord: 'Discord' };
const CANT = ['Spend money or buy anything', 'Post, email or message anyone but you', 'Log in to accounts', 'See your passwords or private folders'];
const ACCESS = [
  ['web', 'Web search and reading', ['web', 'fetch']],
  ['social', 'TikTok, Instagram, Facebook, X, Reddit, YouTube, Maps', ['apify']],
  ['browser', 'Headless browser for hard pages', ['browser']],
  ['docs', 'Documents, scans and photos you send', ['documents', 'files']],
  ['watch', 'Watchers on pages and feeds', ['watchers']],
  ['calls', 'Calls (live or recorded) and voice notes', ['meetings', 'voice']],
  ['remind', 'Reminders and follow-ups', ['reminders']],
  ['learn', 'Learns the skills you teach', ['learn']],
  ['tools', 'Builds its own small tools', ['build_tools']],
  ['brief', 'A brief every workday morning', ['brief']],
];
const SITES = [['YouTube', 'youtube.com'], ['TikTok', 'tiktok.com'], ['Facebook', 'facebook.com'], ['Instagram', 'instagram.com'],
  ['X', 'x.com'], ['LinkedIn', 'linkedin.com'], ['Google Business', 'business.google.com'], ['Shopify', 'myshopify.com']];
const COMING = ['Your own browser, acting as you', 'Email inbox', 'Google Docs and Notion', 'GitHub (private)'];
const ALWAYS = ['telegram', 'team_room'];
const SLACK_MANIFEST = `display_information:
  name: Orbit
  description: My AI team
features:
  app_home:
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  bot_user:
    display_name: Orbit
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
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>'),
  phone: svg('<rect x="7" y="3" width="10" height="18" rx="2.5"/><path d="M11 18h2"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>'),
  manage: svg('<circle cx="12" cy="12" r="3"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>'),
  key: svg('<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8M16 7l2 2M14 9l2 2"/>'),
  eye: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>'),
  chat: svg('<path d="M4 5h16v11H9l-5 4z"/>'),
  target: svg('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8"/>'),
  share: svg('<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="m8.2 10.8 7.6-3.6M8.2 13.2l7.6 3.6"/>'),
  download: svg('<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>'),
  claude: svg('<path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4"/>', 2),
  lock: svg('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  film: svg('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M10 9.5v5l4.5-2.5z"/>'),
  doc: svg('<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>'),
  link: svg('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
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
// The computer the panel runs on, for the words: 'Mac', or 'PC' on Windows, 'computer' on Linux
const MAC = () => (S.data && S.data.device) || 'Mac';
const S = { data: null, detail: null, detailId: null, detailAt: 0, cat: null, roles: null, settings: null, file: null, fileLoading: '',
  skill: null, skillLoading: '', pair: null, job: null, situation: null, theme: store(() => localStorage.getItem('theme')) || '', lastHtml: '', vals: {},
  open: new Set(), busy: new Set(), gone: new Set(), needsAll: false, tryIdx: {} };

async function api(path, body) {
  const opt = body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error(j.error || (r.status === 401 ? 'Signed out: run `orbit panel` to open the panel again.' : 'HTTP ' + r.status));
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
  if (p === '/room') return { page: 'room' };
  if (p === '/objectives') return { page: 'objectives' };
  if (p === '/metrics') return { page: 'metrics' };
  if (p === '/welcome') return { page: 'welcome' };
  if (p === '/connect') return { page: 'connect', ch: q.get('ch') || '' };
  if (p === '/team') return { page: 'team' };
  if (p === '/hire') return { page: 'hire', role: q.get('role') };
  if (p === '/abilities') return { page: 'abilities' };
  if (p === '/settings') return { page: 'settings' };
  const m = p.match(/^\/e\/([a-z0-9-]+)(?:\/([a-z]+))?$/);
  if (m) {
    const alias = { memory: 'knowledge', skills: 'knowledge', activity: 'work', abilities: 'manage' };   // older links
    const tab = alias[m[2]] || m[2] || 'overview';
    if (!['overview', 'plan', 'chat', 'knowledge', 'work', 'manage'].includes(tab)) return { page: 'missing' };
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
    if ((r.page === 'abilities' || (r.page === 'employee' && (r.tab === 'manage' || r.tab === 'overview'))) && !S.cat) S.cat = await api('/api/abilities');
    if ((r.page === 'hire' || r.page === 'welcome') && !S.roles) S.roles = await api('/api/roles');
    if (r.page === 'settings' && (nav || !S.settings)) S.settings = await api('/api/settings');
    if (r.page === 'metrics' && (nav || !S.metrics)) S.metrics = await api('/api/metrics');
  } catch (e) { toast(e.message, 'err'); }
  document.body.classList.toggle('solo', r.page === 'welcome');
  renderSide(r);
  const active = document.activeElement;
  const inMain = !!active && main.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName);
  if (inMain && !nav && (active.value || active.tagName === 'SELECT' || active.type === 'checkbox')) { patchLive(); return; }
  const focusId = inMain ? active.id : '';
  const chat = r.page === 'employee' && r.tab === 'chat';
  if (chat || r.page === 'today' || r.page === 'room') markSeen();
  const cm = chat && $('.chat-main', main);
  const following = !!cm && cm.getBoundingClientRect().bottom <= window.innerHeight + 60;   // you're at the latest message
  const pretend = S.data && S.data.demo && r.page !== 'room'
    ? '<div class="demo-bar"><b>Demo:</b> a pretend team. Replies are scripted and nothing runs Claude.</div>' : '';
  const html = pretend + (PAGES[r.page] || PAGES.missing)(r);
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
  return ({ today: 'Home', room: 'Team room', objectives: 'Objectives', metrics: 'Metrics', team: 'Crew', hire: 'Add crew', abilities: 'Abilities', settings: 'Settings', welcome: 'Welcome', connect: 'Your phone' }[r.page] || 'Orbit') + ' · ' + t;
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
  const on = (...p) => (p.includes(r.page) ? ' class="on" aria-current="page"' : '');
  const items = [['/', 'Home', ['today']], ['/team', 'Crew', ['team', 'employee', 'abilities']], ['/objectives', 'Objectives', ['objectives']],
    ['/metrics', 'Metrics', ['metrics']], ['/hire', 'Hire', ['hire']]];
  side.innerHTML = `
    <a class="brand" href="/" aria-label="Orbit, home"><img src="/icon.svg" alt=""><span class="brand-name">Orbit</span>${d.demo ? ' <span class="badge accent">demo</span>' : ''}</a>
    <div class="topnav-wrap"><nav class="topnav" aria-label="Main">${items.map(([h, l, pg]) => `<a href="${h}"${on(...pg)}>${l}</a>`).join('')}</nav></div>
    ${d.online ? '' : '<span class="badge danger">Service stopped</span>'}
    <a class="iconbtn${['settings', 'connect'].includes(r.page) ? ' on' : ''}" href="/settings" aria-label="Settings" title="Settings">${icon('manage')}</a>`;
  navFade();
}
function navFade() {            // a fade on the right edge of the scrolling nav, gone once it is scrolled to the end
  const n = $('.topnav', side), w = $('.topnav-wrap', side);
  if (n && w) w.classList.toggle('fade', n.scrollLeft + n.clientWidth < n.scrollWidth - 2);
}
document.addEventListener('scroll', (ev) => { if (ev.target.classList && ev.target.classList.contains('topnav')) navFade(); }, true);
window.addEventListener('resize', navFade);

function afterRender(r, nav) {
  syncLaunch(r);
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
function callOf(id) { return (S.data.calls || {})[id] || null; }
function callCard(id, compact) {             // a crew member listening to a live call: elapsed time, the latest line, end it
  const c = callOf(id);
  if (!c) return '';
  const e = S.data.employees.find((x) => x.id === id);
  const last = c.last ? c.last.replace(/^\[[^\]]+\]\s*/, '') : (c.ending ? 'Writing the minutes…' : 'Listening… the first lines appear within a minute.');
  return `<div class="call${c.ending ? ' ending' : ''}"><div class="call-head"><i class="rec"></i><b>${esc(e ? e.name : id)} ${c.ending ? 'is writing the minutes' : 'is on your call'}</b><span class="meta">${esc(c.title)} · <span class="num" data-since="${esc(c.started)}"></span> · ${plural(c.lines, 'line')}</span>
    ${c.ending ? '' : `<button class="btn btn-sm" data-act="order" data-kind="call_stop" data-emp="${id}">End call</button>`}</div>
    <p class="call-last">${esc(last)}</p>${compact ? '' : `<p class="meta">Ask ${esc(e ? e.name : 'them')} anything about it while it runs. Heard on this ${MAC()} only: no bot joins, the audio is deleted once transcribed. <a class="link" href="/e/${id}/work?v=files&f=${encodeURIComponent(c.transcript)}">Read the transcript</a></p>`}</div>`;
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
  if (callOf(e.id)) return `<span class="status"><i class="rec"></i>On a call</span>`;
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
  const inter = step === 2 && S.ob && S.ob.stage !== 'basics';
  const steps = `<ol class="w-steps"><li class="${step > 1 ? 'done' : 'on'}">You</li><li class="${step === 2 && !inter ? 'on' : inter ? 'done' : ''}">Their job</li><li class="${inter ? 'on' : ''}">The interview</li><li>Meet them in Claude</li></ol>`;
  const brand = `<div class="w-brand"><img src="/icon.svg" alt=""><span>Orbit</span></div>`;
  if (step === 1) {
    return `<div class="welcome">${brand}<h1>Build your crew.</h1>
      <p class="lede">Your AI workforce. In motion. Build your team, assign missions, get things done, on the Claude plan you already have.</p>${steps}
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
  const cards = order.map((x) => `<button type="button" class="job ${S.job === x.id ? 'on' : ''}" data-act="job" data-role="${x.id}" aria-pressed="${S.job === x.id}"><b>${esc(x.title)}</b><span>${esc(x.role || 'Your own job')}${x.source ? ` · <em>${x.source === 'yours' ? 'your role' : 'community'}</em>` : ''}${x.trained_by ? ` · trained by ${esc(x.trained_by)}` : ''}</span></button>`).join('');
  const back = `<p class="meta sit-line">${esc(sit.title)} · <a class="link" href="#" data-act="situation" data-id="">change</a>${sit.id === 'other' ? '' : ` · <a class="link" href="#" data-act="situation" data-id="other">all jobs</a>`}</p>`;
  const sel = roles.find((x) => x.id === S.job);
  if (!sel) return back + `<div class="jobs">${cards}</div>`;
  if (S.ob && S.ob.job === sel.id && S.ob.stage !== 'basics') {
    return `<p class="meta sit-line">${esc(sel.title)} · <a class="link" href="#" data-act="ob-restart">change the job</a></p>${interviewHtml(sel, from)}`;
  }
  return back + `<div class="jobs">${cards}</div>${interviewHtml(sel, from)}`;
}
// ---- the hiring interview: the basics, then the owner's own Claude asks what this job needs and writes the card
const BUDGET_LABELS = { light: ['Light', '≈1M tokens a week'], regular: ['Regular', '≈3M tokens a week'], heavy: ['Heavy', '≈8M tokens a week'] };
const ACCESS_KIND = { sign_in: ['key', 'Signs in to read', 'You sign in once, in their own browser on this computer'],
  post_with_approval: ['send', 'Posts after you approve', 'They prepare it; you tap Approve; they post it'],
  finance_read_only: ['eye', 'Reads money, never moves it', 'Statements and balances only'],
  files: ['file', 'Files you share', ''], chat_channel: ['chat', 'A chat channel', ''], other: ['plus', 'Other', ''] };
function fmtTok(n) { n = Number(n) || 0; return n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n); }
function thinking(title, lines) {
  return `<div class="w-card think" role="status" aria-live="polite"><div class="orbit-spin" aria-hidden="true"><i></i><i></i><i></i></div>
    <div><b>${esc(title)}</b><ul class="think-lines">${lines.map((l, i) => `<li>${esc(l)}</li>`).join('')}</ul></div></div>`;
}
// A shared or saved role shows everything it brings before you hire from it: who trained it, its rules, skills, experience.
function bringsHtml(sel) {
  if (!sel.source || !(sel.rules || sel.experience || (sel.skills_in || []).length)) return '';
  const st = sel.stats || {};
  return `<details class="brings"><summary>${sel.trained_by ? `Trained by <b>${esc(sel.trained_by)}</b>` : 'What this role brings'}${st.days ? ` · ${plural(st.days, 'day')} on the job, ${plural(st.lessons || 0, 'lesson')}, ${plural(st.skills || 0, 'skill')}` : ''} · see everything it brings</summary>
    ${sel.experience ? `<h4>Experience</h4><div class="md small">${md(sel.experience)}</div>` : ''}
    ${sel.rules ? `<h4>Rules</h4><div class="md small">${md(sel.rules)}</div>` : ''}
    ${(sel.skills_in || []).length ? `<h4>Skills</h4><p class="small">${sel.skills_in.map(esc).join(', ')}</p>` : ''}</details>`;
}
function interviewHtml(sel, from) {
  const ob = S.ob && S.ob.job === sel.id ? S.ob : (S.ob = { job: sel.id, stage: 'basics' });
  const custom = sel.id === 'blank';
  const name = v('hire', 'name', sel.names[0] || '');
  const who = esc(name || 'them');
  if (ob.stage === 'asking') return thinking(`Your Claude is preparing ${name || 'their'} interview…`, ['Reading about your business', `Thinking about what a ${(v('hire', 'role', sel.role) || 'crew member').toLowerCase()} needs to know`, 'Writing a few questions for you']);
  if (ob.stage === 'composing') return thinking(`Building ${name || 'their'} card…`, ['Reading your answers', 'Choosing responsibilities and routines', 'Deciding what access to ask you for', 'Planning the first days']);
  if (ob.stage === 'questions') {
    const qs = ob.questions || [];
    return `<form class="w-card interview" data-form="interview" data-from="${from}">
      ${ob.intro ? `<p class="lede small">${esc(ob.intro)}</p>` : ''}
      ${qs.map((q, i) => {
        const a = ob.answers[q.id] || (q.type === 'multi' ? [] : '');
        const opts = q.type === 'text' ? `<input class="input" name="${q.id}" maxlength="1500" placeholder="${esc(q.placeholder || '')}" value="${esc(a)}">`
          : `<div class="chips">${q.options.map((o) => { const on = q.type === 'multi' ? a.includes(o) : a === o;
              return `<button type="button" class="chip ${on ? 'on' : ''}" data-act="answer" data-q="${q.id}" data-multi="${q.type === 'multi' ? 1 : ''}" data-v="${esc(o)}" aria-pressed="${on}">${esc(o)}</button>`; }).join('')}</div>
            <input class="input other" name="${q.id}__other" maxlength="400" placeholder="Or in your own words" value="${esc(ob.answers[q.id + '__other'] || '')}">`;
        return `<fieldset class="q"><legend><span class="qn">${i + 1}</span>${esc(q.text)}</legend>${q.why ? `<p class="meta">${esc(q.why)}</p>` : ''}${opts}</fieldset>`;
      }).join('')}
      <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit">Build ${who}'s card</button>
        <button type="button" class="btn btn-ghost" data-act="ob-back">Back</button></div></form>`;
  }
  if (ob.stage === 'card' && ob.card) return cardHtml(sel, ob, name, from);
  // basics
  const status = (sel.today ? `<p class="small status-line">${esc(sel.today)}</p>` : '') + bringsHtml(sel);
  return `<form class="w-card hire-bar" data-form="basics" data-from="${from}">
      <div class="form-row"><div class="field"><label for="h-name">Their name</label><input id="h-name" class="input lg" name="name" required maxlength="60" value="${esc(name)}" placeholder="Sara">
        ${sel.names.length ? `<div class="chips">${sel.names.map((n) => `<button type="button" class="chip ${name === n ? 'on' : ''}" data-act="name" data-name="${esc(n)}">${esc(n)}</button>`).join('')}</div>` : ''}</div>
      ${custom && from === 'hire' ? '<input type="hidden" name="role" value="Crew member">' : custom ? `<div class="field"><label for="h-role">Job title</label><input id="h-role" class="input lg" name="role" required maxlength="120" value="${esc(v('hire', 'role', ''))}" placeholder="Bookkeeper"></div>` : ''}</div>
      <div class="field"><label for="h-scope">${custom ? 'The job, in your own words' : 'What you want from them, in your own words'}</label><textarea id="h-scope" class="textarea" name="scope" rows="3" ${custom ? 'required' : ''} maxlength="2000" placeholder="${custom ? 'Keep my books from the bank statements I send each month: sort every line, flag anything odd, send me a one-page summary.' : esc(sel.scope)}">${esc(v('hire', 'scope', custom ? '' : sel.scope))}</textarea>
        <span class="hint">Say it the way you'd brief a person. Next, your Claude asks a few questions about it.</span></div>
      ${status}
      <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit">Continue</button><span class="meta">A few questions, about a minute.</span></div>
    </form>`;
}
function cardHtml(sel, ob, name, from) {
  const c = ob.card, ed = ob.edit;
  const on = new Set(ed.access);
  const access = `<div class="chips">${ACCESS.filter(([k]) => k !== 'brief').map(([k, l]) => `<button type="button" class="chip ${on.has(k) ? 'on' : ''}" data-act="ob-access" data-k="${k}" aria-pressed="${on.has(k)}">${esc(l)}</button>`).join('')}</div>`;
  const routines = [['brief', 'Morning brief'], ['standup', 'Standup'], ['initiative', 'Initiative'], ['eod', 'End of day']].map(([k, l]) =>
    `<button type="button" class="chip ${ed.routines[k] ? 'on' : ''}" data-act="ob-routine" data-k="${k}" aria-pressed="${!!ed.routines[k]}">${l}</button>`).join('');
  const asks = (c.access || []).map((a) => { const [ic, label, how] = ACCESS_KIND[a.kind] || ACCESS_KIND.other;
    return `<li>${icon(ic)}<div><b>${esc(a.what)}</b>${a.site ? ` <span class="meta">${esc(a.site)}</span>` : ''}<div class="meta">${esc(label)}${how ? ' · ' + esc(how) : ''}. ${esc(a.why || '')}</div></div></li>`; }).join('');
  const budget = Object.entries(BUDGET_LABELS).map(([k, [l, t]]) => `<button type="button" class="${ed.budget === k ? 'on' : ''}" data-act="ob-budget" data-k="${k}"><b>${l}</b><span>${t}</span></button>`).join('');
  return `<form class="idcard" data-form="hire" data-from="${from}">
    <header class="id-head"><span class="avatar xl hue-${hue(name || 'x')}" aria-hidden="true">${esc((name || '?').charAt(0).toUpperCase())}</span><div><h2>${esc(name || 'New crew member')}</h2><input class="input bare" name="role" maxlength="120" value="${esc(ed.role)}" aria-label="Job title"></div></header>
    <div class="id-grid">
      <section><h3>The job</h3><textarea class="textarea" name="scope" rows="4" data-grow maxlength="2000" aria-label="Scope">${esc(ed.scope)}</textarea>
        <ul class="ticks">${(c.responsibilities || []).map((r) => `<li>${icon('check')}${esc(r)}</li>`).join('')}</ul></section>
      <section><h3>First days</h3><ol class="plan">${(c.plan || []).map((p) => `<li>${esc(p)}</li>`).join('')}</ol>
        <p class="meta">Starts with: ${esc(c.first_task || '')}</p></section>
      ${asks ? `<section class="wide"><h3>Access ${esc(name)} will ask you for</h3><ul class="asks">${asks}</ul>
        <p class="meta">Nothing here is granted yet: ${esc(name)} asks when it's needed, and anything public waits for your Approve. Money is read only, always.</p></section>` : ''}
      <section class="wide grant"><h3>${icon('key')} Let ${esc(name || 'them')} post for you <span class="meta">optional</span></h3>
        <p class="meta">Pick the sites where ${esc(name || 'they')} may post, upload or fill in forms for you, from their own browser window: you sign them in there once. They show you each one first and do it after you approve. Never passwords or money.</p>
        ${sitePicker('ob', ed.browser || [])}
        <div class="seg" role="group" aria-label="Approval"><button type="button" class="${(ed.approval || 'each') === 'each' ? 'on' : ''}" data-act="ob-approval" data-v="each">Ask me for each one</button><button type="button" class="${ed.approval === 'batch' ? 'on' : ''}" data-act="ob-approval" data-v="batch">Once per batch</button><button type="button" class="${ed.approval === 'none' ? 'on' : ''}" data-act="ob-approval" data-v="none">Don't ask me</button></div></section>
      ${S.data.employees.length ? `<section class="wide"><h3>${icon('users')} Works with</h3>
        <div class="chips">${S.data.employees.map((x) => `<button type="button" class="chip ${(ed.with || []).includes(x.id) ? 'on' : ''}" data-act="ob-with" data-id="${x.id}" aria-pressed="${(ed.with || []).includes(x.id)}">${esc(x.name)} <span class="faint">${esc(x.role)}</span></button>`).join('')}</div>
        <p class="meta">Everyone on the crew can always ask anyone. These become part of the job: who hands what to whom.</p></section>` : ''}
      ${(ob.conn || []).length ? `<section class="wide"><h3>${icon('grid')} Connectors</h3><div class="chips">${ob.conn.map((x) => `<button type="button" class="chip ${(ed.connectors || []).includes(x.id) ? 'on' : ''}" data-act="ob-conn" data-id="${x.id}" aria-pressed="${(ed.connectors || []).includes(x.id)}" title="${esc(x.what)}">${esc(x.name)}</button>`).join('')}</div>
        <p class="meta">Apps ${esc(name || 'they')} can work in. The first time, you sign in to each in a Claude session with them. More in Manage, any time.</p></section>` : ''}
      <section class="wide grant"><h3>${icon('claude')} How independent?</h3>
        <div class="seg budget" role="group" aria-label="Independence"><button type="button" class="${ed.autonomy ? '' : 'on'}" data-act="ob-autonomy" data-v=""><b>Checks in with me</b><span>Asks before anything new or public</span></button><button type="button" class="${ed.autonomy ? 'on' : ''}" data-act="ob-autonomy" data-v="1"><b>Full autonomy</b><span>Does the whole job, finds its own tools, in its own browser window</span></button></div></section>
      <p class="meta card-cloud">${icon('claude')} If this ${MAC()} is closed or offline, they keep working in Anthropic's cloud, on your Claude plan. Turn it off any time in their Manage tab.</p>
      <section><h3>Tools</h3>${access}</section>
      <section><h3>Routines</h3><div class="chips">${routines}</div><p class="meta">Reports land in the team room and on your phone.</p></section>
      <section class="wide"><h3>Weekly budget on your Claude plan</h3><div class="seg budget" role="group" aria-label="Weekly budget">${budget}</div>
        <p class="meta">When it's used up, routines wait and ${esc(name)} still answers you. Crew members also slow down when your plan's weekly limit runs high.</p></section>
    </div>
    <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit" data-hire-label>${icon('plus')}Launch ${esc(name || 'them')}</button>
      <button type="button" class="btn btn-ghost" data-act="ob-back">Change answers</button></div>
  </form>`;
}

function keepTyped() {                // the interview's typed answers survive a re-render
  const f = $('.interview'); if (!f || !S.ob) return;
  for (const el of f.querySelectorAll('input[name]')) S.ob.answers[el.name.endsWith('__other') ? el.name : el.name] = el.value;
}
function keepCard() {
  const f = $('.idcard, .cardstep'); if (!f || !S.ob || !S.ob.edit) return;
  if (f.elements.role) S.ob.edit.role = f.elements.role.value;
  if (f.elements.scope) S.ob.edit.scope = f.elements.scope.value;
}
async function openClaude(emp, btn, quiet) {            // → true when their chat opened (or its command was handed over)
  const label = btn ? btn.innerHTML : '';
  const e = (S.data.employees || []).find((x) => x.id === emp) || { name: emp };
  let ok = false;
  if (btn) { btn.disabled = true; btn.textContent = 'Opening Claude…'; }
  try {
    const r = await api('/api/claude_session', { employee: emp });
    S.claudeCmd = { ...(S.claudeCmd || {}), [emp]: r.command };
    const busy = r.busy ? ` ${esc(e.name)} is in the middle of ${esc(r.busy)}; the window opens when it's done.` : '';
    if (r.opened && r.how === 'app' && r.new_chat) toast(`Claude is opening a new chat with ${esc(e.name)}. Press Enter once: they set up their routines there, so every report lands in that chat.`);
    else if (r.opened && r.how === 'app') { if (!quiet) toast(`Opening your chat with ${esc(e.name)} in Claude.`); }
    else if (r.opened) toast(`A terminal is opening on ${esc(e.name)}'s conversation.${busy}`);
    else {
      try { await navigator.clipboard.writeText(r.command); } catch (_) { /* no clipboard */ }
      toast(`Run this in a terminal (copied): ${r.command}`);
    }
    ok = true;
  } catch (e2) { toast(e2.message, 'err'); }
  if (btn) { btn.disabled = false; btn.innerHTML = label; }
  return ok;
}
let seenAt = 0;
function markSeen() {                 // the owner is looking at what the crew said: nothing is unread now
  if (S.data && S.data.demo) return;
  const now = Date.now();
  if (now - seenAt < 30000 || !(S.data && S.data.unread)) return;
  seenAt = now;
  api('/api/seen', {}).then(() => { if (S.data) S.data.unread = 0; renderSide(route()); }).catch(() => {});
}
// The moment after a hire: what's ready, and Claude opening on the new crew member
function syncLaunch(r) {             // the welcome after a hire: shown once, then Claude opens on the new crew member
  let el = document.getElementById('launch-layer');
  const e = S.launched && S.data.employees.find((x) => x.id === S.launched);
  if (!e || r.page !== 'employee' || r.id !== e.id) { if (el) el.remove(); return; }
  if (el) return;
  el = document.createElement('div'); el.id = 'launch-layer'; el.innerHTML = launchHtml(e); document.body.appendChild(el);
  if (!S.data.demo && S.autoOpened !== e.id) {
    S.autoOpened = e.id;
    setTimeout(() => { const b = el.querySelector('[data-act=open-claude]'); if (b && document.body.contains(el)) openClaude(e.id, b); }, 2800);
  }
}
function launchHtml(e) {
  const st = S.data.setup || {};
  const steps = [['Card and memory set up', 'Their job, plan and your answers are in their notes'], ['Safety locks on', 'The guard, in every run and every Claude session'],
    ['First task started', 'Watch it below; it takes a minute or two'], [`${esc(e.name)} is ready in Claude`, 'A session in their folder, with everything above']];
  return `<div class="launch" role="dialog" aria-modal="true" aria-label="${esc(e.name)} joined your crew"><div class="launch-card">
    <div class="launch-orbit" aria-hidden="true"><span class="ring r1"></span><span class="ring r2"></span><span class="sat s1"></span><span class="sat s2"></span>${avatar(e.id, e.name, 'xl')}</div>
    <p class="launch-kicker">Welcome aboard</p><h2>${esc(e.name)} joined your crew</h2><p class="launch-role">${esc(e.role)}</p>
    <ol class="launch-steps">${steps.map(([t, d], i) => `<li>${icon('check')}<div><b>${t}</b><span>${d}</span></div></li>`).join('')}</ol>
    <div class="launch-actions">
      <button class="btn btn-primary btn-lg" data-act="open-claude" data-emp="${e.id}" title="${esc(e.name)}'s own conversation in a Claude window">${icon('claude')}Talk to ${esc(e.name)} in Claude</button>
      ${st.paired ? '' : `<a class="btn btn-lg" href="/connect">${icon('phone')}Put ${esc(e.name)} on your phone</a>`}
    </div>
    <p class="meta">Claude is where ${esc(e.name)} does the work, with all of Claude's power. Orbit adds the job, the memory, the routines and the locks. Their reports reach you here, on your phone once connected, and as notifications on this computer.</p>
    <button class="btn btn-ghost btn-sm launch-close" data-act="close-launch">Watch their first task</button>
  </div></div>`;
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
    <div class="save-bar"><button class="btn btn-primary btn-lg" type="submit">Connect</button><span class="meta">The token stays on this ${MAC()}, in your team's private folder. It never goes through a chat.</span></div></form>`;
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
// ---------------------------------------------------------------- mission control: shared pieces
// Crew members write three small records (results, asks, objectives: core/tools/record.py); these screens show them.
const KIND_ICON = { short: 'film', video: 'film', post: 'send', report: 'doc', file: 'file', other: 'link' };
const NEED_ICON = { approval: 'check', decision: 'target', blocked: 'lock', owner: 'user', failed: 'alert', paused: 'pause', waiting: 'clock', reminder: 'bell', usage: 'gauge', plan: 'target', asleep: 'alert' };
const isUrl = (x) => /^https?:\/\//i.test(String(x || ''));
function empById(id) { return S.data.employees.find((e) => e.id === id); }

// One status per crew member, shown everywhere as a word plus a mark, never colour alone.
function crewStatus(e) {
  const d = S.data;
  if (e.status === 'paused') return { k: 'paused', word: 'Paused' };
  if (e.failures_today) return { k: 'failing', word: 'Failing' };
  if ((d.needs || []).some((n) => n.emp === e.id && n.kind !== 'paused' && n.kind !== 'failed')) return { k: 'needs', word: 'Needs you' };
  if (callOf(e.id) || (d.live || {})[e.id] || e.doing) return { k: 'working', word: 'Working' };
  return { k: 'idle', word: 'Idle' };
}
const STATUS_DOT = { working: 'working', needs: 'warn', failing: 'off', paused: 'paused', idle: '' };
function statusPill(e) { const st = crewStatus(e); return `<span class="status"><i class="dot ${STATUS_DOT[st.k]}"></i>${st.word}</span>`; }

function resultTile(r, e, timeOnly) {
  const kind = KIND_ICON[r.kind] ? r.kind : 'other';
  const w = String(r.where || ''), t = parseTs(r.ts);
  const when = t ? (timeOnly ? hm(t) : fmtTime(r.ts)) : '';
  const inner = `<span class="rk" aria-hidden="true">${icon(KIND_ICON[kind])}</span><span class="rtitle"><span class="sr">${esc(kind)}: </span>${esc(r.title)}</span><span class="meta">${esc(e.name)} · ${esc(when)}</span>`;
  if (isUrl(w)) return `<a class="rtile" href="${esc(w)}" target="_blank" rel="noopener noreferrer">${inner}</a>`;
  if (w && !w.startsWith('/') && !w.split('/').includes('..')) return `<a class="rtile" href="/e/${esc(e.id)}/work?v=files&f=${encodeURIComponent(w)}">${inner}</a>`;
  return `<div class="rtile">${inner}</div>`;
}
function krProgress(k) { const t = Number(k.target) || 0, c = Number(k.current) || 0; return t > 0 ? Math.max(0, Math.min(1, c / t)) : 0; }
function objPct(o) { const ks = o.key_results || []; return ks.length ? Math.round(ks.reduce((a, k) => a + krProgress(k), 0) / ks.length * 100) : 0; }
function fmtKR(k) {
  const n = (x) => (Number(x) || 0).toLocaleString();
  return k.unit === '%' ? `${n(k.current)}% / ${n(k.target)}%` : `${n(k.current)} / ${n(k.target)}${k.unit ? ' ' + esc(k.unit) : ''}`;
}
function dueLabel(due) { const d = parseDay(due); return d ? 'Due ' + d.toLocaleDateString([], { day: 'numeric', month: 'short' }) : ''; }
function meterHtml(pct, label) { return `<div class="meter" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i data-w="${pct}"></i></div>`; }

// ---------------------------------------------------------------- Home
// The orbit: you in the middle, the crew on two ellipses. Geometry differs on a phone so the text stays readable.
function orbitGeo() {
  return window.matchMedia('(max-width: 640px)').matches
    ? { w: 340, h: 336, cx: 170, cy: 150, irx: 88, iry: 66, orx: 140, ory: 124, r: 21 }
    : { w: 520, h: 372, cx: 260, cy: 168, irx: 128, iry: 76, orx: 222, ory: 142, r: 24 };
}
function initials(name) { const w = String(name || '?').trim().split(/\s+/); return (w.length > 1 ? w[0][0] + w[1][0] : w[0].slice(0, 1)).toUpperCase(); }
function orbitSvg(d) {
  const g = orbitGeo(), emps = d.employees, inner = emps.slice(0, 4), outer = emps.slice(4);
  const INNER = { 1: [180], 2: [180, 0], 3: [210, 330, 90], 4: [225, 315, 45, 135] };      // degrees, clear of the label under "You"
  const at = (rx, ry, deg) => [g.cx + rx * Math.cos(deg * Math.PI / 180), g.cy + ry * Math.sin(deg * Math.PI / 180)];
  const f = (n) => n.toFixed(1);
  const crew = (e, [x, y]) => {
    const st = crewStatus(e), nm = e.name.length > 9 ? e.name.slice(0, 8) + '…' : e.name;
    return `<a class="orb-node" href="/e/${esc(e.id)}" aria-label="${esc(e.name)}: ${st.word}">
      <circle class="orb-halo" cx="${f(x)}" cy="${f(y)}" r="${g.r + 9}"/><circle class="orb-fill hue-${hue(e.id)}" cx="${f(x)}" cy="${f(y)}" r="${g.r}"/>
      <circle class="orb-st ${st.k}" cx="${f(x)}" cy="${f(y)}" r="${g.r + 4}"/><text class="orb-init" x="${f(x)}" y="${f(y + 5)}" text-anchor="middle">${esc(initials(e.name))}</text>
      <text class="orb-name" x="${f(x)}" y="${f(y + g.r + 18)}" text-anchor="middle">${esc(nm)}</text><text class="orb-word ${st.k}" x="${f(x)}" y="${f(y + g.r + 32)}" text-anchor="middle">${st.word}</text></a>`;
  };
  const slots = outer.length + 1, ang = (i) => 20 + 360 * i / slots;
  const [hx, hy] = at(g.orx, g.ory, ang(outer.length));
  const hire = `<a class="orb-node orb-hire" href="/hire" aria-label="Hire someone"><circle class="orb-halo" cx="${f(hx)}" cy="${f(hy)}" r="${g.r + 9}"/>
    <circle class="orb-slot" cx="${f(hx)}" cy="${f(hy)}" r="${g.r}"/><path class="orb-plus" d="M${f(hx - 7)} ${f(hy)}h14M${f(hx)} ${f(hy - 7)}v14"/>
    <text class="orb-name" x="${f(hx)}" y="${f(hy + g.r + 18)}" text-anchor="middle">Hire</text></a>`;
  const pts = [...inner.map((e, i) => at(g.irx, g.iry, INNER[inner.length][i])), ...outer.map((e, i) => at(g.orx, g.ory, ang(i))), [hx, hy]];
  const x0 = Math.min(g.cx - g.orx, ...pts.map((p) => p[0] - 38)) - 4, x1 = Math.max(g.cx + g.orx, ...pts.map((p) => p[0] + 38)) + 4;
  const y0 = Math.min(g.cy - g.ory, ...pts.map((p) => p[1] - g.r - 6)) - 4, y1 = Math.max(g.cy + g.ory, ...pts.map((p) => p[1] + g.r + 38)) + 4;
  return `<svg class="orbit" viewBox="${f(x0)} ${f(y0)} ${f(x1 - x0)} ${f(y1 - y0)}" role="group" aria-label="Your crew in orbit around you">
    <ellipse class="orb-ring" cx="${g.cx}" cy="${g.cy}" rx="${g.irx}" ry="${g.iry}"/><ellipse class="orb-ring dashed" cx="${g.cx}" cy="${g.cy}" rx="${g.orx}" ry="${g.ory}"/>
    <circle class="orb-you" cx="${g.cx}" cy="${g.cy}" r="30"/><text class="orb-init" x="${g.cx}" y="${g.cy + 5}" text-anchor="middle">You</text>
    ${inner.map((e, i) => crew(e, at(g.irx, g.iry, INNER[inner.length][i]))).join('')}
    ${outer.map((e, i) => crew(e, at(g.orx, g.ory, ang(i)))).join('')}${hire}</svg>`;
}

function needCard(n) {
  const e = n.emp ? empById(n.emp) : null, name = e ? e.name : '';
  const ic = icon(NEED_ICON[n.kind === 'ask' ? n.ask_kind : n.kind] || 'alert');
  if (n.kind !== 'ask') {
    return `<li class="ncard"><span class="nk">${ic}</span><div class="nmain"><div class="ntitle" title="${esc(n.title)}">${esc(n.title)}</div><div class="meta one">${esc(n.detail || name)}</div></div>
      <div class="nbtns"><a class="btn btn-sm" href="${esc(n.href || '/')}">Open</a></div></li>`;
  }
  const ans = (o, i) => `<button type="button" class="btn btn-sm${i === 0 ? ' btn-primary' : ''}" data-act="ask-answer" data-emp="${esc(n.emp)}" data-id="${esc(n.id)}" data-answer="${esc(o)}">${esc(o)}</button>`;
  const chat = `<button type="button" class="btn btn-sm" data-act="open-claude" data-emp="${esc(n.emp)}">Open chat</button>`;
  const opts = (n.options || []).length ? n.options : n.ask_kind === 'approval' ? ['Approve', 'Not now'] : [];
  const btns = n.ask_kind === 'blocked' ? chat + ans('Done', 1) : opts.length ? opts.map(ans).join('') : chat;
  return `<li class="ncard"><span class="nk">${ic}</span><div class="nmain"><div class="ntitle" title="${esc(n.title)}">${esc(n.title)}</div><div class="meta one">${esc(name)} · ${esc(n.ask_kind)}</div></div><div class="nbtns">${btns}</div></li>`;
}
function needsHtml(d) {
  const all = (d.needs || []).filter((n) => !(n.kind === 'ask' && S.gone.has(n.id)));
  const shown = S.needsAll ? all : all.slice(0, 3);
  return `<div class="sec-head"><h2>Needs you</h2><span class="meta num">${all.length}</span></div>` + (all.length
    ? `<ul class="ncards">${shown.map(needCard).join('')}</ul>${all.length > 3 ? `<button type="button" class="btn btn-ghost btn-sm seeall" data-act="needs-all" aria-expanded="${S.needsAll}">${S.needsAll ? 'Show fewer' : `See all (${all.length})`}</button>` : ''}`
    : `<div class="nothing">${icon('check')}<span>Nothing needs you right now.</span></div>`);
}

function weekStats(d) {
  const w = d.week || {}, b = d.week_before || null;
  return [['shipped', 'Shipped'], ['needed_you', 'Needed you'], ['blocked', 'Blocked'], ['plan_used', 'Plan used']].map(([k, label]) => {
    const v = w[k];
    let delta = k === 'plan_used' ? 'of the weekly limit' : '';
    if (k !== 'plan_used' && b && b[k] != null && v != null) {
      const diff = v - b[k];
      delta = diff > 0 ? `<span class="sr">Up </span><span aria-hidden="true">▲</span> ${diff} vs last week` : diff < 0 ? `<span class="sr">Down </span><span aria-hidden="true">▼</span> ${-diff} vs last week` : 'Same as last week';
    }
    return `<div class="stat"><div class="n num">${v == null ? '—' : k === 'plan_used' ? v + '%' : v}</div><div class="l">${label}</div><div class="meta d">${delta}</div></div>`;
  }).join('');
}
function todayResults(d) {
  const now = new Date(), out = [];
  for (const e of d.employees) for (const r of e.results_7d || []) { const t = parseTs(r.ts); if (t && sameDay(t, now)) out.push({ r, e, t }); }
  return out.sort((a, b) => b.t - a.t);
}
PAGES.today = () => {
  const d = S.data, today = todayResults(d);
  const calls = Object.keys(d.calls || {}).map((id) => callCard(id, true)).join('');
  const strip = today.length ? `<div class="strip" tabindex="0" role="region" aria-label="Results shipped today">${today.map(({ r, e }) => resultTile(r, e, true)).join('')}</div>`
    : `<p class="quiet">Nothing shipped yet today.</p>`;
  return `<h1 class="sr">Home</h1>${updateHtml(d)}${setupHtml(d)}${calls ? `<section>${calls}</section>` : ''}
    <div class="home-top"><div class="orbit-sec"><div class="sec-head"><h2>Crew</h2></div>${orbitSvg(d)}</div><div class="needs-sec">${needsHtml(d)}</div></div>
    <section><div class="sec-head"><h2>This week</h2></div><div class="week">${weekStats(d)}</div></section>
    <section><div class="sec-head"><h2>Today</h2></div>${strip}</section>`;
};

// ---------------------------------------------------------------- Objectives
function parseDay(s) { const m = String(s || '').match(/^(\d{4})-(\d\d)-(\d\d)/); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; }
function krRows(o) {
  return (o.key_results || []).length ? o.key_results.map((k) => `<div class="kr"><span class="kn">${esc(k.name)}</span>${meterHtml(Math.round(krProgress(k) * 100), k.name)}<span class="kv num">${fmtKR(k)}</span></div>`).join('')
    : '<p class="quiet">No key results yet.</p>';
}
// Behind = overall progress is below the share of time elapsed between the objective's start (when it was created; else 30 days before due) and its due date.
function objStatus(o) {
  const DAY = 864e5, now = new Date(), today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const due = parseDay(o.due) || today, start = parseDay(o.created) || new Date(due.getTime() - 30 * DAY);
  const pct = objPct(o), share = Math.max(0, Math.min(1, (today - start) / Math.max(DAY, due - start))), left = Math.round((due - today) / DAY);
  return { pct, left, behind: pct < 100 && pct / 100 < share, overdue: left < 0 && pct < 100 };
}
function leftLabel(st) { return st.overdue ? '' : st.left < 0 ? 'Past its due date' : st.left === 0 ? 'Due today' : st.left === 1 ? '1 day left' : `${st.left} days left`; }
function objBlock(o) {
  const st = objStatus(o);
  const word = st.behind ? `<span class="badge warn">${icon('alert')}Behind</span>` : `<span class="badge accent">${icon('check')}On track</span>`;
  return `<div class="obj"><div class="obj-head"><span class="obj-title">${esc(o.title)}</span><span class="meta">${esc(dueLabel(o.due))}${leftLabel(st) ? ' · ' + leftLabel(st) : ''}${st.overdue ? ` · <span class="over">${icon('alert')}Overdue</span>` : ''}</span></div>
    <div class="obj-prog">${word}${meterHtml(st.pct, o.title)}<span class="num">${st.pct}%</span></div>${krRows(o)}</div>`;
}
PAGES.objectives = () => {
  const emps = S.data.employees;
  const rows = emps.map((e) => ({ e, objs: (e.objectives || []).slice().sort((a, b) => String(a.due).localeCompare(String(b.due))) }));
  const have = rows.filter((x) => x.objs.length).sort((a, b) => String(a.objs[0].due).localeCompare(String(b.objs[0].due)));
  const none = rows.filter((x) => !x.objs.length);
  const all = have.flatMap((x) => x.objs.map(objStatus)), behind = all.filter((s) => s.behind).length;
  const summary = all.length ? `${plural(all.length, 'objective')} · ${all.length - behind} on track · ${behind} behind` : 'No objectives yet';
  const secs = have.map(({ e, objs }) => `<section class="obj-sec"><a class="who-link" href="/e/${esc(e.id)}">${avatar(e.id, e.name)}<h2>${esc(e.name)}</h2><span class="meta">${esc(e.role)}</span></a>${objs.map(objBlock).join('')}</section>`).join('');
  const quiet = none.map(({ e }) => `<div class="obj-none">${avatar(e.id, e.name, 'sm')}<span>${esc(e.name)} has no objective yet</span>
    <button type="button" class="btn btn-sm" data-act="try-ask" data-emp="${esc(e.id)}" data-text="Propose your objective for this month with three key results, using staff-record.">Ask ${esc(e.name)} to propose one</button></div>`).join('');
  return `<header class="page-head"><div><h1>Objectives</h1><p class="sub">${summary}</p></div></header>
    ${emps.length ? secs + (quiet ? `<section class="obj-sec">${quiet}</section>` : '') : `<div class="empty"><b>No crew yet.</b><p><a class="link" href="/hire">Hire someone</a> and set their first objective.</p></div>`}`;
};

// ---------------------------------------------------------------- Metrics
const M_DEFS = [['shipped', 'Shipped'], ['needed_you', 'Needed you'], ['blocked', 'Blocked'], ['failed_runs', 'Failed runs']];
const shortDay = (iso) => { const d = parseDay(iso); return d ? d.toLocaleDateString([], { day: 'numeric', month: 'short' }) : ''; };
function changeWords(series) { const d = series[series.length - 1] - series[series.length - 2]; return d > 0 ? `up ${d}` : d < 0 ? `down ${-d}` : 'no change'; }
function columnChart(label, series, weeks) {
  const W = 400, H = 130, L = 10, base = 104, top = 22, slot = (W - 2 * L) / series.length, bw = 30, max = Math.max(1, ...series);
  const now = series.length - 1, sentence = `${label} per week, from ${shortDay(weeks[0])} to this week: ${series.join(', ')}.`;
  const bars = series.map((v, i) => { const h = Math.max(1.5, (v / max) * (base - top)), x = L + i * slot + (slot - bw) / 2;
    return `<rect class="bar${i === now ? ' now' : ''}" x="${x.toFixed(1)}" y="${(base - h).toFixed(1)}" width="${bw}" height="${h.toFixed(1)}" rx="2"/>`; }).join('');
  const hNow = Math.max(1.5, (series[now] / max) * (base - top));
  return `<svg class="mchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sentence)}"><title>${esc(sentence)}</title>${bars}<line class="axis" x1="${L}" y1="${base}" x2="${W - L}" y2="${base}"/>
    <text class="val" x="${(L + now * slot + slot / 2).toFixed(1)}" y="${(base - hNow - 6).toFixed(1)}" text-anchor="middle">${series[now]}</text>
    <text class="xl" x="${L}" y="${H - 6}" text-anchor="start">${esc(shortDay(weeks[0]))}</text><text class="xl" x="${W - L}" y="${H - 6}" text-anchor="end">${esc(shortDay(weeks[now]))}</text></svg>`;
}
function sparkline(label, series) {
  const max = Math.max(1, ...series), pts = series.map((v, i) => [2 + i * (76 / (series.length - 1)), 18 - (v / max) * 16]);
  const last = pts[pts.length - 1], s = `${label}, last ${series.length} weeks: ${series.join(', ')}.`;
  return `<svg class="spark" viewBox="0 0 80 20" role="img" aria-label="${esc(s)}"><title>${esc(s)}</title><polyline points="${pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ')}"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.6"/></svg>`;
}
PAGES.metrics = () => {
  const M = S.metrics;
  if (!M) return loading;
  const crew = M.crew, u = M.usage || {};
  const charts = M_DEFS.map(([k, label]) => `<div class="mc"><h3>${label} · ${crew[k][crew[k].length - 1]} this week, ${changeWords(crew[k])}</h3>${columnChart(label, crew[k], M.weeks)}</div>`).join('');
  const meters = [['seven_day', '7-day plan use'], ['five_hour', '5-hour plan use']].filter(([k]) => k in u).map(([k, l]) => `<div class="pu"><span>${l}</span>${meterHtml(Math.round(u[k]), l)}<span class="num">${Math.round(u[k])}%</span></div>`).join('');
  const plan = `<section><div class="sec-head"><h2>Plan use</h2></div>${meters || '<p class="quiet">No reading yet.</p>'}
    <p class="meta">Shown as what it would cost on the API; nothing is billed. ${money(M.api_equivalent_usd)} over the last 8 weeks.</p></section>`;
  const members = M.members.length ? M.members.map((m) => `<div class="mrow"><div class="mwho">${avatar(m.id, m.name, 'sm')}<a href="/e/${esc(m.id)}">${esc(m.name)}</a></div>
      <div class="msp">${M_DEFS.map(([k, l]) => `<div class="sp"><span class="meta">${l}</span><span class="sp-line">${sparkline(l, m[k])}<b class="num">${m[k][m[k].length - 1]}</b></span></div>`).join('')}</div></div>`).join('')
    : '<p class="quiet">No crew yet.</p>';
  return `<header class="page-head"><div><h1>Metrics</h1><p class="sub">The last 8 weeks, weeks start on Monday.</p></div><div class="actions"><button type="button" class="btn" data-act="metrics-refresh">Refresh</button></div></header>
    <div class="mgrid">${charts}</div>${plan}<section><div class="sec-head"><h2>By crew member</h2></div>${members}</section>`;
};

function setupHtml(d) {            // what's left to set up: the first-run flow, shown on Home until it's done
  const todo = d.checklist.filter((c) => !c.done && !c.optional);
  return todo.length ? `<div class="setup"><h2>Finish setting up</h2><ol>${d.checklist.filter((c) => !c.done).map((c) => `
    <li>${icon('circle')}<div><span>${esc(c.title)}${c.optional ? ' <span class="meta">optional</span>' : ''}</span><div class="how">${esc(c.how)}</div></div>${c.href ? `<a class="btn btn-sm ${c.optional ? '' : 'btn-primary'}" href="${esc(c.href)}">${esc(c.cta)}</a>` : '<span></span>'}</li>`).join('')}</ol></div>` : '';
}
function updateHtml(d) {           // "a new Orbit is available"
  const up = d.update || {};
  return up.newer && !up.dismissed ? `<section class="update"><div><b>Orbit ${esc(up.latest)} is available</b> <span class="meta">you have ${esc(up.current)}</span>
    ${up.notes ? `<div class="md small update-notes">${md(up.notes.split('\n').slice(0, 12).join('\n'))}</div>` : ''}
    ${up.can_update ? '' : `<p class="meta">${esc(up.why_not)}</p>`}</div>
    <div class="actions">${up.can_update ? `<button class="btn btn-primary btn-sm" data-act="update-now">Update now</button>` : ''}<button class="btn btn-ghost btn-sm" data-act="update-later">Later</button>${up.url ? `<a class="link small" href="${esc(up.url)}" target="_blank" rel="noopener">Release notes</a>` : ''}</div></section>` : '';
}
// ---- the team room (the old Today page, kept reachable at /room)
PAGES.room = () => {
  const d = S.data, emps = d.employees, h = new Date().getHours();
  const greet = h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const live = Object.keys(d.live || {}).map((id) => emps.find((e) => e.id === id)).filter(Boolean);
  const date = new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' });
  let sub = date;
  if (!emps.length) sub += ' · no employees yet';
  else sub += ` · ${plural(emps.length, 'crew member')} · ${Object.keys(d.calls || {}).length ? 'on a call · ' : ''}${live.length ? live.length + ' working' : 'all idle'}`;
  if (!d.online) sub += ' · <span class="badge danger">service stopped</span>';
  const demo = d.demo ? `<div class="demo-bar"><b>A pretend team, to look around.</b> The business, the people and their findings are invented (links end in .example) and the replies are canned: no Claude run, no bot. Chat with someone anyway, teach a skill, change abilities. Your own team: run <code>orbit setup</code>, or paste the one line from the README into the Claude app.</div>` : '';
  const setup = setupHtml(d);
  const nowSec = live.length ? `<section><div class="sec-head"><h2>Working now</h2></div><div class="list now-list">${live.map((e) => {
    const L = d.live[e.id];
    return `<a class="row" href="/e/${e.id}">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)} <span class="meta">${esc(L.doing || '')}</span></div><div class="now-step"><i class="dot working"></i>${esc(lastStep(e.id))}</div></div><span class="meta num" data-since="${esc(L.started)}"></span></a>`;
  }).join('')}</div></section>` : '';
  const kinds = { owner: 'user', failed: 'alert', paused: 'pause', waiting: 'clock', reminder: 'bell', usage: 'gauge', plan: 'target', asleep: 'alert' };
  const plans = emps.length ? `<section><div class="sec-head"><h2>Plans</h2><span class="meta">what each one is working toward</span></div><div class="list plans">${emps.map((e) => {
    const p = e.plan || {}, st = p.status || 'none';
    const badge = st === 'agreed' ? '<span class="badge accent">agreed</span>' : st === 'proposed' ? '<span class="badge warn">needs your OK</span>' : '<span class="badge">no plan yet</span>';
    return `<a class="row plan-row" href="/e/${e.id}/plan">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)} ${badge}</div>
      <div class="meta">${st === 'none' ? 'Proposes one at the next standup' : esc(p.goal || '')}</div>${p.next ? `<div class="meta">Next: ${esc(p.next.what)} · by ${esc(p.next.by)}</div>` : ''}</div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`;
  }).join('')}</div></section>` : '';
  const needs = d.needs.length ? `<div class="list needs">${d.needs.map((n) => `
    <a class="row ${n.kind}" href="${esc(n.href)}"><span class="k">${icon(kinds[n.kind] || 'alert')}</span><div><div class="title">${esc(n.title)}</div><div class="meta">${esc(n.detail)}</div></div>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`).join('')}</div>`
    : `<p class="quiet">Nothing needs you right now.</p>`;
  const now = new Date();
  let feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && sameDay(t, now); });
  if (feed.length < 4) { const y = new Date(now); y.setDate(now.getDate() - 1); feed = sortedByTs(d.feed).filter((f) => { const t = parseTs(f.ts); return t && (sameDay(t, now) || sameDay(t, y)); }); }
  const timeline = feed.length ? `<div class="timeline">${withDays(feed.slice(-40), tlItem, true)}</div>`
    : `<div class="empty"><b>Quiet so far.</b><p>${emps.length ? 'What your team says to you and to each other shows up here.' : 'Add your first crew member and their missions show up here.'}</p></div>`;
  const mini = emps.length ? `<div class="list mini">${emps.map((e) => `<a class="row" href="/e/${e.id}">${avatar(e.id, e.name)}<div><div class="title">${esc(e.name)}</div><div class="meta">${esc(empNow(e))}</div></div>${statusHtml(e)}</a>`).join('')}</div>`
    : `<p class="quiet">No crew yet. <a class="link" href="/hire">Add your first</a>.</p>`;
  const useToday = emps.reduce((a, e) => a + (e.tokens_today || 0), 0), use7 = emps.reduce((a, e) => a + (e.tokens_7d || 0), 0);
  const u = d.usage || {};
  const usage = `<div class="usage-box"><div class="row2"><span>Crew today</span><b class="num">${fmtTok(useToday)} tokens</b></div><div class="row2"><span>Last 7 days</span><b class="num">${fmtTok(use7)} tokens</b></div>
    ${['five_hour', 'seven_day'].filter((k) => k in u).map((k) => `<div class="row2"><span>${k === 'five_hour' ? '5-hour limit' : 'Weekly limit'}</span><b class="num">${Math.round(u[k])}% used</b></div>`).join('')}
    <p class="meta">Your crew runs on your Claude plan: nothing extra is billed. The limits are your plan's (shared with your own Claude use); each crew member also has a weekly budget.</p></div>`;
  const calls = Object.keys(d.calls || {}).map((id) => callCard(id, true)).join('');
  const upd = updateHtml(d);
  return `${demo}${upd}<header class="greet"><h1>${greet}, ${esc(d.me)}.</h1><p class="sub">${sub}</p></header>${setup}
    <div class="cols"><div>${calls ? `<section>${calls}</section>` : ''}${nowSec}
      <section><div class="sec-head"><h2>Needs you</h2>${d.needs.length ? `<span class="meta">${d.needs.length}</span>` : ''}</div>${needs}</section>
      ${plans}
      <section><div class="sec-head"><h2>Today</h2><span class="meta">the team room</span></div>${timeline}</section>
    </div><aside>
      <section><div class="sec-head"><h2>Crew</h2><a class="link small" href="/team">All</a></div>${mini}</section>
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
// A crew member's health at a glance: this week's runs and failures, and tokens against their weekly budget
// "Posts for you": the owner's consent, per crew member, per site, from the crew member's own browser window.
function sitePicker(prefix, sites) {
  const on = new Set(sites);
  const extra = [...on].filter((d) => !SITES.some(([, x]) => x === d));
  return `<div class="chips">${SITES.map(([l, d]) => `<button type="button" class="chip ${on.has(d) ? 'on' : ''}" data-act="${prefix}-site" data-d="${d}" aria-pressed="${on.has(d)}">${esc(l)}</button>`).join('')}
    ${extra.map((d) => `<button type="button" class="chip on" data-act="${prefix}-site" data-d="${esc(d)}" aria-pressed="true">${esc(d)} ×</button>`).join('')}</div>
    <div class="row-form"><input class="input" data-site-input="${prefix}" placeholder="Another site, like etsy.com" maxlength="80"><button type="button" class="btn btn-sm" data-act="${prefix}-add">Add</button></div>`;
}
// Connectors (MCP servers): the apps a crew member works in. Granted here, by chat, or with a Yes in Claude.
function connectorsSection(e) {
  const c = (S.conn || {})[e.id];
  if (!c) { loadConnectors(e.id); return `<section><h2>${icon('grid')} Connectors</h2><p class="quiet">Loading…</p></section>`; }
  const row = (x, on) => `<li><div><b>${esc(x.name)}</b> <span class="meta">${esc(x.what || x.url || '')}${x.money ? ' · read-only on money' : ''}</span>${x.source && String(x.source).startsWith('registry') ? `<div class="meta warn-text">${esc(x.source)}</div>` : ''}</div>
    <button type="button" class="btn btn-sm ${on ? 'btn-ghost' : ''}" data-act="connector" data-emp="${e.id}" data-ref="${esc(on ? x.id : (x.source && String(x.source).startsWith('registry') ? x.url : x.id))}" data-name="${esc(x.name)}" data-off="${on ? 1 : ''}">${on ? 'Remove' : 'Add'}</button></li>`;
  return `<section class="connectors"><h2>${icon('grid')} Connectors</h2>
    <p class="desc">Apps ${esc(e.name)} works in directly: your Drive, inbox, CRM, design or analytics tools. The first time, open ${esc(e.name)} in Claude and sign in to the app when it asks; Orbit never sees that sign-in. ${esc(e.name)} also asks for one when it would help.</p>
    ${c.granted.length ? `<h3>Connected</h3><ul class="conn">${c.granted.map((x) => row(x, true)).join('')}</ul>` : ''}
    ${c.suggested.length ? `<h3>Suggested for this job</h3><ul class="conn">${c.suggested.map((x) => row(x, false)).join('')}</ul>` : ''}
    <form class="row-form" data-form="conn-search" data-emp="${e.id}"><input class="input" name="q" maxlength="80" placeholder="Search apps: invoices, newsletter, Figma…" value="${esc(c.q || '')}"><button class="btn btn-sm" type="submit">Search</button></form>
    ${c.results && c.results.length ? `<ul class="conn">${c.results.map((x) => row(x, false)).join('')}</ul>` : c.q ? '<p class="quiet small">Nothing found. Paste the app\'s MCP link below.</p>' : ''}
    <form class="row-form" data-form="conn-link" data-emp="${e.id}"><input class="input" name="url" type="url" placeholder="https://… an app's MCP link" pattern="https://.*"><input class="input" name="name" maxlength="40" placeholder="Name"><button class="btn btn-sm" type="submit">Add by link</button></form></section>`;
}
async function loadConnectors(emp, q = '') {
  if (S.connLoading === emp + q) return;
  S.connLoading = emp + q;
  try { S.conn = { ...(S.conn || {}), [emp]: { ...(await api(`/api/connectors?emp=${encodeURIComponent(emp)}&q=${encodeURIComponent(q)}`)), q } }; }
  catch (err) { S.conn = { ...(S.conn || {}), [emp]: { granted: [], suggested: [], results: [], q } }; }
  S.connLoading = ''; render(false);
}
// Laptop first; when this computer is closed or offline, they keep working on Anthropic's cloud, on the owner's plan.
function cloudSection(e) {
  const c = e.cloud || {};
  const state = c.on ? `<span class="badge accent">On</span>` : `<span class="badge">Off</span>`;
  const when = c.on && c.next_shift ? `<p class="meta">While this ${MAC()} is on, ${esc(e.name)} works here. If it's closed or offline, the next cloud shift starts ${esc(c.next_shift)}.${c.last_shift ? ` Last cloud shift: ${esc(c.last_shift)}.` : ''}${c.session ? ` <a class="link" href="${esc(c.session)}" target="_blank" rel="noopener">Open their cloud desk</a>` : ''}</p>` : '';
  return `<section class="grant"><h2>${icon('claude')} Cloud shift</h2>
    <p class="desc">${esc(e.name)} works on this ${MAC()} first. When it's closed or offline, they carry on in Anthropic's cloud, on your own Claude plan: research, plans, scripts and code, with a report to your phone. When this ${MAC()} is back, they bring that work home. The cloud has no access to their browser window or your accounts, so anything that needs them waits for this ${MAC()}. ${state}</p>
    ${when}${c.error ? `<p class="meta warn-text">${esc(c.error)}</p>` : ''}${c.why_not ? `<p class="meta warn-text">${esc(c.why_not)}</p>` : ''}
    <div class="save-bar"><button type="button" class="btn ${c.on ? '' : 'btn-primary'}" data-act="order" data-kind="set_cloud" data-emp="${e.id}" data-on="${c.on ? '' : '1'}" ${c.why_not ? 'disabled' : ''}>${c.on ? 'Turn off' : 'Turn on the cloud shift'}</button></div></section>`;
}
function autonomySection(e) {
  const on = (e.abilities || []).includes('full_autonomy');
  return `<section class="grant"><h2>${icon('claude')} Full autonomy</h2>
    <p class="desc">${esc(e.name)} does the whole job without asking: reaches any website in its own browser window, downloads and installs the tools it needs, studies videos, and finishes the work. It asks you only for decisions and things only you know. The guard keeps it away from your secrets, your own browser and money, and it never types passwords. ${on ? '<span class="badge accent">On</span>' : '<span class="badge">Off</span>'}</p>
    <div class="save-bar"><button type="button" class="btn ${on ? '' : 'btn-primary'}" data-act="order" data-kind="set_autonomy" data-emp="${e.id}" data-on="${on ? '' : '1'}">${on ? 'Turn off' : 'Turn on full autonomy'}</button></div></section>`;
}
function browserSection(e) {
  const b = e.browser || {};
  const st = S.browserEdit && S.browserEdit.id === e.id ? S.browserEdit : (S.browserEdit = { id: e.id, sites: [...(b.sites || [])], approval: b.approval || 'each' });
  const dirty = JSON.stringify(st.sites) !== JSON.stringify(b.sites || []) || st.approval !== (b.approval || 'each');
  return `<section class="grant"><h2>${icon('key')} Posts for you</h2>
    <p class="desc">${esc(e.name)} has <b>a browser window of its own</b>, apart from yours. On the sites you pick, it posts, uploads and fills in forms for you there. They show you each one first and do it after you say “approved”, unless you choose otherwise. They never sign in themselves, type a password, change account settings or touch money. ${b.sites && b.sites.length ? `<span class="badge accent">On · ${esc(b.sites.join(', '))}</span>` : '<span class="badge">Off</span>'}</p>
    <div>${sitePicker('br', st.sites)}
      <div class="seg mt" role="group" aria-label="Approval"><button type="button" class="${st.approval === 'each' ? 'on' : ''}" data-act="br-approval" data-v="each">Ask me for each one</button><button type="button" class="${st.approval === 'batch' ? 'on' : ''}" data-act="br-approval" data-v="batch">Once per batch</button><button type="button" class="${st.approval === 'none' ? 'on' : ''}" data-act="br-approval" data-v="none">Don't ask me</button></div>
      <div class="save-bar"><button type="button" class="btn btn-primary" data-act="br-save" data-emp="${e.id}" ${dirty ? '' : 'disabled'}>${!dirty ? (st.sites.length ? 'Allowed' : 'Off') : st.sites.length ? 'Allow on ' + plural(st.sites.length, 'site') : 'Turn off'}</button>
      <button type="button" class="btn btn-sm btn-ghost" data-act="open-browser" data-emp="${e.id}">Open ${esc(e.name)}'s browser</button>
      <span class="meta">Sign them in to these sites there once; they stay signed in. Your own Chrome is never theirs.</span></div></div></section>`;
}
function healthHtml(e) {
  const cap = e.weekly_tokens || 0, used = e.tokens_7d || 0, pct = cap ? Math.min(100, Math.round(used / cap * 100)) : 0;
  const runs = e.runs_7d ? `${plural(e.runs_7d, 'run')} this week` : 'No runs this week';
  const fails = e.failures_7d ? ` · <span class="badge danger">${e.failures_7d} failed</span>` : '';
  const meter = cap ? `<div class="meter thin ${pct >= 90 ? 'hot' : ''}" title="${fmtTok(used)} of ${fmtTok(cap)} tokens this week"><i data-w="${pct}"></i></div>` : '';
  return `${runs}${fails}<div>${fmtTok(used)}${cap ? ' of ' + fmtTok(cap) : ''} tokens</div>${meter}`;
}
// ---------------------------------------------------------------- Crew
PAGES.team = () => {
  const d = S.data, emps = d.employees;
  const working = emps.filter((e) => crewStatus(e).k === 'working').length;
  const card = (e) => {
    const o = (e.objectives || [])[0], asks = (e.asks_open || []).length;
    return `<a class="crew-card" href="/e/${esc(e.id)}">
      <div class="cc-head">${avatar(e.id, e.name)}<div class="cc-who"><div class="title">${esc(e.name)}</div><div class="meta one">${esc(e.role)}</div></div>${statusPill(e)}</div>
      ${o ? `<div class="cc-obj"><div class="cc-otitle">${esc(o.title)}</div><div class="cc-bar">${meterHtml(objPct(o), o.title)}<span class="num meta">${objPct(o)}%</span></div></div>` : `<div class="cc-obj meta">No objective yet</div>`}
      ${asks ? `<div class="cc-asks"><span class="badge warn">${plural(asks, 'ask')}</span></div>` : ''}</a>`;
  };
  return `<header class="page-head"><div><h1>Crew</h1><p class="sub">${emps.length ? `${plural(emps.length, 'crew member')}${working ? ` · ${working} working` : ''}` : 'Nobody works here yet.'}</p></div>
</header>
    <div class="crew-grid">${emps.map(card).join('')}<a class="crew-card crew-add" href="/hire">${icon('plus')}Hire someone</a></div>`;
};

// ---------------------------------------------------------------- Crew member
const ABILITY_SKIP = ['memory', 'safety', 'telegram', 'team_room'];            // plumbing: not something to ask for
const ROUTINES = ['brief', 'standup', 'initiative', 'eod', 'review', 'scout', 'evals'];
const ABILITY_ICON = { voice: 'mic', meetings: 'mic', files: 'file', documents: 'doc', reminders: 'bell', web: 'eye', fetch: 'link', browser: 'grid', apify: 'users', watchers: 'bell',
  own_browser: 'grid', full_autonomy: 'claude', act_in_browser: 'send', content: 'film', marketing: 'gauge', compute: 'gauge', build_tools: 'manage', learn: 'target' };
const TRY = {                                                                  // two plain asks per ability, for any business
  web: ['Find what our three biggest competitors changed on their sites this week', 'Find five recent articles about our industry and tell me which matter'],
  fetch: ['Read our closest competitor’s pricing page and list what each plan costs', 'Check our own site for broken links and tell me which to fix'],
  browser: ['Walk through a competitor’s checkout and tell me every step', 'Screenshot our pricing page and tell me what looks unclear'],
  apify: ['Pull a competitor’s last 20 posts and tell me which did best', 'Find the best-rated places near us on Maps and what customers complain about'],
  watchers: ['Watch our competitors’ pricing pages and tell me the day one changes', 'Tell me when a supplier’s terms page changes'],
  documents: ['Read the contract I send you and list the dates and the amounts', 'Turn a scanned receipt into a row I can paste in a spreadsheet'],
  voice: ['I will send a voice note: turn it into a to-do list', 'Transcribe my next voice note and answer what it asks'],
  files: ['Read the PDF I send you and give me the five lines that matter', 'Look at the photo I send you and tell me what is wrong with it'],
  reminders: ['Remind me every Monday at 9 to review last week’s numbers', 'On Friday, remind me to chase anyone who has not answered'],
  meetings: ['Take minutes of my next call and list who owes what by when', 'Turn my last recording into decisions and next steps'],
  own_browser: ['Open our admin dashboard in your own window and tell me what looks off', 'Check our listing on a review site and note any new reviews'],
  full_autonomy: ['Do this whole task start to finish and only ask me for decisions', 'Find the tools you need, install them and finish the job'],
  act_in_browser: ['Draft this week’s post, show me, and publish it once I approve', 'Fill in the supplier’s order form and show me before you send it'],
  content: ['Plan next week’s posts for our channels, one idea a day', 'Write three short video scripts about our best seller'],
  marketing: ['Suggest one small ad test for next week and what it would cost', 'Read last month’s ad numbers and tell me what to stop'],
  compute: ['Run the heavy analysis on my GitHub and tell me when it is done', 'Crunch last year’s export on my GitHub and summarise it'],
  build_tools: ['Build a small tool that checks competitor prices every day', 'Write a script that turns my weekly export into a clean summary'],
  learn: ['From now on, end every report with the one thing I should do next', 'Learn how I like my weekly summary and use it every time'],
};
const TRY_ANY = ['Tell me what you worked on this week and what you need from me', 'Propose three things you could do for us next week'];
const CHIP_ORDER = ['content', 'act_in_browser', 'marketing', 'web', 'fetch', 'documents', 'watchers', 'browser', 'meetings', 'reminders', 'voice', 'files', 'apify', 'own_browser', 'build_tools', 'learn', 'compute', 'full_autonomy'];
const CHIP_LABEL = { content: 'Content and channels', act_in_browser: 'Posts for you', marketing: 'Paid ads', web: 'Web research', fetch: 'Reads any page', documents: 'Reads documents', watchers: 'Watches pages',
  browser: 'Reads hard pages', meetings: 'Calls and minutes', reminders: 'Reminders', voice: 'Voice notes', files: 'Photos and files', apify: 'Social and maps data', own_browser: 'Own browser window',
  build_tools: 'Builds its own tools', learn: 'Learns skills', compute: 'Heavy jobs', full_autonomy: 'Works on its own' };
function visibleAbilities(e) { return (e.abilities || []).filter((id) => !ABILITY_SKIP.includes(id) && !ROUTINES.includes(id)); }
function tryList(e) {
  const out = [];
  for (const id of visibleAbilities(e)) for (const t of TRY[id] || []) if (!out.includes(t)) out.push(t);
  return out.length ? out : TRY_ANY;
}
async function askInClaude(emp, text, btn) {                // an open chat can't be pre-filled: copy the sentence, open the chat
  const e = empById(emp) || { name: 'them' };
  let copied = true;
  try { await navigator.clipboard.writeText(text); } catch (_) { copied = false; }
  if (await openClaude(emp, btn, true)) toast(copied ? `Copied. Paste it in ${e.name}’s chat.` : `Open ${e.name}’s chat and type: ${text}`);
}
function weekTimeline(e, dt) {
  const key = (x) => x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0');
  const runs = dt && dt.runs ? dt.runs : [], res = e.results_7d || [];
  const cols = [];
  for (let i = 6; i >= 0; i--) {
    const x = new Date(); x.setDate(x.getDate() - i);
    const k = key(x);
    const rs = runs.filter((r) => String(r.ts || '').slice(0, 10) === k).reverse();
    const dots = rs.slice(0, 12).map((r) => { const t = parseTs(r.ts), at = t ? hm(t) : '';
      return r.ok ? `<i class="rd" role="img" aria-label="Run at ${esc(at)}"></i>` : `<i class="rd fail" role="img" aria-label="Failed run at ${esc(at)}"></i>`; }).join('');
    const n = res.filter((r) => String(r.ts || '').slice(0, 10) === k).length;
    cols.push(`<li class="wd${i === 0 ? ' today' : ''}"><span class="wd-day">${i === 0 ? 'Today' : x.toLocaleDateString([], { weekday: 'short' })}</span>
      <span class="wd-dots">${dots}${rs.length > 12 ? `<span class="meta">+${rs.length - 12}</span>` : ''}</span><span class="wd-n num${n ? '' : ' none'}" aria-label="${plural(n, 'result')} shipped">${n}</span></li>`);
  }
  return `<ol class="week-tl" aria-label="The last seven days">${cols.join('')}</ol><p class="meta">Dots are runs, diamonds are failed runs. Numbers are results shipped.</p>`;
}
function tabOverview(e, dt, r) {
  const st = crewStatus(e), paused = e.status === 'paused', live = (S.data.live || {})[e.id];
  const status = `<span class="status"><i class="dot ${STATUS_DOT[st.k]}"></i><span class="one">${st.word}${st.k === 'working' && live ? ' · ' + esc(lastStep(e.id)) : ''}</span></span>`;
  const head = `<header class="emp-head">${avatar(e.id, e.name, 'lg')}<div class="id"><h1>${esc(e.name)}</h1><div class="sub"><span>${esc(e.role)}</span><span aria-hidden="true">·</span>${status}</div></div>
    <div class="actions"><button type="button" class="btn btn-primary" data-act="open-claude" data-emp="${e.id}">${icon('claude')}Open chat</button>
    <button type="button" class="btn" data-act="order" data-kind="${paused ? 'resume' : 'pause'}" data-emp="${e.id}">${icon(paused ? 'play' : 'pause')}${paused ? 'Resume' : 'Pause'}</button></div></header>${callCard(e.id)}`;
  const asks = (e.asks_open || []).filter((a) => !S.gone.has(a.id));
  const askCards = asks.length ? `<ul class="ncards on-member" aria-label="${esc(e.name)} needs you">${asks.map((a) => needCard({ kind: 'ask', ask_kind: a.kind, id: a.id, title: a.title, options: a.options || [], emp: e.id })).join('')}</ul>` : '';
  const objs = e.objectives || [];
  const objective = objs.length ? objs.map((o) => `<div class="obj"><div class="obj-head"><span class="obj-title">${esc(o.title)}</span><span class="meta">${esc(dueLabel(o.due))}</span></div>
      ${krRows(o)}</div>`).join('')
    : `<div class="none-yet"><p>No objective yet.</p><button type="button" class="btn" data-act="try-ask" data-emp="${e.id}" data-text="Propose your objective for this month with three key results, using staff-record.">Ask ${esc(e.name)} to propose one</button></div>`;
  const byId = {}; for (const a of (S.cat ? S.cat.abilities : [])) byId[a.id] = a;
  const vis = visibleAbilities(e).sort((a, b) => (CHIP_ORDER.indexOf(a) + 1 || 99) - (CHIP_ORDER.indexOf(b) + 1 || 99));
  const chipOf = (id) => `<span class="chip static">${icon(ABILITY_ICON[id] || 'check')}${esc(CHIP_LABEL[id] || (byId[id] || {}).name || id)}</span>`;
  const showAll = S.chipsAll === e.id, shown = showAll ? vis : vis.slice(0, 8);
  const chips = shown.map(chipOf).join('') + (vis.length > 8 ? `<button type="button" class="chip more" data-act="chips-more" data-emp="${e.id}" aria-expanded="${showAll}">${showAll ? 'Show fewer' : '+' + (vis.length - 8) + ' more'}</button>` : '');
  const routines = (e.abilities || []).filter((id) => ROUTINES.includes(id)).map((id) => JOB_LABELS[id]);
  const list = tryList(e), text = list[(S.tryIdx[e.id] || 0) % list.length];
  const can = `<div class="chips">${chips || '<span class="quiet">Nothing switched on yet.</span>'}</div>${routines.length ? `<p class="meta">Works on a schedule: ${esc(routines.join(', '))}</p>` : ''}
    <div class="try"><span class="meta">Try asking</span><p class="try-text">“${esc(text)}”</p>
      <div class="try-actions"><button type="button" class="btn btn-primary" data-act="try-ask" data-emp="${e.id}" data-text="${esc(text)}">${icon('claude')}Ask in Claude</button>
      ${list.length > 1 ? `<button type="button" class="btn btn-ghost" data-act="try-next" data-emp="${e.id}">Another</button>` : ''}</div></div>`;
  const gallery = (e.results_7d || []).length ? `<div class="gallery">${e.results_7d.map((x) => resultTile(x, e)).join('')}</div>` : `<p class="quiet">Nothing shipped this week.</p>`;
  const mopts = (cur) => MODELS.map((m) => `<option value="${m}" ${m === cur ? 'selected' : ''}>${m}${m === 'sonnet' ? ' (balanced)' : m === 'haiku' ? ' (lightest)' : ' (strongest)'}</option>`).join('');
  const auto = (e.abilities || []).includes('full_autonomy');
  const controls = `<div class="controls">
    <div class="ctl"><label for="brain-${e.id}">Thinking model</label><select class="select auto" id="brain-${e.id}" data-field="brain" data-emp="${e.id}">${mopts(e.brain || 'opus')}</select></div>
    <div class="ctl"><label for="hands-${e.id}">Routine model</label><select class="select auto" id="hands-${e.id}" data-field="model" data-emp="${e.id}">${mopts(e.model)}</select></div>
    <div class="ctl"><span id="auto-${e.id}">Works without asking</span><button type="button" class="switch" role="switch" aria-checked="${auto}" aria-labelledby="auto-${e.id}" data-act="order" data-kind="set_autonomy" data-emp="${e.id}" data-on="${auto ? '' : '1'}"><i></i></button><span class="meta">${auto ? 'On' : 'Off'}</span></div>
    <div class="ctl"><button type="button" class="btn" data-act="order" data-kind="${paused ? 'resume' : 'pause'}" data-emp="${e.id}">${icon(paused ? 'play' : 'pause')}${paused ? 'Resume' : 'Pause'}</button></div></div>
    <nav class="elinks" aria-label="More about ${esc(e.name)}"><a href="/e/${e.id}/plan">Plan</a><a href="/e/${e.id}/knowledge">Knowledge</a><a href="/e/${e.id}/work?v=files">Files</a><a href="/e/${e.id}/work?v=activity">Activity</a><a href="/e/${e.id}/manage">Settings</a></nav>`;
  return `${head}${askCards}<section><div class="sec-head"><h2>Objective</h2></div>${objective}</section>
    <section><div class="sec-head"><h2>What ${esc(e.name)} can do</h2></div>${can}</section>
    <section><div class="sec-head"><h2>This week</h2></div>${weekTimeline(e, dt)}</section>
    <section><div class="sec-head"><h2>Results</h2></div>${gallery}</section>
    <section><div class="sec-head"><h2>Controls</h2></div>${controls}</section>`;
}

PAGES.employee = (r) => {
  const e = S.data.employees.find((x) => x.id === r.id);
  if (!e) return `<div class="empty"><b>No crew member called “${esc(r.id)}”.</b><p><a class="link" href="/team">Back to the crew</a></p></div>`;
  const dt = S.detail && S.detailId === r.id ? S.detail : null;
  if (r.tab === 'overview') return tabOverview(e, dt, r);
  const nKnow = dt ? dt.skills.own.length + dt.skills.team.length : '';
  const pl = (e.plan || {}).status;
  const tabs = [['overview', 'Overview', ''], ['plan', 'Plan', pl === 'proposed' ? 'needs your OK' : ''], ['work', 'Work', ''], ['knowledge', 'Knowledge', nKnow || ''], ['manage', 'Manage', '']];
  const body = { plan: tabPlan, chat: tabChat, knowledge: tabKnowledge, work: tabWork, manage: tabManage }[r.tab](e, dt, r);
  const canCall = dt && dt.abilities.includes('meetings') && e.status !== 'paused';
  const callBtn = callOf(e.id) ? '' : canCall && !Object.keys(S.data.calls || {}).length
    ? `<button class="btn" data-act="order" data-kind="call_start" data-emp="${e.id}" title="${esc(e.name)} listens on this ${MAC()} and takes notes. Tell the others you're taking notes.">${icon('mic')}Listen to a call</button>` : '';
  const claudeBtn = S.data.demo ? '' : `<button class="btn btn-primary" data-act="open-claude" data-emp="${e.id}" title="${esc(e.name)}'s own running conversation in a Claude window: everything they did and said, and what you say there they remember">${icon('claude')}Open in Claude</button>`;
  return `<header class="emp-head">${avatar(e.id, e.name, 'lg')}<div class="id"><h1>${esc(e.name)}</h1><div class="sub"><span>${esc(e.role)}</span><span>·</span><span>reports to ${esc(e.supervisor)}</span><span>·</span>${statusHtml(e)}</div></div><div class="actions">${claudeBtn}${callBtn}</div></header>${callCard(e.id)}
    <nav class="tabs">${tabs.map(([k, l, n]) => `<a href="/e/${e.id}${k === 'overview' ? '' : '/' + k}" class="${r.tab === k ? 'on' : ''}">${l}${n !== '' ? `<small>${esc(n)}</small>` : ''}</a>`).join('')}</nav>${body}`;
};

// The plan: PLAN.md, the one place a crew member's strategy lives. Agreed by the owner with one click,
// scored every evening, reviewed and rewritten every week.
function lastWorkday() { const w = S.data.workdays || ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']; return w[w.length - 1]; }
function tabPlan(e, dt) {
  if (!dt) return loading;
  const p = e.plan || {}, raw = (dt.memory || {})['PLAN.md'] || '';
  if (p.status === 'none' || !raw.trim()) {
    return `<div class="empty"><b>${esc(e.name)} hasn't proposed a plan yet.</b><p>Their next standup proposes one: the goal in numbers, how they'll get there, the cadence and the milestones. Then you agree to it here.</p>
      <p><button class="btn btn-primary" data-act="order" data-kind="run_job" data-job="standup" data-emp="${e.id}">${icon('target')}Ask for the plan now</button></p></div>`;
  }
  const doc = raw.replace(/^# .*\n+/, '').replace(/^Status:.*\n+/m, '');
  const agreed = p.status === 'agreed';
  const nx = p.next;
  const facts = [
    ['Goal', esc(p.goal || '—'), ''],
    ['Next milestone', nx ? esc(nx.what) : 'All done', nx ? 'by ' + esc(nx.by) : ''],
    ['Strategy review', p.reviewed ? 'Last on ' + esc(p.reviewed) : 'First one this ' + esc(lastWorkday()), 'every ' + esc(lastWorkday()) + ', plus a score of each day'],
  ].map(([k, val, sub]) => `<div class="fact"><span class="k">${k}</span><b>${val}</b>${sub ? `<span class="meta">${sub}</span>` : ''}</div>`).join('');
  const nums = (p.numbers || []).length ? `<div class="plan-nums">${p.numbers.map((n) => `<div><span class="meta">${esc(n.metric)}</span><b class="num">${esc(n.value)}</b><span class="meta">target ${esc(n.target || '—')} · ${esc(n.date)}</span></div>`).join('')}</div>` : '';
  return `<section class="plan-head ${agreed ? 'agreed' : 'proposed'}">
      <div class="plan-top"><div>${agreed ? `<span class="badge accent">${icon('check')}Agreed</span> <span class="meta">${esc(p.agreed)}</span>` : `<span class="badge warn">Proposed · waiting for your OK</span>`}</div>
      <div class="actions">${agreed ? '' : `<button class="btn btn-primary" data-act="order" data-kind="agree_plan" data-emp="${e.id}">${icon('check')}Agree to this plan</button>`}
        <button class="btn" data-act="plan-change" data-emp="${e.id}">${icon('chat')}Ask for changes</button>
        <button class="btn btn-ghost" data-act="order" data-kind="run_job" data-job="review" data-emp="${e.id}" title="${esc(e.name)} checks the numbers, what worked and what didn't, and rewrites the plan">Review it now</button></div></div>
      <div class="plan-facts">${facts}</div>${nums}</section>
    <article class="md prose plan-doc">${md(doc)}</article>
    ${shareHint(e)}`;
}
// After a week of real learning: the owner who trained them is offered to share it.
function shareHint(e) {
  const l = e.learned || {};
  if (e.shared_as || !(l.days >= 7 && (l.lessons >= 8 || l.skills >= 2))) return '';
  return `<section class="share-hint">${icon('share')}<div><b>${esc(e.name)} has learned a lot: ${plural(l.lessons, 'lesson')} and ${plural(l.skills, 'skill')} of their own in ${plural(l.days, 'day')}.</b>
    <p class="meta">Others hiring a ${esc(e.role)} could start with all of it, credited to you. Nothing private leaves.</p></div><a class="btn btn-sm" href="/e/${e.id}/manage#share">Share it</a></section>`;
}

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
  else if (sel === 'experience') preview = experienceForm(e);
  else if (sel.startsWith('note:')) preview = notePreview(e, dt, sel.slice(5));
  else preview = skillPreview(e, sel);
  return `<div class="ab-bar"><a class="btn btn-primary" href="/e/${e.id}/knowledge?f=experience">${icon('plus')}Teach from your experience</a><a class="btn" href="/e/${e.id}/knowledge?f=teach">Write a skill</a><span class="meta">Notes they keep, skills they learned or were taught, and playbooks for their abilities. All loaded on every run.</span></div>
    <div class="work"><div class="files">${list}</div><div class="preview">${preview}</div></div>`;
}
function experienceForm(e) {
  return `<form class="form prose" data-form="experience" data-emp="${e.id}">
    <h2>Teach ${esc(e.name)} from your experience</h2>
    <p class="muted small">Paste your playbook, process, notes or a handoff doc: how you do this work, what you've learned, what you never want. ${esc(e.name)} reads it, turns it into skills and rules, and tells you what they took from it. Leave out passwords and private data.</p>
    <div class="field"><label for="xp-title">What is it</label><input id="xp-title" class="input" name="title" maxlength="80" placeholder="My content playbook"></div>
    <div class="field"><label for="xp-text">Your know-how</label><textarea id="xp-text" class="textarea" name="text" rows="16" required minlength="40" placeholder="How I work… What worked… What I never want…"></textarea>
      <span class="hint">Or attach a file: <input type="file" accept=".md,.txt,.markdown,.csv,.json" data-xp-file></span></div>
    <div class="save-bar"><button class="btn btn-primary" type="submit">Teach ${esc(e.name)}</button><span class="meta">Takes a minute or two; the result shows in their Work tab.</span></div></form>`;
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

// How you'll talk to them, shown on a crew member's page until a phone is connected (or it's closed): the
// last step of the first minutes, so a new owner knows every way in and what to expect back.
function reachCard(e) {
  const st = S.data.setup || {};
  if (S.data.demo || st.paired || store(() => localStorage.getItem('reach-hidden'))) return '';
  return `<section class="reach"><div class="reach-head"><h2>How you'll work with ${esc(e.name)}</h2><button type="button" class="btn btn-ghost btn-sm" data-act="hide-reach" aria-label="Close">Got it</button></div>
    <ol>
      <li><b>Here.</b> Type in the box above; the answer appears right under it. The whole crew talks in Mission Control's team room.</li>
      <li><b>On your phone</b> <span class="meta">recommended</span>. Telegram, Slack or Discord, through a bot of your own: message ${esc(e.name)} from anywhere, send voice notes, photos and files, and get their routine reports there. <a class="btn btn-primary btn-sm" href="/connect">Connect your phone</a> <span class="meta">about 2 minutes</span></li>
      <li><b>In Claude.</b> <button type="button" class="btn btn-sm" data-act="open-claude" data-emp="${e.id}">${icon('claude')}Open ${esc(e.name)} in Claude</button> Their own running conversation in a Claude window: what they did, what they said, your replies, all in one place. Routines wait while you're in it.</li>
    </ol>
    <p class="meta">What to expect: an answer in a minute or two (deep research takes longer), each with “How I did it”. On their own they only send the routines you tick in Manage (like a morning brief) and things that need you. They never post, buy or message anyone but you.</p></section>`;
}

function tabWork(e, dt, r) {
  if (!dt) return loading;
  const activity = r.v === 'activity', files = r.v === 'files';
  const subs = `<div class="subtabs"><a href="/e/${e.id}/work" class="${activity || files ? '' : 'on'}">Latest</a><a href="/e/${e.id}/work?v=files" class="${files ? 'on' : ''}">Files${dt.files.length ? ' · ' + dt.files.length : ''}</a><a href="/e/${e.id}/work?v=activity" class="${activity ? 'on' : ''}">Activity${dt.runs.length ? ' · ' + dt.runs.length : ''}</a></div>`;
  if (activity) return subs + runsHtml(dt);
  if (!files) {          // type at the top; what they're doing now right under it, then results newest first, each with your question
    const live = liveCard(e.id);
    let asked = null;
    const pairs = [];
    for (const m of dt.chat) {                    // oldest first: each answer takes the question just before it
      if (m.from_id === e.id) { pairs.push({ m, q: asked }); asked = null; } else if (m.to_id === e.id) asked = m;
    }
    const recent = pairs.slice(-5).reverse();
    const results = recent.length ? `<div class="results">${recent.map(({ m, q }) => `<article class="result">${q ? `<p class="asked"><span>${esc(nameOf(q.from_id) || 'You')} asked</span> ${esc(String(q.body || '').replace(/\s+/g, ' ').slice(0, 220))}</p>` : ''}<div class="head"><span>${fmtTime(m.ts)}</span>${m.to_id && m.to_id !== 'owner' && m.to_id !== e.id ? `<span>→ ${esc(nameOf(m.to_id))}</span>` : ''}${channelBadge(m.channel)}</div><div class="body md rich">${bodyHtml(m.body, e.id)}</div>${receiptHtml(m.receipt, 'res:' + (m.id || m.ts))}</article>`).join('')}</div>`
      : live ? '' : `<div class="empty"><b>Nothing yet.</b><p>${esc(e.name)}'s results show up here as they finish.</p></div>`;
    return subs + `<div class="chat"><div class="chat-main">
      <form class="composer top" data-form="message" data-emp="${e.id}"><div class="box"><textarea id="composer-${e.id}" name="text" data-grow rows="1" placeholder="Ask ${esc(e.name)} for something…" aria-label="Message" maxlength="4000">${esc(v('message:' + e.id, 'text', ''))}</textarea>
      <div class="bar"><span class="meta">Enter to send · answers appear below</span><button class="btn btn-primary btn-sm" type="submit">${icon('send')}Send</button></div></div></form>
      ${reachCard(e)}<div data-live-slot="${e.id}">${live}</div>${results}</div>
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
  const head = `<div class="run-head"><span>When</span><span>What</span><span>Model</span><span class="num">Time</span><span class="num">Tokens</span><span>Result</span></div>`;
  return `<div class="runs">${head}${dt.runs.map((x) => {
    const steps = x.steps || [];
    const cells = `<span class="num">${fmtTime(x.ts)}</span><span>${esc(RUN_LABELS[x.job] || x.job)}</span><span class="muted">${esc(x.model || '')}</span><span class="num">${dur(x.secs)}</span><span class="num">${fmtTok(x.tokens != null ? x.tokens : (x.cost_usd || 0) * 200000)}</span><span class="${x.ok ? 'muted' : 'err'}">${x.ok ? (steps.length ? plural(steps.length, 'step') : 'ok') : esc(x.error || 'failed')}</span>`;
    const key = 'run:' + x.ts;
    return steps.length ? `<details class="run" data-key="${esc(key)}" ${S.open.has(key) ? 'open' : ''}><summary>${cells}</summary><ol class="steps done">${steps.map((s) => `<li><span>${esc(s.text)}</span><span class="t num">${mmss(s.t)}</span></li>`).join('')}</ol></details>`
      : `<div class="run"><div class="sum">${cells}</div></div>`;
  }).join('')}</div>`;
}

function tabManage(e, dt) {
  if (!S.cat || !dt) return loading;
  const paused = e.status === 'paused';
  const jobs = Object.entries(JOB_LABELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('');
  const modelOpts = (cur) => MODELS.map((m) => `<option value="${m}" ${m === cur ? 'selected' : ''}>${m}${m === 'sonnet' ? ' (balanced)' : m === 'haiku' ? ' (lightest on your plan)' : ' (strongest, heaviest)'}</option>`).join('');
  const models = modelOpts(e.model);
  const brains = modelOpts(e.brain || 'opus');
  const on = new Set(dt.abilities);
  const groups = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<div class="ab-group"><h3>${esc(g)}</h3>${items.map((a) => a.consent
      ? `<div class="ab">${icon(on.has(a.id) ? 'check' : 'circle')}<div><div class="n">${esc(a.name)}<span class="badge">${on.has(a.id) ? 'on' : 'off'} · its own switch below</span></div><div class="d">${esc(a.description)}</div></div></div>`
      : a.locked
      ? `<div class="ab">${icon('check')}<div><div class="n">${esc(a.name)}<span class="badge">always on</span></div><div class="d">${esc(a.description)}</div></div></div>`
      : `<label class="ab"><input type="checkbox" name="abilities" value="${a.id}" ${on.has(a.id) ? 'checked' : ''} form="ab-${e.id}"><div><div class="n">${esc(a.name)}${a.paid ? '<span class="badge warn">paid</span>' : ''}${a.job ? '<span class="badge">routine</span>' : ''}</div><div class="d">${esc(a.description)}</div></div></label>`).join('')}</div>`;
  }).join('');
  return `<div class="manage">
    <section><h2>Status</h2><p class="desc">${paused ? `${esc(e.name)} is paused: no chats or routines until you resume.` : `${esc(e.name)} is working normally.`}</p>
      <div class="save-bar"><button class="btn" data-act="order" data-kind="${paused ? 'resume' : 'pause'}" data-emp="${e.id}">${icon(paused ? 'play' : 'pause')}${paused ? 'Resume' : 'Pause'}</button></div></section>
    <section><h2>Run a routine now</h2><p class="desc">The result shows up in the chat and the team room.</p>
      <div class="save-bar"><select class="select auto" id="run-job" aria-label="Routine">${jobs}</select><button class="btn" data-act="order" data-kind="run_job" data-emp="${e.id}" data-from="#run-job" ${paused ? 'disabled' : ''}>Launch now</button></div></section>
    <section><h2>Brain and hands</h2><p class="desc">The brain thinks and talks with you: standup, initiative, end of day, the weekly review, chats. The hands do the production work: follow-ups, the morning brief, scout, self-test. Both switch to the lightest model on their own when your plan is nearly used up.</p>
      <div class="save-bar"><label class="small muted" for="brain-${e.id}">Brain</label><select class="select auto" id="brain-${e.id}" data-field="brain" data-emp="${e.id}" aria-label="Brain model">${brains}</select>
      <label class="small muted" for="hands-${e.id}">Hands</label><select class="select auto" id="hands-${e.id}" data-field="model" data-emp="${e.id}" aria-label="Hands model">${models}</select></div></section>
    ${cloudSection(e)}
    ${autonomySection(e)}
    ${browserSection(e)}
    <section><h2>Weekly budget</h2><p class="desc">Tokens a week on your Claude plan. When it's used up, routines wait and ${esc(e.name)} still answers you. This week: ${fmtTok(e.tokens_7d)} tokens.</p><div><select class="select auto" data-field="weekly_tokens" data-emp="${e.id}" aria-label="Weekly budget">${[[0, 'No cap'], [1000000, 'Light · 1M tokens'], [3000000, 'Regular · 3M tokens'], [8000000, 'Heavy · 8M tokens'], [20000000, 'Very heavy · 20M tokens']].map(([n, l]) => `<option value="${n}" ${Number(e.weekly_tokens || 0) === n ? 'selected' : ''}>${l}</option>`).join('')}</select></div></section>
    <section><h2>Abilities</h2><p class="desc">What ${esc(e.name)} may do. These are locks: anything off is blocked, whatever anyone says in chat. Changes apply on their next run.</p>
      <form id="ab-${e.id}" data-form="abilities" data-emp="${e.id}"><div class="ab-bar"><button class="btn btn-primary" type="submit">Save</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super agent</button><span class="meta">${on.size} of ${S.cat.abilities.length} on</span></div></form>
      <div class="ab-groups">${groups}</div></section>
    ${connectorsSection(e)}
    ${shareSection(e)}
    <section><h2>Retire</h2><p class="desc">They stop working; their folder and memory stay on this ${MAC()}.</p><div><button class="btn btn-danger" data-act="retire" data-emp="${e.id}" data-name="${esc(e.name)}">Retire ${esc(e.name)}…</button></div></section>
  </div>`;
}

// Share what a crew member knows: Claude drafts a private-free copy (job, rules, skills, experience); the owner
// reads and edits every word; it's saved as a role; then it goes out as a file or to the Orbit community.
function shareSection(e) {
  const l = e.learned || {}, st = (S.share || {})[e.id];
  const intro = `<p class="desc">${esc(e.name)} has ${plural(l.lessons || 0, 'lesson')} and ${plural(l.skills || 0, 'skill')} of their own after ${plural(l.days || 0, 'day')} on the job. Share it as a role anyone can hire, credited to you: the job, the rules, the skills and the experience. Claude first takes out names, accounts, links and your business's numbers; you read and edit every word before anything is saved or leaves this ${MAC()}.</p>`;
  let body;
  if (!st) {
    body = `<div class="save-bar"><button class="btn btn-primary" data-act="share-prepare" data-emp="${e.id}">${icon('share')}Prepare a shareable copy</button>${e.shared_as ? `<span class="meta">Shared before as “${esc(e.shared_as)}”. <a class="link" href="/api/role/${esc(e.shared_as)}.orbit-role.zip" download>Download that file</a></span>` : '<span class="meta">Takes a minute or two.</span>'}</div>`;
  } else if (st.stage === 'busy') {
    body = thinking('Preparing a shareable copy', ['Reading the lessons and skills', 'Taking out names, accounts, links and numbers', 'Writing it as know-how anyone can use']);
  } else if (st.stage === 'draft') {
    const d = st.draft;
    body = `<form class="form share-form" data-form="share-save" data-emp="${e.id}">
      <div class="field"><label for="sh-title-${e.id}">Role name</label><input id="sh-title-${e.id}" class="input" name="title" maxlength="80" value="${esc(d.title)}" required></div>
      <div class="field"><label for="sh-sum-${e.id}">One line: what they're good at</label><input id="sh-sum-${e.id}" class="input" name="summary" maxlength="300" value="${esc(d.summary)}"></div>
      <div class="field"><label for="sh-by-${e.id}">Credited to</label><input id="sh-by-${e.id}" class="input" name="trained_by" maxlength="60" value="${esc(d.trained_by || S.data.me)}"></div>
      <div class="field"><label for="sh-xp-${e.id}">What they learned (EXPERIENCE.md)</label><textarea id="sh-xp-${e.id}" class="textarea mono" name="experience" rows="14">${esc(d.experience)}</textarea></div>
      <div class="field"><label for="sh-rules-${e.id}">Rules for the role</label><textarea id="sh-rules-${e.id}" class="textarea mono" name="rules" rows="5">${esc(d.rules)}</textarea></div>
      ${(d.skills || []).length ? `<fieldset class="field"><legend>Skills that go with it</legend>${d.skills.map((k, i) => `<details class="skill-pick"><summary><label><input type="checkbox" name="skill" value="${i}" checked> ${esc(k.name)}</label></summary><textarea class="textarea mono" name="skill-${i}" rows="10" aria-label="${esc(k.name)}">${esc(k.text)}</textarea></details>`).join('')}</fieldset>` : ''}
      ${(d.removed || []).length ? `<p class="meta">Taken out: ${esc(d.removed.join(', '))}. Read it once more: you know your business best.</p>` : ''}
      <div class="save-bar"><button class="btn btn-primary" type="submit">Save as a role</button><button class="btn btn-ghost" type="button" data-act="share-reset" data-emp="${e.id}">Start over</button></div></form>`;
  } else {
    const rid = st.rid;
    body = `<div class="shared"><p><b>Saved as “${esc(st.title)}”.</b> It's on your hiring page, and now you can send it anywhere:</p>
      <ul class="share-ways">
        <li><a class="btn" href="/api/role/${esc(rid)}.orbit-role.zip" download>${icon('download')}Download the file</a><span class="meta">One file. Send it to anyone with Orbit; they add it on their hiring page (“Add a role from a file or link”).</span></li>
        <li><button class="btn btn-primary" data-act="share-publish" data-role="${esc(rid)}">${icon('share')}Share with the Orbit community</button><span class="meta">Goes to the Orbit project on GitHub for a quick check that nothing private is in it, then reaches every Orbit with the next update, credited to you.</span></li>
        <li><a class="btn btn-ghost" href="/hire?role=${esc(rid)}">${icon('plus')}Hire another from it</a></li></ul>
      ${st.published ? `<p class="meta">${esc(st.published.how)} <a class="link" href="${esc(st.published.url)}" target="_blank" rel="noopener">${st.published.pr ? 'See the pull request' : 'Open the page again'}</a></p>` : ''}</div>`;
  }
  return `<section id="share" class="share"><h2>${icon('share')} Share what ${esc(e.name)} knows</h2>${intro}${body}</section>`;
}

// ---- abilities matrix
PAGES.abilities = () => {
  const d = S.data, emps = d.employees;
  if (!S.cat) return loading;
  if (!emps.length) return `<header class="page-head"><div><h1>Abilities</h1></div></header><div class="empty"><b>Add a crew member first.</b><p>Their abilities appear here as a column of checkboxes.</p></div>`;
  const head = emps.map((e) => `<th><div>${esc(e.name)}</div><div class="acts"><button class="btn btn-sm btn-primary" type="submit" form="mx-${e.id}">Save</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="default">Default</button><button class="btn btn-sm" type="button" data-act="preset" data-emp="${e.id}" data-preset="super">Super</button></div></th>`).join('');
  const rows = S.cat.groups.map((g) => {
    const items = S.cat.abilities.filter((a) => a.group === g);
    return `<tr class="g"><th colspan="${emps.length + 1}">${esc(g)}</th></tr>` + items.map((a) => `<tr><td><div>${esc(a.name)}${a.paid ? ' <span class="badge warn">paid</span>' : ''}</div><div class="d">${esc(a.description)}</div></td>${emps.map((e) => a.consent
      ? `<td class="c"><a class="link small" href="/e/${e.id}/manage" title="Its own switch, in Manage">${(e.abilities || []).includes(a.id) ? 'On' : 'Off'}</a></td>`
      : a.locked
      ? `<td class="c" title="Always on">${icon('check')}</td>`
      : `<td class="c"><input type="checkbox" form="mx-${e.id}" name="abilities" value="${a.id}" ${(e.abilities || []).includes(a.id) ? 'checked' : ''} aria-label="${esc(a.name)} for ${esc(e.name)}"></td>`).join('')}</tr>`).join('');
  }).join('');
  return `<header class="page-head"><div><h1>Abilities</h1><p class="sub">Tick what each employee may do. <b>Default</b> is a capable, low-cost setup; <b>Super agent</b> ticks everything. Changes apply on their next run.</p></div><div class="actions"><a class="btn" href="/team">Back to the team</a></div></header>
    ${emps.map((e) => `<form id="mx-${e.id}" data-form="abilities" data-emp="${e.id}"></form>`).join('')}
    <div class="matrix-wrap"><table class="matrix"><thead><tr><th>Ability</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
};

// ---- hire
// ---- hire as a stepper: Job, Questions, Card, Hire. The same data and API calls as the welcome flow (S.ob), a different shape.
function jobIcon(x) {
  const t = `${x.id} ${x.role || ''}`.toLowerCase();
  return /watch/.test(t) ? 'bell' : /research/.test(t) ? 'eye' : /social|creator|market/.test(t) ? 'send' : /lead|recruit|job|client/.test(t) ? 'users' : /book/.test(t) ? 'gauge'
    : /assist|call|update/.test(t) ? 'chat' : /review|design/.test(t) ? 'doc' : 'plus';
}
function hireStep(ob) { return !ob || ob.stage === 'basics' ? 1 : ob.stage === 'asking' || ob.stage === 'questions' ? 2 : ob.review ? 4 : 3; }
function stepBar(n) {
  const names = ['Job', 'Questions', 'Card', 'Hire'];
  return `<ol class="stepbar" aria-label="Steps">${names.map((l, i) => `<li class="${i + 1 < n ? 'done' : i + 1 === n ? 'on' : ''}"${i + 1 === n ? ' aria-current="step"' : ''}>${i + 1 < n ? icon('check') : `<span class="sn">${i + 1}</span>`}${l}</li>`).join('')}</ol>
    <div class="meter stepprog" role="progressbar" aria-label="Step ${n} of 4" aria-valuemin="0" aria-valuemax="4" aria-valuenow="${n}"><i data-w="${n * 25}"></i></div>`;
}
function loader(title, line) {
  return `<div class="loader" role="status" aria-live="polite"><div class="orbit-spin" aria-hidden="true"><i></i><i></i><i></i></div><div><b>${esc(title)}</b><p class="meta">${esc(line)}</p></div></div>`;
}
function chipRow(ids, key) {                      // capability chips: job-relevant first, at most 8, then "+N more"
  const vis = ids.filter((id) => !ABILITY_SKIP.includes(id) && !ROUTINES.includes(id)).sort((a, b) => (CHIP_ORDER.indexOf(a) + 1 || 99) - (CHIP_ORDER.indexOf(b) + 1 || 99));
  const all = S.chipsAll === key, shown = all ? vis : vis.slice(0, 8), byId = {}; for (const a of (S.cat ? S.cat.abilities : [])) byId[a.id] = a;
  return shown.map((id) => `<span class="chip static">${icon(ABILITY_ICON[id] || 'check')}${esc(CHIP_LABEL[id] || (byId[id] || {}).name || id)}</span>`).join('')
    + (vis.length > 8 ? `<button type="button" class="chip more" data-act="chips-more" data-emp="${esc(key)}" aria-expanded="${all}">${all ? 'Show fewer' : '+' + (vis.length - 8) + ' more'}</button>` : '');
}
function questionStep(sel, ob, name) {
  const qs = ob.questions || [], qi = Math.max(0, Math.min(ob.qi || 0, qs.length - 1)), last = qi >= qs.length - 1;
  const one = (q, i) => {
    const a = ob.answers[q.id] || (q.type === 'multi' ? [] : '');
    const body = q.type === 'text' ? `<input class="input lg" name="${q.id}" maxlength="1500" placeholder="${esc(q.placeholder || '')}" value="${esc(a)}" aria-label="${esc(q.text)}">`
      : `<div class="choices">${q.options.map((o) => { const on = q.type === 'multi' ? a.includes(o) : a === o;
          return `<button type="button" class="choice ${on ? 'on' : ''}" data-act="answer" data-q="${q.id}" data-multi="${q.type === 'multi' ? 1 : ''}" data-v="${esc(o)}" aria-pressed="${on}">${on ? icon('check') : ''}${esc(o)}</button>`; }).join('')}</div>
        <input class="input other" name="${q.id}__other" maxlength="400" placeholder="Other…" aria-label="Other answer" value="${esc(ob.answers[q.id + '__other'] || '')}">`;
    return `<fieldset class="q one-q" ${i === qi ? '' : 'hidden'}><legend>${esc(q.text)}</legend>${q.why ? `<p class="meta">${esc(q.why)}</p>` : ''}${body}</fieldset>`;
  };
  return `<form class="interview step-form" data-form="interview" data-from="hire">
    ${qs.length ? `<p class="meta num">${qi + 1} of ${qs.length}</p>` : ''}${ob.intro && qi === 0 ? `<p class="meta">${esc(ob.intro)}</p>` : ''}
    ${qs.map(one).join('')}
    <div class="step-nav"><button type="button" class="btn btn-ghost" data-act="${qi > 0 ? 'q-prev' : 'ob-back'}">Back</button>
      ${last ? `<button class="btn btn-primary btn-lg" type="submit">Build ${esc(name ? name + '\u2019s' : 'their')} card</button>` : `<button type="button" class="btn btn-primary btn-lg" data-act="q-next">Next</button>`}</div></form>`;
}
function cardStep(sel, ob, name) {
  const c = ob.card, ed = ob.edit, E = ob.editing || (ob.editing = {}), picked = new Set(ed.access);
  const edit = (k) => `<button type="button" class="linkbtn" data-act="ob-edit" data-k="${k}" aria-expanded="${!!E[k]}">${E[k] ? 'Done' : 'Edit'}</button>`;
  const blk = (k, title, inner, withEdit = true) => `<section class="cs-block"><div class="cs-title"><h3>${title}</h3>${withEdit ? edit(k) : ''}</div>${inner}</section>`;
  const ids = ACCESS.filter(([k]) => picked.has(k) && k !== 'brief').flatMap(([, , a]) => a);
  const toolsEdit = `<div class="chips">${ACCESS.filter(([k]) => k !== 'brief').map(([k, l]) => `<button type="button" class="chip ${picked.has(k) ? 'on' : ''}" data-act="ob-access" data-k="${k}" aria-pressed="${picked.has(k)}">${esc(l)}</button>`).join('')}</div>`;
  const routineList = [['brief', 'Morning brief'], ['standup', 'Standup'], ['initiative', 'Initiative'], ['eod', 'End of day']];
  const routinesOn = routineList.filter(([k]) => ed.routines[k]).map(([, l]) => l);
  const routinesEdit = `<div class="chips">${routineList.map(([k, l]) => `<button type="button" class="chip ${ed.routines[k] ? 'on' : ''}" data-act="ob-routine" data-k="${k}" aria-pressed="${!!ed.routines[k]}">${l}</button>`).join('')}</div>`;
  const sites = (ed.browser || []).map((d) => (SITES.find(([, x]) => x === d) || [d])[0]);
  const onoff = (on) => `<span class="onoff-state">${on ? icon('check') : ''}${on ? 'On' : 'Off'}</span>`;
  const long = String(ed.scope || '').length > 150;
  const asks = (c.access || []).map((a) => { const [ic, label] = ACCESS_KIND[a.kind] || ACCESS_KIND.other; return `<li>${icon(ic)}<span><b>${esc(a.what)}</b> <span class="meta">${esc(label)}</span></span></li>`; }).join('');
  const dayOf = (p) => { const m = String(p).match(/^\s*((?:Day|Week)\s*\d+)\s*[:\-–]\s*(.*)$/i); return m ? `<li><b>${esc(m[1])}</b><span>${esc(m[2])}</span></li>` : `<li><b>Then</b><span>${esc(p)}</span></li>`; };
  return `<form class="cardstep step-form" data-form="hire" data-from="hire">
    <header class="cs-head"><span class="avatar xl hue-${hue(name || 'x')}" aria-hidden="true">${esc((name || '?').charAt(0).toUpperCase())}</span><div class="cs-who"><h2>${esc(name || 'New crew member')}</h2>
      ${E.head ? `<input class="input" name="role" maxlength="120" value="${esc(ed.role)}" aria-label="Job title">` : `<p class="muted">${esc(ed.role)}</p>`}</div>${edit('head')}</header>
    ${blk('scope', 'The job', E.scope ? `<textarea class="textarea" name="scope" rows="4" data-grow maxlength="2000" aria-label="Scope">${esc(ed.scope)}</textarea>`
      : `<p class="cs-scope${ob.more ? '' : ' clamp2'}">${esc(ed.scope)}</p>${long ? `<button type="button" class="linkbtn" data-act="ob-more">${ob.more ? 'Less' : 'More'}</button>` : ''}`)}
    ${(c.responsibilities || []).length ? blk('', 'Responsibilities', `<ul class="ticks">${c.responsibilities.map((r) => `<li>${icon('check')}${esc(r)}</li>`).join('')}</ul>`, false) : ''}
    ${c.first_task ? `<section class="first-task"><span class="meta">First task</span><p>${esc(c.first_task)}</p></section>` : ''}
    ${(c.plan || []).length ? blk('', 'First days', `<ol class="mini-tl">${c.plan.map(dayOf).join('')}</ol>`, false) : ''}
    ${blk('tools', 'What they can do', E.tools ? toolsEdit : `<div class="chips">${chipRow(ids, 'hire') || '<span class="quiet">Nothing switched on.</span>'}</div>`)}
    ${blk('routines', 'Routines', E.routines ? routinesEdit : `<p class="meta">${routinesOn.length ? 'Works on a schedule: ' + esc(routinesOn.join(', ')) : 'No routines.'}</p>`)}
    <section class="cs-block"><div class="onoff"><span id="ob-auto">Works without asking</span><button type="button" class="switch" role="switch" aria-checked="${!!ed.autonomy}" aria-labelledby="ob-auto" data-act="ob-autonomy" data-v="${ed.autonomy ? '' : '1'}"><i></i></button>${onoff(!!ed.autonomy)}</div>
      <div class="onoff"><span>May post for you on</span><b class="one">${sites.length ? esc(sites.join(', ')) : 'Nowhere'}</b>${onoff(sites.length > 0)}${edit('sites')}</div>
      ${E.sites ? `<div class="cs-edit">${sitePicker('ob', ed.browser || [])}<div class="seg" role="group" aria-label="Approval"><button type="button" class="${(ed.approval || 'each') === 'each' ? 'on' : ''}" data-act="ob-approval" data-v="each">Ask me for each one</button><button type="button" class="${ed.approval === 'batch' ? 'on' : ''}" data-act="ob-approval" data-v="batch">Once per batch</button><button type="button" class="${ed.approval === 'none' ? 'on' : ''}" data-act="ob-approval" data-v="none">Don't ask me</button></div></div>` : ''}
      <div class="onoff"><span>Weekly budget</span><b>${esc((BUDGET_LABELS[ed.budget] || BUDGET_LABELS.regular)[0])}</b><span class="meta">${esc((BUDGET_LABELS[ed.budget] || BUDGET_LABELS.regular)[1])}</span>${edit('budget')}</div>
      ${E.budget ? `<div class="cs-edit"><div class="seg budget" role="group" aria-label="Weekly budget">${Object.entries(BUDGET_LABELS).map(([k, [l, t]]) => `<button type="button" class="${ed.budget === k ? 'on' : ''}" data-act="ob-budget" data-k="${k}"><b>${l}</b><span>${t}</span></button>`).join('')}</div></div>` : ''}</section>
    ${asks ? blk('', 'Will ask you for', `<ul class="asks cs-asks">${asks}</ul>`, false) : ''}
    ${S.data.employees.length ? blk('with', 'Works with', E.with ? `<div class="chips">${S.data.employees.map((x) => `<button type="button" class="chip ${(ed.with || []).includes(x.id) ? 'on' : ''}" data-act="ob-with" data-id="${x.id}" aria-pressed="${(ed.with || []).includes(x.id)}">${esc(x.name)}</button>`).join('')}</div>`
      : `<p class="meta">${(ed.with || []).length ? esc((ed.with || []).map((id) => nameOf(id)).join(', ')) : 'Nobody in particular. Anyone on the crew can always ask anyone.'}</p>`) : ''}
    ${(ob.conn || []).length ? blk('conn', 'Apps', E.conn ? `<div class="chips">${ob.conn.map((x) => `<button type="button" class="chip ${(ed.connectors || []).includes(x.id) ? 'on' : ''}" data-act="ob-conn" data-id="${x.id}" aria-pressed="${(ed.connectors || []).includes(x.id)}" title="${esc(x.what)}">${esc(x.name)}</button>`).join('')}</div>`
      : `<p class="meta">${(ed.connectors || []).length ? esc(ob.conn.filter((x) => (ed.connectors || []).includes(x.id)).map((x) => x.name).join(', ')) : 'None chosen.'}</p>`) : ''}
    <div class="step-nav"><button type="button" class="btn btn-ghost" data-act="ob-back">Back</button><button type="button" class="btn btn-primary btn-lg" data-act="ob-review">Next</button></div></form>`;
}
function reviewStep(sel, ob, name) {
  const ed = ob.edit, sites = (ed.browser || []).map((d) => (SITES.find(([, x]) => x === d) || [d])[0]);
  return `<form class="cardstep step-form" data-form="hire" data-from="hire">
    <header class="cs-head"><span class="avatar xl hue-${hue(name || 'x')}" aria-hidden="true">${esc((name || '?').charAt(0).toUpperCase())}</span><div class="cs-who"><h2>${esc(name || 'New crew member')}</h2><p class="muted">${esc(ed.role)}</p></div></header>
    ${ob.card.first_task ? `<section class="first-task"><span class="meta">First task</span><p>${esc(ob.card.first_task)}</p></section>` : ''}
    <section class="cs-block"><div class="onoff"><span>Works without asking</span><span class="onoff-state">${ed.autonomy ? icon('check') + 'On' : 'Off'}</span></div>
      <div class="onoff"><span>May post for you on</span><b class="one">${sites.length ? esc(sites.join(', ')) : 'Nowhere'}</b></div></section>
    <div class="step-nav"><button type="button" class="btn btn-ghost" data-act="ob-unreview">Back</button><button class="btn btn-primary btn-lg" type="submit" data-hire-label>${icon('plus')}Launch ${esc(name || 'them')}</button></div></form>`;
}
PAGES.hire = (r) => {
  if (!S.roles) return loading;
  if (r.role && !S.job) { S.situation = S.situation || 'other'; pickJob(r.role, false); }
  const sel = S.roles.roles.find((x) => x.id === S.job) || null;
  const ob = sel && S.ob && S.ob.job === sel.id ? S.ob : null, n = hireStep(ob);
  const name = v('hire', 'name', (sel && sel.names[0]) || '');
  let body;
  if (n === 1) {
    const tiles = S.roles.roles.slice().sort((a, b) => (a.id === 'blank') - (b.id === 'blank')).map((x) => `<button type="button" class="jtile ${S.job === x.id ? 'on' : ''}" data-act="job" data-role="${x.id}" aria-pressed="${S.job === x.id}">${icon(jobIcon(x))}<b>${esc(x.role || 'Something else')}</b>
      <span class="one" title="${esc(x.title)}">${x.id === 'blank' ? 'Describe the job yourself' : esc(x.title)}</span>${x.source ? `<em class="meta">${x.source === 'yours' ? 'your role' : 'community'}</em>` : ''}</button>`).join('');
    const imp = `<details class="role-import"><summary>${icon('download')} Add a role from a file or link</summary>
      <form class="row-form" data-form="role-import"><input class="file" type="file" name="file" accept=".zip,application/zip" aria-label="Role file"><input class="input" name="url" type="url" placeholder="https://… link to a role file" pattern="https://.*" aria-label="Role link"><button class="btn" type="submit">Add</button></form></details>`;
    body = `<div class="jgrid">${tiles}</div>${sel ? interviewHtml(sel, 'hire') : ''}${sel ? '' : imp}`;
  } else if (ob.stage === 'asking') body = loader(`Your Claude is preparing ${name || 'their'} questions`, 'A few seconds. It reads about your business first.');
  else if (ob.stage === 'composing') body = loader(`Building ${name || 'their'} card`, 'Choosing responsibilities, routines and what to ask you for.');
  else if (n === 2) body = questionStep(sel, ob, name);
  else if (n === 3) body = cardStep(sel, ob, name);
  else body = reviewStep(sel, ob, name);
  return `<header class="page-head"><div><h1>${n === 1 ? 'Hire someone' : esc(name || 'New crew member')}</h1></div></header>${stepBar(n)}<div class="step-body">${body}</div>`;
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
  const F = (h) => h.replace(/<(input|select|textarea)\b/g, '<$1 form="sf"');       // the fields sit in different blocks but save together
  const adv = (key, title, inner, id) => `<details class="adv-d"${id ? ` id="${id}"` : ''} data-key="set:${key}" ${S.open.has('set:' + key) || (id && location.hash === '#' + id) ? 'open' : ''}><summary>${title}</summary><div class="adv-in">${inner}</div></details>`;
  const advLink = (href, title, hint) => `<a class="adv-row" href="${href}"><span>${title}</span><span class="meta">${hint}</span>${icon('chev').replace('<svg', '<svg class="chev"')}</a>`;
  const ts = d.team_skills || [], emps = d.employees;
  const skills = ts.length ? `<div class="list">${ts.map((x) => `<a class="row row-2" href="/e/${esc(x.shared_from || (emps[0] || {}).id)}/knowledge?f=team:${esc(x.name)}"><div><div class="title">${esc(x.name)}</div><div class="meta">${esc(x.description)}</div></div><span class="meta">shared by ${esc(nameOf(x.shared_from || ''))}</span></a>`).join('')}</div>`
    : '<p class="quiet">None yet. When someone learns something everyone should know, they share it here.</p>';
  const biz = `<p class="desc">Every employee reads this before they work.</p>
      <div class="field"><label for="tn">Team name</label><input id="tn" class="input" name="team_name" maxlength="60" value="${esc(v('settings', 'team_name', s.team_name))}"></div>
      <div class="field"><label for="ab">About the business</label><textarea id="ab" class="textarea" name="about" rows="7" maxlength="6000" placeholder="What you do, for whom, what matters most right now, names they should know.">${esc(v('settings', 'about', s.about))}</textarea></div>
      <div class="field"><span class="lbl">Workdays</span><div class="chips">${days}</div><span class="hint">Routines run on these days.</span></div>`;
  const awake = `<p class="desc">Your crew works only while this ${MAC()} is awake; when it wakes, they catch up.</p>
      <div><select class="select auto" name="keep_awake" aria-label="Keep awake">${[['plugged', 'While plugged in (recommended)'], ['always', 'Always, on battery too (uses more battery)'], ['off', 'Never']].map(([k, l]) => `<option value="${k}" ${v('settings', 'keep_awake', s.keep_awake) === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>`;
  const comp = `<p class="desc">Optional: a <a class="link" href="https://github.com/new" target="_blank" rel="noopener">private GitHub repository</a> for jobs too heavy for this ${MAC()}.</p>
      <div class="field"><label for="compute-repo">Private repository</label><input id="compute-repo" class="input" name="compute" maxlength="120" placeholder="yourname/orbit-compute" value="${esc(v('settings', 'compute', s.compute || ''))}"></div>`;
  const timesB = `<p class="desc">Local time on this ${MAC()}. Each employee runs only the routines ticked in their abilities.</p><div class="times">${times}</div>`;
  const research = `<p class="desc">Apify reads social sites and Maps. Paid per use, never beyond this budget.</p>
      <div class="usage-box"><div class="row2"><span>Spent this month</span><b class="num">${money(spent)} of ${money(budget)}</b></div><div class="meter ${pct >= 80 ? 'hot' : ''}"><i data-w="${pct}"></i></div></div>
      <div class="form-row"><div class="field"><label for="amb">Monthly budget (USD)</label><input id="amb" class="input" name="apify.monthly_budget_usd" inputmode="decimal" value="${esc(v('settings', 'apify.monthly_budget_usd', s.apify.monthly_budget_usd ?? 5))}"></div>
      <div class="field"><label for="amr">Max per run (USD)</label><input id="amr" class="input" name="apify.max_run_usd" inputmode="decimal" value="${esc(v('settings', 'apify.max_run_usd', s.apify.max_run_usd ?? 0.5))}"><span class="hint">Hard ceiling 2.00.</span></div></div>`;
  const sites = `<p class="desc">Only limits scripts the crew writes itself.</p>
      <div class="field"><textarea class="textarea" name="network_domains" rows="3" placeholder="api.example.com&#10;*.example.org" aria-label="Allowed sites">${esc(v('settings', 'network_domains', s.network_domains.join('\n')))}</textarea></div>`;
  const apify = `  <section><h3>Apify token</h3><p class="desc">${s.apify.token ? 'Connected.' : 'A free <a class="link" href="https://console.apify.com/sign-up" target="_blank" rel="noopener">apify.com</a> account has monthly credit. Paste its API token below.'}</p>
    <form class="connect-form row-form" data-form="connect" data-kind="apify"><input id="c-apify" class="input mono" name="token" required autocomplete="off" spellcheck="false" placeholder="${s.apify.token ? 'Paste a new token to replace it' : 'apify_api_…'}"><button class="btn" type="submit">${s.apify.token ? 'Replace' : 'Add'}</button></form></section>
`;
  const chan = `  <section id="channels"><h3>Chat channels</h3><p class="desc">Your employees answer you through bots you create. Each one talks only to your bots.</p><div class="list">${chans}</div></section>
`;
  const access = `  <section id="access"><h3>Access</h3><p class="desc">Owners can direct every employee. Only approve people you know.</p>
    <dl class="kv">${d.owners.map((o) => `<dt>${esc(o.name)}</dt><dd>${o.local ? 'this ' + MAC() + ' only · <a class="link" href="/connect">connect your phone</a>' : esc((o.addresses || []).join(' · '))}</dd>`).join('')}</dl>
    ${pending ? `<h3>Messaged your bot</h3>${pending}` : `<p class="meta">Nobody is waiting for approval.</p>`}</section>
`;
  const appear = `  <section><h2>Appearance</h2><div class="seg" role="group" aria-label="Appearance"><button data-act="theme" data-v="" class="${S.theme === '' ? 'on' : ''}">${MAC() === 'PC' ? 'Match Windows' : MAC() === 'Mac' ? 'Match the Mac' : 'Match the system'}</button><button data-act="theme" data-v="light" class="${S.theme === 'light' ? 'on' : ''}">Light</button><button data-act="theme" data-v="dark" class="${S.theme === 'dark' ? 'on' : ''}">Dark</button></div></section>
`;
  const about = `
    <dl class="kv"><dt>Claude</dt><dd>${s.claude.ok ? `signed in (${esc(s.claude.note)})` : '<span class="badge danger">not signed in</span> ask Claude: “Sign in Claude Code for my Orbit.”'} · runs on ${s.auth === 'api_key' ? 'your API key' : 'your subscription'}</dd>
      <dt>Service</dt><dd>${d.online ? 'running' : '<span class="badge danger">stopped</span>'} · panel on port ${s.port}</dd>
      <dt>Team folder</dt><dd><code>${esc(s.home)}</code></dd><dt>Kit</dt><dd><code>${esc(s.kit)}</code></dd></dl>`;
  const hist = `${orders.length ? `<div class="list mini">${orders.map((o) => `<div class="row row-2"><div><div class="small">${esc(o.summary)}</div><div class="meta">${esc(o.by)} · ${fmtTime(o.ts)}${o.result ? ' · ' + esc(o.result) : ''}</div></div><span class="badge ${o.status === 'failed' ? 'danger' : ''}">${esc(o.status)}</span></div>`).join('')}</div>` : '<p class="quiet">Nothing yet.</p>'}`;
  const saveBar = '<div class="save-bar"><button class="btn btn-primary" type="submit" form="sf">Save settings</button></div>';
  return `<header class="page-head"><div><h1>Settings</h1></div>${d.demo ? '' : `<div class="actions"><button type="button" class="btn" data-act="open-desk" title="One Claude chat for your whole crew: hire, check and change anyone by talking">${icon('claude')}Orbit in Claude</button></div>`}</header>
  <form id="sf" data-form="settings"></form>
  <div class="settings">
    <section><h2>Your business</h2>${F(biz)}${saveBar}</section>
    <section id="connections"><h2>Connections</h2>${chan}${apify}${access}<p class="meta">Apps like Drive or your CRM are added per crew member: open one and go to Settings.</p></section>
    <section id="limits"><h2>Limits</h2><ul class="limits">${['Spending money or buying anything', 'Your passwords and secrets', 'Your personal accounts and files'].map((t) => `<li>${icon('lock')}<span>${t}</span><span class="meta">Never, whatever anyone says in chat</span></li>`).join('')}</ul></section>
    ${appear}
    <section id="advanced"><h2>Advanced</h2>
      ${advLink('/abilities', 'Abilities by crew member', 'every ability, one table')}
      ${advLink('/room', 'Team room', 'what the crew said, in order')}
      ${adv('skills', 'Team skills', skills)}
      ${adv('plan', 'Plan and model defaults', `<p class="meta">Models and the weekly budget are set for each crew member.</p><div class="chips">${emps.map((e) => `<a class="chip" href="/e/${esc(e.id)}/manage">${esc(e.name)}</a>`).join('') || '<span class="quiet">No crew yet.</span>'}</div>`)}
      ${adv('awake', 'Keep awake', F(awake), 'awake')}
      ${adv('compute', 'Extra computing', F(comp), 'compute')}
      ${adv('times', 'Routine times', F(timesB))}
      ${adv('research', 'Research budget', F(research), 'research')}
      ${adv('sites', 'Sites their own scripts may reach', F(sites))}
      ${adv('install', 'About this install', about)}
      ${adv('history', 'History', hist)}
      ${saveBar}</section>
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
  if (a && a.getAttribute('href').startsWith('/') && !a.getAttribute('href').startsWith('/api/') && !a.hasAttribute('download') && !a.hasAttribute('target') && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey) { ev.preventDefault(); go(a.getAttribute('href')); return; }
  const b = ev.target.closest('[data-act]');
  if (!b) return;
  const act = b.dataset.act;
  if (act === 'theme') { setTheme(b.dataset.v); render(true); }
  if (act === 'hide-reach') { store(() => localStorage.setItem('reach-hidden', '1')); render(true); }
  else if (act === 'more') { const body = b.previousElementSibling; body.classList.remove('clamp'); b.remove(); }
  else if (act === 'job') { pickJob(b.dataset.role); }
  else if (act === 'situation') { ev.preventDefault(); S.situation = b.dataset.id || null; S.job = null; delete S.vals.hire; render(true); }
  else if (act === 'name') { (S.vals.hire ||= {}).name = b.dataset.name; render(true); }
  else if (act === 'answer' && S.ob) {
    const q = b.dataset.q, val = b.dataset.v;
    if (b.dataset.multi) { const cur = new Set(S.ob.answers[q] || []); cur.has(val) ? cur.delete(val) : cur.add(val); S.ob.answers[q] = [...cur]; }
    else S.ob.answers[q] = S.ob.answers[q] === val ? '' : val;
    keepTyped(); render(false);
  }
  else if (act === 'ob-restart') { ev.preventDefault(); S.ob = null; S.job = null; render(true); }
  else if (act === 'ob-back' && S.ob) { if (S.ob.stage === 'card') S.ob.qi = Math.max(0, (S.ob.questions || []).length - 1); S.ob.stage = S.ob.stage === 'card' ? 'questions' : 'basics'; render(true); }
  else if (act === 'q-next' && S.ob) { keepTyped(); S.ob.qi = Math.min((S.ob.qi || 0) + 1, (S.ob.questions || []).length - 1); render(false); }
  else if (act === 'q-prev' && S.ob) { keepTyped(); S.ob.qi = Math.max((S.ob.qi || 0) - 1, 0); render(false); }
  else if (act === 'ob-edit' && S.ob) { keepCard(); const E = (S.ob.editing ||= {}); E[b.dataset.k] = !E[b.dataset.k]; render(false); }
  else if (act === 'ob-more' && S.ob) { S.ob.more = !S.ob.more; render(false); }
  else if (act === 'ob-review' && S.ob) { keepCard(); S.ob.review = true; render(true); }
  else if (act === 'ob-unreview' && S.ob) { S.ob.review = false; render(true); }
  else if (act === 'ob-access' && S.ob) { const a = new Set(S.ob.edit.access); a.has(b.dataset.k) ? a.delete(b.dataset.k) : a.add(b.dataset.k); S.ob.edit.access = [...a]; keepCard(); render(false); }
  else if (act === 'ob-routine' && S.ob) { S.ob.edit.routines[b.dataset.k] = !S.ob.edit.routines[b.dataset.k]; keepCard(); render(false); }
  else if (act === 'ob-budget' && S.ob) { S.ob.edit.budget = b.dataset.k; keepCard(); render(false); }
  else if (act === 'open-claude') { openClaude(b.dataset.emp, b); }
  else if (act === 'try-ask') { askInClaude(b.dataset.emp, b.dataset.text, b); }
  else if (act === 'try-next') { S.tryIdx[b.dataset.emp] = (S.tryIdx[b.dataset.emp] || 0) + 1; render(false); }
  else if (act === 'chips-more') { S.chipsAll = S.chipsAll === b.dataset.emp ? null : b.dataset.emp; render(false); }
  else if (act === 'metrics-refresh') { try { S.metrics = await api('/api/metrics'); render(false); toast('Refreshed'); } catch (err) { toast(err.message, 'err'); } }
  else if (act === 'needs-all') { S.needsAll = !S.needsAll; render(false); }
  else if (act === 'ask-answer') {
    const { emp, id, answer } = b.dataset, name = (empById(emp) || { name: 'them' }).name;
    S.gone.add(id); render(false);                       // the card leaves at once; it comes back if the answer didn't go through
    try { await api('/api/ask/answer', { employee: emp, id, answer }); toast(`Sent to ${name}`); await refresh(false); }
    catch (err) { S.gone.delete(id); toast(err.message, 'err'); render(false); }
  }
  else if (act === 'open-desk') {
    api('/api/desk', {}).then((r) => {
      if (r.opened) toast(r.new ? 'Orbit\'s chat is opening in Claude. Press Enter there once: it sets itself up.' : 'Opening Orbit\'s chat in Claude.');
      else { window.location.href = r.link; }
    }).catch((e) => toast(e.message, 'err'));
  }
  else if (act === 'open-browser') {
    api('/api/browser', { employee: b.dataset.emp }).then(() => toast('Their browser window is open: sign them in there, then close it or leave it.'))
      .catch((e) => toast(e.message, 'err'));
  }
  else if (act === 'connector') {
    b.disabled = true;
    await order({ kind: 'connector', employee_id: b.dataset.emp, ref: b.dataset.ref, name: b.dataset.name, off: !!b.dataset.off });
    const q = ((S.conn || {})[b.dataset.emp] || {}).q || ''; delete S.conn[b.dataset.emp]; loadConnectors(b.dataset.emp, q);
  }
  else if (act === 'update-later') { await api('/api/update', { action: 'dismiss' }); S.data = await api('/api/state'); render(true); }
  else if (act === 'update-now') {
    b.disabled = true; b.textContent = 'Updating…';
    try { const r = await api('/api/update', {}); toast(r.message); setTimeout(() => location.reload(), 9000); }
    catch (e) { toast(e.message, 'err'); b.disabled = false; b.textContent = 'Update now'; }
  }
  else if ((act === 'br-site' || act === 'ob-site') && b.dataset.d) {
    const st = act === 'br-site' ? S.browserEdit : S.ob.edit; const set = new Set(act === 'br-site' ? st.sites : st.browser);
    set.has(b.dataset.d) ? set.delete(b.dataset.d) : set.add(b.dataset.d);
    if (act === 'br-site') st.sites = [...set]; else { keepCard(); st.browser = [...set]; }
    render(true);
  }
  else if (act === 'br-add' || act === 'ob-add') {
    const inp = document.querySelector(`[data-site-input="${act === 'br-add' ? 'br' : 'ob'}"]`);
    const d = (inp && inp.value || '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0];
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(d)) { toast('Type a site like etsy.com'); return; }
    if (act === 'br-add') S.browserEdit.sites = [...new Set([...S.browserEdit.sites, d])]; else { keepCard(); S.ob.edit.browser = [...new Set([...(S.ob.edit.browser || []), d])]; }
    render(true);
  }
  else if (act === 'br-approval') { S.browserEdit.approval = b.dataset.v; render(true); }
  else if (act === 'ob-conn') { keepCard(); const w = new Set(S.ob.edit.connectors || []); w.has(b.dataset.id) ? w.delete(b.dataset.id) : w.add(b.dataset.id); S.ob.edit.connectors = [...w]; render(false); }
  else if (act === 'ob-with') { keepCard(); const w = new Set(S.ob.edit.with || []); w.has(b.dataset.id) ? w.delete(b.dataset.id) : w.add(b.dataset.id); S.ob.edit.with = [...w]; render(false); }
  else if (act === 'ob-autonomy') { keepCard(); S.ob.edit.autonomy = !!b.dataset.v; render(false); }
  else if (act === 'ob-approval') { keepCard(); S.ob.edit.approval = b.dataset.v; render(false); }
  else if (act === 'br-save') {
    const st = S.browserEdit;
    await order({ kind: 'set_browser', employee_id: b.dataset.emp, sites: st.sites, approval: st.approval });
    S.browserEdit = null;
  }
  else if (act === 'close-launch') { S.launched = null; const l = document.getElementById('launch-layer'); if (l) l.remove(); }
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
    if (b.dataset.job) body.job = b.dataset.job;
    if (b.dataset.kind === 'set_autonomy' || b.dataset.kind === 'set_cloud') body.on = !!b.dataset.on;
    b.disabled = true; await order(body); b.disabled = false; schedule();
  }
  else if (act === 'plan-change') {
    S.vals['message:' + b.dataset.emp] = { text: 'About your plan: ' }; go(`/e/${b.dataset.emp}/chat`);
    setTimeout(() => { const t = $('#composer-' + b.dataset.emp); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } }, 50);
  }
  else if (act === 'share-prepare') {
    const emp = b.dataset.emp; S.share = { ...(S.share || {}), [emp]: { stage: 'busy' } }; render(false);
    try { const r = await api('/api/share/prepare', { employee: emp }); S.share[emp] = { stage: 'draft', draft: r }; }
    catch (err) { delete S.share[emp]; toast(err.message, 'err'); }
    render(false);
  }
  else if (act === 'share-reset') { delete (S.share || {})[b.dataset.emp]; render(false); }
  else if (act === 'share-publish') {
    b.disabled = true;
    try {
      const r = await api('/api/order', { kind: 'publish_role', role: b.dataset.role }), out = r.message || {};
      const emp = Object.keys(S.share || {}).find((k) => S.share[k].rid === b.dataset.role);
      if (emp) S.share[emp].published = out;
      if (out.url) window.open(out.url, '_blank', 'noopener');
      if (!out.pr) { const a = document.createElement('a'); a.href = `/api/role/${b.dataset.role}.orbit-role.zip`; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); }
      toast(out.how || 'Shared');
    } catch (err) { toast(err.message, 'err'); }
    b.disabled = false; render(false);
  }
  else if (act === 'preset') { await order({ kind: 'set_abilities', employee_id: b.dataset.emp, preset: b.dataset.preset }); if (S.detailId === b.dataset.emp) await loadDetail(b.dataset.emp); render(true); }
  else if (act === 'retire') {
    if (confirm(`Retire ${b.dataset.name}? They stop working; their folder and memory are kept on this ${MAC()}.`)) { await order({ kind: 'retire', employee_id: b.dataset.emp }); go('/team'); }
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
  if (ev.target.matches && ev.target.matches('[data-xp-file]') && ev.target.files[0]) {
    const box = document.getElementById('xp-text'); box.value = await ev.target.files[0].text();
    const t = document.getElementById('xp-title'); if (t && !t.value) t.value = ev.target.files[0].name.replace(/\.[^.]+$/, '');
    return;
  }
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
  const f = ev.target.form && ev.target.form.dataset.form ? ev.target.form : ev.target.closest('form[data-form]');   // fields can sit outside their form (form="…")
  if (!f || !ev.target.name) return;
  const key = f.dataset.form + (f.dataset.emp ? ':' + f.dataset.emp : '') + (f.dataset.form === 'skill' ? ':' + f.dataset.where + ':' + f.dataset.name : '');
  const vals = (S.vals[key] ||= {});
  if (ev.target.type === 'checkbox') vals[ev.target.name] = [...f.elements].filter((x) => x.name === ev.target.name && x.checked).map((x) => x.value);
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
    } else if (kind === 'basics') {
      const sel = S.roles.roles.find((x) => x.id === S.job) || {};
      const h = (S.vals.hire ||= {});
      h.name = (fd.get('name') || '').trim(); h.role = (fd.get('role') || sel.role || '').trim(); h.scope = (fd.get('scope') || sel.scope || '').trim();
      S.ob = { job: S.job, stage: 'asking', answers: {} }; render(true);
      try {
        const q = await api('/api/onboard/questions', { name: h.name, role: h.role, scope: h.scope });
        Object.assign(S.ob, { stage: 'questions', intro: q.intro, questions: q.questions || [] });
      } catch (e) { S.ob.stage = 'basics'; toast(e.message); }
      render(true).then(() => { const x = $('.interview, .hire-bar'); if (x) x.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    } else if (kind === 'interview') {
      const h = S.vals.hire || {}, ob = S.ob;
      if (f.dataset.from === 'hire' && (ob.qi || 0) < (ob.questions || []).length - 1) { keepTyped(); ob.qi = (ob.qi || 0) + 1; render(true); return; }   // Enter on an early question means Next
      for (const q of ob.questions) {
        if (q.type === 'text') ob.answers[q.id] = (fd.get(q.id) || '').trim();
        else ob.answers[q.id + '__other'] = (fd.get(q.id + '__other') || '').trim();
      }
      const answers = ob.questions.map((q) => { const a = ob.answers[q.id], o = ob.answers[q.id + '__other'];
        return { q: q.text, a: [].concat(a || []).concat(o ? [o] : []).join(', ') }; });
      ob.stage = 'composing'; render(true);
      try {
        const c = await api('/api/onboard/card', { name: h.name, role: h.role, scope: h.scope, answers });
        const ids = new Set(c.abilities || []);
        ob.card = c; ob.stage = 'card';
        try { ob.conn = (await api(`/api/connectors?role=${encodeURIComponent(S.job || '')}&text=${encodeURIComponent((c.role || '') + ' ' + (c.scope || ''))}`)).suggested || []; } catch (err) { ob.conn = []; }
        ob.edit = { role: c.role || h.role, scope: c.scope || h.scope, routines: { ...(c.routines || {}) }, budget: c.budget || 'regular', model: c.model || 'sonnet',
          access: ACCESS.filter(([k, , a]) => k !== 'brief' && a.some((x) => ids.has(x))).map(([k]) => k),
          browser: SITES.filter(([l]) => (c.access || []).some((a) => a.kind === 'post_with_approval' && new RegExp('\\b' + l + '\\b', 'i').test(`${a.site || ''} ${a.what || ''}`))).map(([, d]) => d),
          approval: 'each', autonomy: true };   // the promise is an employee who gets on with it; owners can pick "checks in"
      } catch (e) { ob.stage = 'questions'; toast(e.message); }
      render(true).then(() => { const x = $('.idcard, .interview'); if (x) x.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    } else if (kind === 'hire') {
      const h = S.vals.hire || {}, ob = S.ob || {}, ed = ob.edit || {}, c = ob.card || {};
      const picked = new Set(ed.access || []);
      const routines = Object.entries(ed.routines || {}).filter(([, on]) => on).map(([k]) => k);
      const tpl = (S.roles.roles.find((x) => x.id === S.job) || {}).template;
      const body = { kind: 'hire', template: tpl, name: h.name, role: fd.get('role') || ed.role || h.role, scope: fd.get('scope') || ed.scope || h.scope,
        supervisor: S.data.me, model: ed.model || 'sonnet',
        abilities: ALWAYS.concat(...ACCESS.filter(([k]) => picked.has(k) && k !== 'brief').map(([, , ids]) => ids), routines),
        card: { ...c, weekly_tokens: { light: 1e6, regular: 3e6, heavy: 8e6 }[ed.budget] || 3e6 } };
      const btn = f.querySelector('[data-hire-label]'); if (btn) { btn.disabled = true; btn.textContent = 'Launching…'; }
      const r = await api('/api/order', body);
      const id = (r.message.match(/\/([a-z0-9-]+)$/) || [])[1];
      if (id && (ed.browser || []).length) await api('/api/order', { kind: 'set_browser', employee_id: id, sites: ed.browser, approval: ed.approval || 'each' });
      if (id && ed.autonomy) await api('/api/order', { kind: 'set_autonomy', employee_id: id, on: true });
      for (const other of (id ? ed.with || [] : [])) await api('/api/order', { kind: 'connect', employee_id: id, other });
      for (const ref of (id ? ed.connectors || [] : [])) await api('/api/order', { kind: 'connector', employee_id: id, ref });
      delete S.vals.hire; S.job = null; S.ob = null;
      S.data = await api('/api/state');
      S.launched = id || null;
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
    } else if (kind === 'experience') {
      const r = await api('/api/order', { kind: 'teach', employee_id: emp, title: fd.get('title') || '', text: fd.get('text') || '' });
      toast(r.message); go(`/e/${emp}`); schedule();
    } else if (kind === 'save-role') {
      const r = await api('/api/order', { kind: 'save_role', employee_id: emp, title: fd.get('title') || '' });
      toast(r.message); S.roles = null;
    } else if (kind === 'share-save') {
      const d = S.share[emp].draft, keep = fd.getAll('skill').map(Number);
      const draft = { title: fd.get('title'), summary: fd.get('summary'), trained_by: fd.get('trained_by'), experience: fd.get('experience'), rules: fd.get('rules'),
        skills: (d.skills || []).map((k, i) => ({ name: k.name, text: fd.get('skill-' + i) || k.text })).filter((k, i) => keep.includes(i)) };
      const r = await api('/api/order', { kind: 'save_role', employee_id: emp, title: draft.title, draft });
      S.roles = null; toast(r.message); await refresh(false);
      const me = S.data.employees.find((x) => x.id === emp);
      S.share[emp] = { stage: 'saved', rid: me ? me.shared_as : '', title: draft.title }; render(false);
    } else if (kind === 'role-import') {
      const file = f.querySelector('input[type=file]').files[0], url = String(fd.get('url') || '').trim();
      if (!file && !url) { toast('Pick a role file or paste its link', 'err'); return; }
      let body = { kind: 'import_role', url };
      if (file) {
        if (file.size > 5000000) { toast('That file is over 5 MB', 'err'); return; }
        body = { kind: 'import_role', data: await new Promise((ok, no) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = no; rd.readAsDataURL(file); }) };
      }
      const r = await api('/api/order', body); toast(r.message); f.reset(); S.roles = await api('/api/roles'); S.situation = 'yours'; render(true);
    } else if (kind === 'conn-search') {
      delete S.conn[emp]; loadConnectors(emp, String(fd.get('q') || '').trim());
    } else if (kind === 'conn-link') {
      const r = await api('/api/order', { kind: 'connector', employee_id: emp, ref: String(fd.get('url') || '').trim(), name: String(fd.get('name') || '').trim() });
      toast(r.message); delete S.conn[emp]; loadConnectors(emp);
    } else if (kind === 'rules') {
      const r = await api(`/api/employee/${emp}/rules`, { text: fd.get('text') || '' });
      toast(r.message); delete S.vals['rules:' + emp]; await loadDetail(emp); render(true);
    } else if (kind === 'settings') {
      const body = { team_name: fd.get('team_name'), about: fd.get('about'), workdays: fd.getAll('workdays'), network_domains: fd.get('network_domains'), jobs: {}, apify: {} };
      for (const k of Object.keys(JOB_LABELS)) body.jobs[k] = fd.get('jobs.' + k);
      body.keep_awake = fd.get('keep_awake'); body.compute = String(fd.get('compute') || '').trim();
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
  const fast = S.data && (Object.keys(S.data.live || {}).length || Object.keys(S.data.calls || {}).length || waitingToPair());
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
window.matchMedia('(max-width: 640px)').addEventListener('change', () => { if (S.data && route().page === 'today') render(false); });   // the orbit has a phone layout
