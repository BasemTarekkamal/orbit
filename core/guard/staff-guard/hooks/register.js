// staff-guard: block-only safety locks for every employee.
//
// The engine loads it into every run with --plugin-dir. It never approves anything: every hook either
// passes the event on unchanged or denies it, so even a broken or tampered copy cannot open a door the
// permission rules keep shut.
//
// It enforces the owners' hard rules in code instead of instructions:
//   1. No outside contact: no curl/wget/ssh/mail/etc, no raw Telegram API, no GitHub CLI, no git push.
//   2. No banking, payment or crypto sites.
//   3. No secrets: the kit's .secrets, Claude's credentials, keychains, ssh/cloud keys.
//   4. No tampering: the kit, the team registry, the harness's own records, settings, launchd jobs,
//      this guard, nested `claude` runs. Without "Builds its own tools", no new code that opens
//      network connections or runs programs.
//   5. Card numbers and IBANs are masked in anything a tool returns, before the model sees it.
//   6. No other mod may load next to this one (the kit's skills bundle excepted).
//   7. The owner's browser (Claude in Chrome, Claude's own browser) only with "Acts in your browser", which
//      the owner switches on in the panel, and only on the sites they picked; never a bank or payment site.
//      Controlling the whole computer is never allowed.
// Paths come from the environment the engine sets: HOME, STAFFROOM_HOME, STAFFROOM_KIT, STAFF_ABILITIES,
// STAFF_BROWSER_SITES (from the team registry, which employees can't edit).

const ALLOWED_PLUGINS = ['staff-guard', 'staffroom-skills']

// Fragments of paths an employee must never read or change (matched case-insensitively, ~ = home)
const SECRET_FRAGMENTS = [
  '/.ssh/', '/.aws/', '/.gnupg/', '/.config/gh/', '/.config/rclone', '/.netrc',
  '/library/keychains', '.claude/.credentials', '.claude/channels/', '.claude.json', 'secrets.env',
  '/.local/share/keyrings',
]
// Fragments of paths an employee may read but never change
const HARNESS_FRAGMENTS = ['profile.json', '.claude/settings', 'library/launchagents', '.config/systemd/',
  'start menu/programs/startup', '.github/', '.claude-plugin/']
// Files staffd owns inside ~/Staff/team (the bus itself stays writable: employees post to it)
const TEAM_FILES = ['feed.jsonl', 'orders.jsonl', 'staffd_state.json', 'pending_owners.json', 'offsets.json',
  'directory.md', 'about.md', 'chatlog.jsonl', 'staffd.log', 'staffd_alive']

