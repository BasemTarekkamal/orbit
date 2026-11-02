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

let ctx = null
async function context($) {
  if (ctx) return ctx
  const home = (await $.env.get('HOME')) || ''
  const data = (await $.env.get('STAFFROOM_HOME')) || (home + '/Staff')
  const kit = (await $.env.get('STAFFROOM_KIT')) || ''
  const abilities = ((await $.env.get('STAFF_ABILITIES')) || '').split(',')
  const sites = ((await $.env.get('STAFF_BROWSER_SITES')) || '').split(',').map((x) => x.trim().toLowerCase()).filter(Boolean)
  ctx = {
    home,
    secrets: SECRET_FRAGMENTS.concat([data + '/.secrets']),
    harness: HARNESS_FRAGMENTS.concat(kit ? [kit + '/'] : [], [data + '/staff.json', data + '/.runtime/'],
      TEAM_FILES.map((f) => data + '/team/' + f)),
    buildTools: abilities.includes('build_tools') || abilities.includes('full_autonomy'),
    autonomy: abilities.includes('full_autonomy'),
    browser: abilities.includes('act_in_browser') && sites.length > 0,
    sites,
  }
  return ctx
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

export function register(on) {
  on('tool.call', async ($, e, next) => {
    const why = verdict(e, await context($))
    if (why) {
      $.ui.log('staff-guard blocked ' + e.tool + ': ' + why)
      return { deny: 'staff-guard: ' + why + '. This is an owner-set lock, not a bug; do not try to work around it. If the task really needs it, ask your owner.' }
    }
    const result = await next(e)
    // Images and PDFs come back as data; only mask text results, and only when something matched.
    if (!result || result.deny || /\.(png|jpe?g|gif|webp|heic|pdf)$/i.test(String(e.file_path || ''))) return result
    const masked = redactDeep({ result: result.result, text: result.text })
    if (JSON.stringify(masked) === JSON.stringify({ result: result.result, text: result.text })) return result
    $.ui.log('staff-guard masked a card number or IBAN in ' + e.tool + ' output')
    return { result: masked.result, context: ['staff-guard masked a card number/IBAN in this output.'] }
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