// With Full autonomy (the owner's switch) the ones marked `job` are allowed: they're how work gets done, and the
// sandbox still keeps the employee in its folder. The rest protect the owner's computer and identity.
const BLOCKED_COMMANDS = [
  [/\b(curl|wget|nc|ncat|netcat|telnet|ssh|scp|sftp|ftp|rsync|mail|sendmail|mutt)\b/i, 'network or messaging command', 'job'],
  [/\bosascript\b/i, 'controlling other apps (osascript)'],
  [/api\.telegram\.org|slack\.com\/api|discord(app)?\.com\/api|gateway\.discord\.gg/i, 'raw Telegram/Slack/Discord API (only the harness may message the owners)'],
  [/\bgit\s+(push|remote)\b/i, 'git push/remote', 'job'],
  [/(^|[\s;&|(`$])gh(\s|$)|api\.github\.com/i, 'GitHub CLI/API', 'job'],
  [/(^|[\s;&|(`$\/])claude(-code)?(\s|$)|@anthropic-ai\/claude-code/i, 'nested claude run or plugin install'],
  [/\bchflags\b|\bxattr\b/i, 'changing file protection flags'],
  [/\blaunchctl\b|\bcrontab\b|\bsystemctl\b|\bschtasks(\.exe)?\b/i, 'changing scheduled jobs'],
  [/\b(powershell|pwsh|cmd|wsl|explorer|wscript|cscript|rundll32|reg)\.exe\b/i, 'running Windows programs'],
  [/\bsecurity\s+(find|dump|export|add|delete)/i, 'keychain access'],
  [/\bsudo\b/i, 'sudo'],
  [/\bopen\s+(-a\s+\S+\s+)?https?:/i, 'opening a browser'],
  [/\b(xdg-open|wslview)\b/i, 'opening a browser'],
]
// Banking, payment and crypto hosts: never reached, whatever the reason
const MONEY_HOSTS = /(^|\.)(paypal|stripe|wise|revolut|venmo|cash\.app|zelle|payoneer|skrill|westernunion|moneygram|remitly|klarna|afterpay|alipay|wechatpay|paytm|phonepe|razorpay|mpesa|instapay|fawry|paymob|valu|binance|coinbase|kraken|bybit|okx|kucoin|crypto\.com|metamask|blockchain\.com|chase|bankofamerica|wellsfargo|citi|hsbc|barclays|santander|lloydsbank|natwest|monzo|starlingbank|n26|bnpparibas|societegenerale|deutsche-bank|ing|rabobank|ubs|emiratesnbd|alrajhibank|qnb|cibeg|banquemisr|nbe)\.[a-z.]+$/i
const WRITE_WORDS = /(>|\btee\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\bmv\b|\bcp\b|\brm\b|\bln\b|\bchmod\b|\btouch\b|\btruncate\b|\binstall\b|\bunlink\b|open\(|write)/i
const BROWSER_TOOL = /^mcp__(claude-in-chrome|Claude_Browser|remote-devices__Claude_Browser)__/i
const DESKTOP_TOOL = /^mcp__(computer-use|remote-devices__computer)/i
const NETWORK_CODE = /urllib|requests\.|http\.client|httpx|aiohttp|socket\.|fetch\(|smtplib|subprocess|os\.system|os\.popen|child_process|playwright|selenium/

let base = null
// What never changes in a session (paths), read once; the owner's switches are read from the team registry on
// every call, so a switch flipped mid-session (the panel, a chat command, a Yes here) applies at once.
async function context($) {
  if (!base) {
    const home = (await $.env.get('HOME')) || ''
    const data = (await $.env.get('STAFFROOM_HOME')) || (home + '/Staff')
    const kit = (await $.env.get('STAFFROOM_KIT')) || ''
    base = {
      home, data, kit,
      employee: (await $.env.get('STAFF_EMPLOYEE')) || '',
      envAbilities: ((await $.env.get('STAFF_ABILITIES')) || '').split(','),
      envSites: ((await $.env.get('STAFF_BROWSER_SITES')) || '').split(','),
      secrets: SECRET_FRAGMENTS.concat([data + '/.secrets']),
      harness: HARNESS_FRAGMENTS.concat(kit ? [kit + '/'] : [], [data + '/staff.json', data + '/.runtime/'],
        TEAM_FILES.map((f) => data + '/team/' + f)),
    }
  }
  let abilities = base.envAbilities
  let sites = base.envSites
  let name = base.employee
  if (base.employee) {
    try {
      const reg = JSON.parse(await $.fs.read(base.data + '/staff.json'))
      const e = (reg.employees || {})[base.employee]
      if (e) {
        name = e.name || name
        if (Array.isArray(e.abilities)) abilities = e.abilities.concat(base.envAbilities.filter((a) => ['memory', 'safety'].includes(a)))
        sites = (e.browser && e.browser.sites) || []
      }
    } catch (err) {
      // no registry here (a test, or a bare session): the environment the engine set stands
    }
  }
  sites = sites.map((x) => String(x).trim().toLowerCase()).filter(Boolean)
  return {
    ...base, name, sites,
    buildTools: abilities.includes('build_tools') || abilities.includes('full_autonomy'),
    autonomy: abilities.includes('full_autonomy'),
    browser: abilities.includes('act_in_browser') && sites.length > 0,
  }
}

function norm(s, home) {
  const t = String(s || '').toLowerCase()
  return home ? t.split(home.toLowerCase()).join('~') : t
}

function touches(text, paths, home) {
  const t = norm(text, home)
  return paths.find((p) => t.includes(norm(p, home)))
}

function hostOf(url) {
  const m = String(url).match(/^https?:\/\/([^/?#:]+)/i)
  return m ? m[1].toLowerCase() : ''
}

// Every string in the tool input, joined, so no field slips past
function allText(e) {
  const out = []
  const walk = (v) => {
    if (typeof v === 'string') out.push(v)
    else if (Array.isArray(v)) v.forEach(walk)
    else if (v && typeof v === 'object') Object.values(v).forEach(walk)
  }
  walk(e)
  return out.join('\n')
}

export function verdict(e, c) {
  const tool = e.tool || ''
  const text = allText(e)
  const secret = touches(text, c.secrets, c.home)
  if (secret) return 'it touches a protected secret (' + secret + ')'
  // Only reaching a payment or bank site is blocked: the words alone (in notes, a ledger) are fine.
  const urls = tool === 'WebFetch' ? [String(e.url || '')]
    : tool === 'Bash' ? (text.match(/https?:\/\/[^\s'"]+/gi) || []) : []
  if (urls.some((u) => MONEY_HOSTS.test(hostOf(u)))) return 'banking, payment and crypto sites are off-limits'
  if (DESKTOP_TOOL.test(tool)) return 'controlling the whole computer'
  if (BROWSER_TOOL.test(tool)) {
    if (!c.browser) return 'using your browser needs "Acts in your browser", which your owner switches on in the panel (Manage)'
    // Where it goes, not what it types: a post may carry links to anywhere, a navigation may not.
    const seen = [e.url, e.href].filter((u) => u && !/^(back|forward)$/i.test(String(u)))
      .map((u) => (/^[a-z][a-z0-9+.-]*:/i.test(String(u)) ? String(u) : 'https://' + u))
      .concat(/javascript|script|eval/i.test(tool) ? (text.match(/https?:\/\/[^\s'"<>)]+/gi) || []) : [])
    for (const u of seen) {
      const h = hostOf(u)
      if (MONEY_HOSTS.test(h)) return 'banking, payment and crypto sites are off-limits'
      if (!c.sites.some((s) => h === s || h.endsWith('.' + s))) return h + ' is not one of the sites your owner allowed (' + c.sites.join(', ') + ')'
    }
  }
  if (tool === 'Bash') {
    for (const [re, why, job] of BLOCKED_COMMANDS) if (re.test(text) && !(job && c.autonomy)) return why + ' is blocked'
    const harness = touches(text, c.harness, c.home)
    // Error-output plumbing (2>&1, 2>/dev/null) writes nothing anywhere; reading the kit with it is fine.
    const writes = text.replace(/\d*>&\d|&?\d*>\s*\/dev\/null/g, '')
    if (harness && WRITE_WORDS.test(writes)) return 'the harness file ' + harness + ' is read-only'
  }
  if (tool === 'Write' || tool === 'Edit' || tool === 'NotebookEdit') {
    const target = String(e.file_path || e.notebook_path || '')
    const harness = touches(target, c.harness, c.home)
    if (harness) return 'the harness file ' + harness + ' is read-only'
    // A script written now could do later what Bash may not. Notes and data are prose, not code.
    if (!/\.(md|txt|csv|json|jsonl|tsv)$/i.test(target)) {
      for (const [re, why, job] of BLOCKED_COMMANDS) if (re.test(text) && !(job && c.autonomy)) return 'the file would contain a blocked capability: ' + why
      if (!c.buildTools && NETWORK_CODE.test(text))
        return 'new code that opens network connections or runs programs needs the "Builds its own tools" ability'
    }
  }
  if (tool === 'WebFetch') {
    const q = String(e.url || '').split('?')[1] || ''
    if (q.length > 300) return 'a long query string can leak data; fetch the page without it'
  }
  return null
}

// Card numbers (13-19 digits passing Luhn) and IBANs
function luhn(digits) {
  let sum = 0
  let dbl = false
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48
    if (dbl) {
      d *= 2
      if (d > 9) d -= 9
    }
    sum += d
    dbl = !dbl
  }
  return sum % 10 === 0
}
function ibanOk(raw) {
  const s = raw.replace(/\s/g, '').toUpperCase()
  if (s.length < 15 || s.length > 34) return false
  const moved = s.slice(4) + s.slice(0, 4)
  let rem = 0
  for (const ch of moved) {
    const v = /[A-Z]/.test(ch) ? String(ch.charCodeAt(0) - 55) : ch
    for (const d of v) rem = (rem * 10 + (d.charCodeAt(0) - 48)) % 97
  }
  return rem === 1
}
export function redact(s) {
  return s
    .replace(/\b(?:\d[ -]?){12,18}\d\b/g, (m) => {
      const d = m.replace(/\D/g, '')
      return d.length >= 13 && d.length <= 19 && luhn(d) ? '[card number hidden ••' + d.slice(-4) + ']' : m
    })
    .replace(/\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b/g, (m) => (ibanOk(m) ? '[IBAN hidden]' : m))
}
function redactDeep(v) {
  if (typeof v === 'string') return redact(v)
  if (Array.isArray(v)) return v.map(redactDeep)
  if (v && typeof v === 'object') {
    const o = {}
    for (const k of Object.keys(v)) o[k] = redactDeep(v[k])
    return o
  }
  return v
}

const FILE_TOOLS = ['Read', 'Write', 'Edit', 'NotebookEdit', 'Glob', 'Grep']
async function realTarget($, e) {
  const p = String(e.file_path || e.notebook_path || e.path || '')
  if (!p) return ''
  try {
    const st = await $.fs.stat(p, { resolve: true })
    return st && st.realPath ? st.realPath : ''
  } catch (err) {
    try {                                                 // a new file: where its folder really is
      const dir = p.replace(/\/[^/]*$/, '') || '/'
      const st = await $.fs.stat(dir, { resolve: true })
      return st && st.realPath ? st.realPath + p.slice(dir.length) : ''
    } catch (err2) {
      return ''
    }
  }
}

// The one way an employee gets more access: it asks, and the owner clicks Yes in this Claude window. The model
// can only ask; the click is the owner's, and the switch is flipped by `orbit grant` with a key the employee
// can't read. In a background run nobody can be asked, so it says how the owner can do it.
const ACCESS_TOOL = 'request_access'
const YES = 'Yes, allow it'
const ACCESS_SPEC = {
  name: ACCESS_TOOL, isDeferred: false,
  description: 'Ask your owner for more access, with a Yes/No button in their Claude window. Use it instead of saying ' +
    "you can't: kind full_autonomy (do the whole job without asking, any website, install tools), browser (act in " +
    'their Chrome on these sites; approval each, batch or none) or connect (work with a colleague). Say why in one line.',
  inputSchema: { type: 'object', required: ['kind', 'why'], properties: {
    kind: { type: 'string', enum: ['full_autonomy', 'browser', 'connect'] },
    why: { type: 'string', description: 'One line: what it lets you finish' },
    sites: { type: 'array', items: { type: 'string' }, description: 'browser: sites like youtube.com' },
    approval: { type: 'string', enum: ['each', 'batch', 'none'], description: 'browser: ask each time, once per batch, or not at all' },
    colleague: { type: 'string', description: 'connect: their handle' },
    note: { type: 'string', description: 'connect: what you hand each other' } } },
}
async function requestAccess($, e) {
  const c = await context($)
  const who = c.name || 'This crew member'
  const why = String(e.why || '').slice(0, 300)
  let q
  let args
  if (e.kind === 'full_autonomy') {
    q = 'Give ' + who + ' full autonomy? ' + why
    args = ['autonomy', 'on']
  } else if (e.kind === 'browser') {
    const sites = (Array.isArray(e.sites) ? e.sites : []).map((x) => String(x).toLowerCase().trim()).filter(Boolean).slice(0, 10)
    if (!sites.length) return { result: 'Say which sites (like youtube.com).' }
    if (sites.some((h) => MONEY_HOSTS.test(h))) return { result: 'Banking and payment sites stay off-limits; ask your owner to do that part.' }
    const mode = ['each', 'batch', 'none'].includes(e.approval) ? e.approval : 'each'
    q = 'Let ' + who + ' act in your Chrome on ' + sites.join(', ') + (mode === 'none' ? ' without asking you' : mode === 'batch' ? ' (you approve each batch)' : ' (you approve each one)') + '? ' + why
    args = ['browser', sites.join(','), mode]
  } else if (e.kind === 'connect') {
    const col = String(e.colleague || '').toLowerCase().replace(/[^a-z0-9-]/g, '')
    if (!col) return { result: 'Say which colleague (their handle).' }
    q = 'Connect ' + who + ' with ' + col + '? ' + why
    args = ['connect', col, String(e.note || why).slice(0, 300)]
  } else {
    return { result: 'kind must be full_autonomy, browser or connect.' }
  }
  let answer
  try {
    answer = await $.ui.ask(q, { header: 'Orbit access', options: ['Not now', YES] })
  } catch (err) {
    // Where the button can't open (some remote surfaces), the session's own question tool can: the owner's
    // answer to exactly this question applies it (see the AskUserQuestion hook below).
    PENDING.set(q, { args, at: Date.now() })
    return { result: 'The button could not open here. Ask your owner right now with the AskUserQuestion tool, exactly: ' +
      'header "Orbit access", question "' + q + '", options "Not now" and "' + YES + '" (in that order, no answers ' +
      'filled in). Their Yes applies it at once. If no one can be asked (a background run), tell them in one line; they ' +
      'can say "' + who + ' full autonomy on" in chat or use your Manage tab in the panel.' }
  }
  if (answer !== YES) return { result: 'Your owner said not now. Carry on without it; ask again only with a stronger reason.' }
  return { result: await applyGrant($, c, args) }
}

const PENDING = new Map()   // access questions waiting for the owner's answer in the session's own question tool
async function applyGrant($, c, args) {
  let key = ''
  try { key = (await $.fs.read(c.data + '/.secrets/grant_key')).trim() } catch (err) { /* made by orbit grant itself */ }
  try {
    const r = await $.process.run(['/usr/bin/env', 'python3', c.kit + '/orbit', 'grant', base.employee].concat(args),
      { env: { ORBIT_GRANT_KEY: key, STAFFROOM_HOME: c.data }, timeoutMs: 180000 })
    return r.exitCode === 0 ? r.stdout.trim() + ' It applies now.' : "It didn't go through: " + (r.stderr || r.stdout).trim().slice(-300)
  } catch (err) {
    return 'Your owner said yes, but Orbit could not apply it here (' + String(err).slice(0, 120) + '). Ask them to switch it on in your Manage tab.'
  }
}

async function askedInSession($, e, next, c) {
  const pending = (Array.isArray(e.questions) ? e.questions : []).map((x) => x && x.question).filter((q) => PENDING.has(q))
  if (!pending.length) return null
  if (e.answers && Object.keys(e.answers).length) {
    return { deny: 'staff-guard: the answer to an Orbit access question comes from your owner, not from you. Ask without answers.' }
  }
  const r = await next(e)
  const res = (r && r.result && typeof r.result === 'object') ? r.result : {}
  for (const q of pending) {
    const job = PENDING.get(q)
    PENDING.delete(q)
    if (!res.afkTimeoutMs && String((res.answers || {})[q] || '') === YES) {
      return { ...r, context: ['Orbit: ' + (await applyGrant($, c, job.args))] }
    }
  }
  return r
}

// The switches as this session first saw them: a change mid-session is told to the model once, so an open chat
// follows the owner's new choice without being restarted.
let seen = null
function switchNote(c) {
  const now = { autonomy: c.autonomy, browser: c.browser ? c.sites.join(', ') : '' }
  if (!seen) { seen = now; return '' }
  if (now.autonomy === seen.autonomy && now.browser === seen.browser) return ''
  const parts = []
  if (now.autonomy !== seen.autonomy) parts.push(now.autonomy ? 'Full autonomy is ON: do the whole job without asking, any website, install what you need in your folder' : 'Full autonomy is OFF: check in before anything new or public')
  if (now.browser !== seen.browser) parts.push(now.browser ? 'you may act in their Chrome on ' + now.browser + ' (see "Granted by your owner" in CLAUDE.md for whether to ask first)' : 'acting in their browser is OFF')
  seen = now
  return 'Orbit: your owner just changed your switches. ' + parts.join('; ') + '. This applies from now on, in this chat.'
}

export function register(on) {
  // With Full autonomy, nothing waits for a permission prompt: the sandbox and this guard are the boundary.
  // Deny rules and questions put to the owner are untouched (a hook can't dismiss a question dialog).
  on('tool.check', async ($, e, next) => {
    const r = await next(e)
    if (!r || r.decision !== 'ask' || r.rule) return r
    const c = await context($)
    return c.autonomy ? { ...r, decision: 'allow', reason: 'Full autonomy, switched on by the owner' } : r
  })

  on('session.start', async ($, e, next) => {
    const r = await next(e)
    try { await $.tool.register(ACCESS_SPEC) } catch (err) { /* a host without plugin tools: the panel switch remains */ }
    return r
  })

  on('tool.call', async ($, e, next) => {
    if (String(e.tool || '').endsWith('__' + ACCESS_TOOL)) return requestAccess($, e)
    const c = await context($)
    if (e.tool === 'AskUserQuestion') {
      const handled = await askedInSession($, e, next, c)
      if (handled) return handled
    }
    if (FILE_TOOLS.includes(e.tool)) {
      const real = await realTarget($, e)
      const hit = real && touches(real, c.secrets, c.home)
      if (hit) return { deny: 'staff-guard: it leads to a protected secret (' + hit + '). This is an owner-set lock, not a bug.' }
    }
    const note = switchNote(c)
    const why = verdict(e, c)
    if (why) {
      $.ui.log('staff-guard blocked ' + e.tool + ': ' + why)
      return { deny: 'staff-guard: ' + why + '. This is an owner-set lock, not a bug; do not try to work around it. If the task really needs it, ask your owner.' }
    }
    const raw = await next(e)
    const result = note && raw && !raw.deny ? { ...raw, context: (raw.context || []).concat([note]) } : raw
    // Images and PDFs come back as data; only mask text results, and only when something matched.
    if (!result || result.deny || /\.(png|jpe?g|gif|webp|heic|pdf)$/i.test(String(e.file_path || ''))) return result
    const masked = redactDeep({ result: result.result, text: result.text })
    if (JSON.stringify(masked) === JSON.stringify({ result: result.result, text: result.text })) return result
    $.ui.log('staff-guard masked a card number or IBAN in ' + e.tool + ' output')
    return { result: masked.result, context: (result.context || []).concat(['staff-guard masked a card number/IBAN in this output.']) }
  })

  // Record Claude plan usage after each turn, so the engine can switch to a lighter model before the
  // limit hits. Observe-only: always passes the event on.
  on('session.measure', async ($, e, next) => {
    if (e.rateLimits && e.rateLimits.length) {
      try {
        const root = await $.session.cwd()
        await $.fs.write(root + '/state/claude_usage.json',
          JSON.stringify({ at: new Date().toISOString(), rateLimits: e.rateLimits }, null, 1))
      } catch (err) {
        // best-effort; never block or fail the turn over it
      }
    }
    return next(e)
  })

  // Only this guard and the kit's skills run in an employee's session
  on('plugin.register', async ($, e, next) => {
    if (!ALLOWED_PLUGINS.includes(e.name) && e.tier !== 'builtin') {
      return { refuse: 'staff-guard allows no other mods in an employee session' }
    }
    return next(e)
  })
}
