"""The control panel: a small web page on this Mac (http://127.0.0.1:7317) where owners see and run
the team. No accounts, no cloud, nothing to install. Started by staffd in a thread; `staff panel`
opens it in the browser.

Pages: Team (cards, hire, team room, orders, Telegram sign-ups), Abilities (the checkbox matrix with
Default and Super agent), Settings. Every change goes through orders.py and is logged.

Security: listens on 127.0.0.1 only; a secret token (in ~/Staff/.secrets/panel_token, which
employees can't read) is exchanged once for an HttpOnly SameSite=Strict cookie; the Host and Origin
headers must be this Mac (no DNS rebinding, no cross-site posts). Employees' shells can't reach
localhost (sandbox) and the toolbelt gateways refuse local addresses.
"""
from __future__ import annotations

import datetime as dt
import hmac
import html
import json
import os
import secrets
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
import abilities  # noqa: E402
import engine  # noqa: E402
import hire  # noqa: E402
import orders  # noqa: E402
import team  # noqa: E402

ABOUT = os.path.join(team.TEAM, "ABOUT.md")
PENDING = os.path.join(team.TEAM, "pending_owners.json")
MODELS = ("opus", "sonnet", "haiku")
e = html.escape


def port() -> int:
    return int(engine.registry().get("panel", {}).get("port", 7317))


def token() -> str:
    t = engine.secret("panel_token")
    if not t:
        os.makedirs(engine.SECRETS, exist_ok=True)
        os.chmod(engine.SECRETS, 0o700)
        t = secrets.token_urlsafe(24)
        p = os.path.join(engine.SECRETS, "panel_token")
        with open(p, "w") as fh:
            fh.write(t)
        os.chmod(p, 0o600)
    return t


def url() -> str:
    return "http://127.0.0.1:%d/?t=%s" % (port(), token())


def daemon_online() -> bool:
    try:
        return time.time() - os.path.getmtime(os.path.join(team.TEAM, "staffd_alive")) < 120
    except OSError:
        return False


def when(ts) -> str:
    if not ts:
        return "—"
    try:
        d = dt.datetime.fromisoformat(str(ts).replace(" ", "T")[:19])
    except ValueError:
        return e(str(ts))
    today = dt.date.today()
    if d.date() == today:
        return d.strftime("%H:%M")
    if d.date() == today - dt.timedelta(days=1):
        return "yesterday " + d.strftime("%H:%M")
    if d.date() == today + dt.timedelta(days=1):
        return "tomorrow " + d.strftime("%H:%M")
    return d.strftime("%a %d %b %H:%M")


CSS = """
:root{--bg:#f7f6f2;--card:#fff;--text:#1d1d1b;--muted:#6b6a65;--line:#e4e2da;--accent:#2f6b4f;--accent-ink:#fff;
--warn:#a4441c;--chip:#efede6;--focus:#2f6b4f55}
@media (prefers-color-scheme:dark){:root{--bg:#141513;--card:#1d1f1c;--text:#ecebe6;--muted:#9c9b94;--line:#30322e;
--accent:#7cc39c;--accent-ink:#102018;--warn:#f0936a;--chip:#272925;--focus:#7cc39c55}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
a{color:inherit}header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--card)}
header b{font-size:17px}nav a{margin-right:14px;text-decoration:none;color:var(--muted)}nav a.on{color:var(--text);font-weight:600}
main{max-width:1180px;margin:0 auto;padding:18px 16px 60px}h2{font-size:15px;margin:26px 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.between{justify-content:space-between}
.muted{color:var(--muted)}.small{font-size:13px}.chip{display:inline-block;padding:1px 8px;border-radius:99px;background:var(--chip);font-size:12px}
.chip.on{background:var(--accent);color:var(--accent-ink)}.chip.warn{background:var(--warn);color:#fff}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:10px 0;font-size:13px}dt{color:var(--muted)}dd{margin:0}
button,.btn{font:inherit;font-size:13px;padding:5px 11px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--text);cursor:pointer;text-decoration:none;display:inline-block}
button.primary,.btn.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
input,select,textarea{font:inherit;font-size:14px;padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--text);max-width:100%}
textarea{width:100%}:focus-visible{outline:3px solid var(--focus);outline-offset:1px}
form.inline{display:inline}details summary{cursor:pointer}.flash{padding:10px 14px;border-radius:10px;background:var(--chip);margin-bottom:12px}
.flash.err{background:var(--warn);color:#fff}.feed li{list-style:none;border-bottom:1px solid var(--line);padding:10px 0}.feed{padding:0;margin:0}
.feed p{margin:4px 0 0;white-space:pre-wrap}.meter{height:6px;border-radius:9px;background:var(--chip);overflow:hidden;width:120px;display:inline-block;vertical-align:middle}
.meter i{display:block;height:100%;background:var(--accent)}.meter.hot i{background:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
td.c,th.c{text-align:center}.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
.two{display:grid;gap:14px;grid-template-columns:minmax(0,2fr) minmax(0,1fr)}@media (max-width:820px){.two{grid-template-columns:1fr}}
label{display:block;font-size:13px;color:var(--muted);margin:8px 0 3px}
"""

JS = """
// Refresh the page every 20s so the cards stay live, unless you're typing or have something open.
setInterval(function(){var a=document.activeElement;if(a&&/INPUT|TEXTAREA|SELECT/.test(a.tagName))return;
if(document.querySelector('details[open]'))return;if(document.hidden)return;location.replace(location.pathname);},20000);
"""


def page(title, active, body, flash=None, err=False):
    script = JS if active == "team" else ""                 # only the team page refreshes itself
    online = daemon_online()
    u = engine.usage()
    meters = ""
    for k, label in (("five_hour", "5-hour"), ("seven_day", "Weekly")):
        if k in u:
            pct = max(0, min(100, u[k]))
            meters += ' <span class="small muted">%s limit</span> <span class="meter%s" title="%d%% used"><i style="width:%d%%"></i></span>' % (
                label, " hot" if pct >= 80 else "", pct, pct)
    nav = "".join('<a href="%s" class="%s">%s</a>' % (h, "on" if active == k else "", t)
                  for k, h, t in (("team", "/", "Team"), ("abilities", "/abilities", "Abilities"), ("settings", "/settings", "Settings")))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s · %s</title><style>%s</style></head><body><header><div class=row><b>%s</b>"
            "<span class='chip %s'>%s</span>%s</div><nav>%s</nav></header><main>%s%s</main><script>%s</script></body></html>") % (
        e(title), e(engine.registry().get("team_name", "Staffroom")), CSS, e(engine.registry().get("team_name", "Staffroom")),
        "on" if online else "warn", "Running" if online else "Stopped: run `staff start`", meters, nav,
        ('<div class="flash%s" role=status>%s</div>' % (" err" if err else "", e(flash))) if flash else "", body, script)


def hidden(**kw):
    return "".join('<input type=hidden name="%s" value="%s">' % (e(k), e(str(v))) for k, v in kw.items())


def order_form(kind, label, cls="", **kw):
    return '<form method=post action=/order class=inline>%s<button class="%s">%s</button></form>' % (hidden(kind=kind, **kw), cls, e(label))


def card(eid, m):
    emp = engine.employee(eid)
    s = engine.stats(emp)
    paused = m.get("status") == "paused"
    doing = team.DOING.get(eid)
    state = ("Paused", "") if paused else ("Working", "on") if doing else ("Idle", "")
    nj, nwhen = team.next_job(eid) if not paused else (None, None)
    on = len(abilities.effective(eid))
    model = m.get("model") or emp.get("model", "sonnet")
    jobs = "".join('<option value="%s">%s</option>' % (j, e(l)) for j, l in team.JOBS.items())
    models = "".join('<option %s>%s</option>' % ("selected" if x == model else "", x) for x in MODELS)
    return """<div class=card><div class="row between"><div><b>{name}</b><div class="small muted">{role} · reports to {sup}</div></div>
<span class="chip {stc}">{st}</span></div><p class=small>{doing}</p>
<dl><dt>Last run</dt><dd>{last}</dd><dt>Next</dt><dd>{nxt}</dd><dt>Today</dt><dd>{runs}{fail}</dd>
<dt>Plan use</dt><dd>≈${ut:.2f} today · ≈${u7:.2f} 7 days</dd><dt>Abilities</dt><dd>{on} on · <a href="/abilities#{id}">edit</a></dd>
<dt>Model</dt><dd><form method=post action=/order class=inline>{mh}<select name=value aria-label="Model for {name}">{models}</select> <button>Set</button></form></dd></dl>
<div class=row>{pause}<form method=post action=/order class=inline>{jh}<select name=job aria-label="Routine">{jobs}</select> <button>Run now</button></form></div>
<details class="small" style="margin-top:8px"><summary class=muted>Retire…</summary><p class=muted>Stops {name}. Their folder and memory are kept.</p>{retire}</details></div>""".format(
        name=e(m["name"]), role=e(m["role"]), sup=e(m.get("supervisor", "")), st=state[0], stc=state[1], id=e(eid),
        doing=e(doing or ("Paused" if paused else "Nothing running")), last=when(s["last_run"]),
        nxt=("%s · %s" % (e(nj), when(nwhen))) if nj else "—",
        runs="%d run%s" % (s["runs_today"], "" if s["runs_today"] == 1 else "s"),
        fail=(' · <span style="color:var(--warn)">%d failed</span>' % s["failures_today"]) if s["failures_today"] else "",
        ut=s["use_today"], u7=s["use_7d"], on=on, models=models, jobs=jobs,
        mh=hidden(kind="set_field", employee_id=eid, field="model"), jh=hidden(kind="run_job", employee_id=eid),
        pause=order_form("resume" if paused else "pause", "Resume" if paused else "Pause", employee_id=eid),
        retire=order_form("retire", "Retire %s" % m["name"], employee_id=eid))


def team_page(me):
    reg = engine.registry()
    emps = {k: m for k, m in reg.get("employees", {}).items() if m.get("status") != "retired"}
    owners = "".join('<option %s>%s</option>' % ("selected" if o["name"] == me else "", e(o["name"])) for o in reg.get("owners", {}).values())
    hire_f = """<details class=card><summary><b>+ Hire someone</b> <span class="small muted">They start within a minute, with the whole toolbelt.</span></summary>
<form method=post action=/order>{h}<div class=two><div><label for=hn>Name</label><input id=hn name=name required maxlength=60 placeholder="Sara">
<label for=hr>Role</label><input id=hr name=role required maxlength=120 placeholder="Market researcher" style="width:100%">
<label for=hs>Scope: what they own</label><textarea id=hs name=scope rows=3 maxlength=2000 placeholder="Competitors, prices and social media in our market; weekly summary for me"></textarea></div>
<div><label for=hsup>Reports to</label><select id=hsup name=supervisor>{owners}</select><label for=hp>Start as</label>
<select id=hp name=preset><option value=default>Default employee</option><option value=super>Super agent (every ability)</option></select>
<label for=hm>Model</label><select id=hm name=model><option value="">Team default</option>{models}</select></div></div>
<p><button class=primary>Hire</button></p></form></details>""".format(
        h=hidden(kind="hire"), owners=owners, models="".join("<option>%s</option>" % x for x in MODELS))
    cards = "".join(card(k, m) for k, m in emps.items()) or '<p class=muted>Nobody works here yet. Hire your first employee above.</p>'
    act = team.active()
    to = '<option value=team>Whole team</option>' + "".join('<option value="%s">%s</option>' % (e(k), e(m["name"])) for k, m in act.items())
    names = {k: m["name"] for k, m in reg.get("employees", {}).items()}
    feed = "".join("""<li><div class="small muted"><b style="color:var(--text)">{f}</b> → {t} · {w} <span class=chip>{c}</span></div><p>{b}</p></li>""".format(
        f=e(r.get("from_name", "")), t=e("Team" if r.get("to_id") == "team" else names.get(r.get("to_id"), r.get("to_id", ""))),
        w=when(r.get("ts")), c=e(r.get("channel", "")), b=e(r.get("body", "")[:3000])) for r in reversed(team.tail(team.FEED, 60)))
    working = "".join('<p class="small muted">%s is working: %s…</p>' % (e(names.get(k, k)), e(v)) for k, v in team.DOING.items())
    room = """<div class=card><b>Team room</b><form method=post action=/order class=row style="margin:10px 0">{h}
<select name=employee_id aria-label=To>{to}</select><textarea name=text rows=2 required maxlength=4000 aria-label=Message placeholder="Sara, what did our competitors post this week?" style="flex:1;min-width:200px"></textarea>
<button class=primary>Send</button></form>{working}<ul class=feed>{feed}</ul></div>""".format(
        h=hidden(kind="message"), to=to, working=working, feed=feed or '<li class=muted>Nothing said yet. Messages between the team and you appear here.</li>')
    ords = "".join('<li><div class="row between"><span class=small>%s</span><span class="chip %s">%s</span></div><div class="small muted">%s · %s%s</div></li>' % (
        e(o["summary"]), "warn" if o["status"] == "failed" else "", e(o["status"]), e(o["by"]), when(o["ts"]),
        (" · " + e(o["result"])) if o.get("result") else "") for o in reversed(team.tail(team.ORDERS, 25)))
    pend = team.jload(PENDING, {})
    pend_html = ""
    if pend:
        rows = "".join("""<li><div class=small><b>{n}</b> {u} · Telegram id {i} · {a}</div>
<form method=post action=/owner class=row style="margin-top:6px">{h}<input name=name value="{n}" aria-label="Owner name" maxlength=40>
<button class=primary name=do value=approve>Make owner</button><button name=do value=ignore>Ignore</button></form></li>""".format(
            n=e(p.get("name") or "Someone"), u=("@" + e(p["username"])) if p.get("username") else "", i=e(i), a=when(p.get("at")), h=hidden(id=i))
            for i, p in pend.items())
        pend_html = '<div class=card style="margin-top:14px"><b>Messaged your bot</b><p class="small muted">Only owners can talk to the team. Approve someone only if you know them: owners can direct every employee.</p><ul class=feed>%s</ul></div>' % rows
    return "%s<h2>Team</h2><div class=grid>%s</div><h2>Talk</h2><div class=two>%s<div><div class=card><b>Orders</b><ul class=feed>%s</ul></div>%s</div></div>" % (
        hire_f, cards, room, ords or '<li class=muted>No orders yet.</li>', pend_html)


def abilities_page():
    reg = engine.registry()
    emps = [(k, m) for k, m in reg.get("employees", {}).items() if m.get("status") != "retired"]
    if not emps:
        return '<p class=muted>Hire someone first; their abilities appear here.</p>'
    eff = {k: abilities.effective(k) for k, _ in emps}
    head = "".join('<th class=c id="%s">%s</th>' % (e(k), e(m["name"])) for k, m in emps)
    rows = ""
    for g in abilities.groups():
        items = [a for a in abilities.catalog() if a["group"] == g]
        if not items:
            continue
        rows += '<tr><th colspan=%d class="small muted">%s</th></tr>' % (len(emps) + 1, e(g))
        for a in items:
            cells = ""
            for k, _ in emps:
                if a.get("locked"):
                    cells += '<td class=c title="Always on">✓</td>'
                else:
                    cells += '<td class=c><input type=checkbox form="ab-%s" name=abilities value="%s" %s aria-label="%s for %s"></td>' % (
                        e(k), e(a["id"]), "checked" if a["id"] in eff[k] else "", e(a["name"]), e(reg["employees"][k]["name"]))
            rows += '<tr><td><b>%s</b>%s<div class="small muted">%s</div></td>%s</tr>' % (
                e(a["name"]), ' <span class="chip warn">paid</span>' if a.get("paid") else "", e(a.get("description", "")), cells)
    foot = "".join("""<td class=c><form id="ab-{k}" method=post action=/order>{h}<button class=primary>Save</button><br>
<button name=preset value=default style="margin-top:4px">Default</button><br><button name=preset value=super style="margin-top:4px">Super agent</button></form></td>""".format(
        k=e(k), h=hidden(kind="set_abilities", employee_id=k)) for k, _ in emps)
    return """<p class="muted small">Tick what each employee may do. <b>Default</b> is a capable, low-cost setup; <b>Super agent</b> ticks everything.
Locked rows are the safety basics. Paid abilities spend from budgets you set in Settings.</p>
<div class=wrap><table><thead><tr><th>Ability</th>{head}</tr></thead><tbody>{rows}<tr><td class="small muted">Save each column</td>{foot}</tr></tbody></table></div>""".format(
        head=head, rows=rows, foot=foot)


def apify_spent():
    """This month's Apify spend, as the gateway records it (runs in flight count at their cap)."""
    sys.path.insert(0, os.path.join(CORE, "tools"))
    import apify
    spent, pending = apify.month_spend(team.jload(os.path.join(engine.HOME, "state", "apify_spend.json"), {}))
    return spent + pending


def settings_page():
    reg = engine.registry()
    try:
        with open(ABOUT, encoding="utf-8") as fh:
            about = fh.read()
    except OSError:
        about = ""
    wd = reg.get("workdays", ["Mon", "Tue", "Wed", "Thu", "Fri"])
    days = "".join('<label style="display:inline;margin-right:10px;color:var(--text)"><input type=checkbox name=workdays value=%s %s> %s</label>' % (
        d, "checked" if d in wd else "", d) for d in team.DAYS)
    times = "".join('<label for="t-%s">%s</label><input id="t-%s" name="at_%s" value="%s" pattern="[0-2][0-9]:[0-5][0-9]" size=5>' % (
        j, e(l), j, j, e(team.job_spec({}, j)["at"])) for j, l in team.JOBS.items())
    ap = reg.get("apify", {})
    owners = "".join("<li>%s <span class='small muted'>Telegram id %s</span></li>" % (e(o["name"]), e(i)) for i, o in reg.get("owners", {}).items())
    return """<form method=post action=/settings class=two>{h}<div class=card><b>Your business</b>
<label for=tn>Team name</label><input id=tn name=team_name value="{tn}" maxlength=60>
<label for=ab>About the business (every employee reads this)</label><textarea id=ab name=about rows=8 maxlength=6000>{about}</textarea>
<label>Workdays</label>{days}<label for=nd>Sites their own scripts may reach (one per line, e.g. api.example.com or *.example.org)</label>
<textarea id=nd name=network_domains rows=4 placeholder="api.example.com">{nd}</textarea>
<p class="small muted">Web search, the page reader, the browser and Apify work without this list; it only limits scripts employees write themselves.</p></div>
<div><div class=card><b>Routine times</b>{times}</div><div class=card style="margin-top:14px"><b>Apify (paid)</b>
<p class="small muted">Token: {tok}. Spent this month: ${spent:.2f}.</p>
<label for=amb>Monthly budget (USD)</label><input id=amb name=apify_monthly_budget_usd value="{mb}" size=6>
<label for=amr>Max per run (USD)</label><input id=amr name=apify_max_run_usd value="{mr}" size=6></div>
<div class=card style="margin-top:14px"><b>Owners</b><ul>{owners}</ul><p class="small muted">Claude: {auth}. Telegram bot: {bot}. Team group: {grp}.</p></div>
<p><button class=primary>Save settings</button></p></div></form>""".format(
        h="", tn=e(reg.get("team_name", "")), about=e(about), days=days, nd=e("\n".join(reg.get("network_domains", []))), times=times,
        tok="set" if engine.secret("apify_token") else "not set (run `staff secret apify` in Terminal)", spent=apify_spent(),
        mb=e(str(ap.get("monthly_budget_usd", 5))), mr=e(str(ap.get("max_run_usd", 0.5))), owners=owners or "<li class=muted>none yet</li>",
        auth="your own API key" if reg.get("auth") == "api_key" else "your Claude subscription, signed in on this Mac",
        bot="connected" if team.bot_token() else "not set (`staff setup`)", grp=e(team.group_id() or "none"))


def save_settings(f):
    reg = engine.registry()
    reg["team_name"] = (f.get("team_name", [""])[0].strip() or "Staffroom")[:60]
    reg["workdays"] = [d for d in f.get("workdays", []) if d in team.DAYS] or ["Mon", "Tue", "Wed", "Thu", "Fri"]
    doms = []
    for line in f.get("network_domains", [""])[0].splitlines():
        d = line.strip().lower()
        if d and all(c.isalnum() or c in ".-*" for c in d) and "." in d:
            doms.append(d)
    reg["network_domains"] = sorted(set(doms))[:100]
    jobs = reg.setdefault("jobs", {})
    for j in team.JOBS:
        v = f.get("at_" + j, [""])[0].strip()
        if len(v) == 5 and v[2] == ":" and v[:2].isdigit() and v[3:].isdigit() and int(v[:2]) < 24 and int(v[3:]) < 60:
            jobs.setdefault(j, {})["at"] = v
    ap = reg.setdefault("apify", {})
    for k, hi in (("monthly_budget_usd", 1000.0), ("max_run_usd", 2.0)):
        try:
            ap[k] = max(0.0, min(hi, float(f.get("apify_" + k, [""])[0])))
        except ValueError:
            pass
    engine.save_registry(reg, "settings changed in the control panel")
    with open(ABOUT, "w", encoding="utf-8") as fh:
        fh.write(f.get("about", [""])[0][:6000].replace("\r\n", "\n"))
    return "Settings saved"


def approve_owner(f, me):
    pend = team.jload(PENDING, {})
    i = f.get("id", [""])[0]
    if i not in pend:
        raise orders.OrderError("That request is gone")
    p = pend.pop(i)
    team.jsave(PENDING, pend)
    if f.get("do", [""])[0] != "approve":
        return "Ignored"
    name = (f.get("name", [""])[0].strip() or p.get("name") or "Owner")[:40]
    reg = engine.registry()
    owners = reg.setdefault("owners", {})
    for k in [k for k, o in owners.items() if o.get("local") and o["name"].lower() == name.lower()]:
        owners.pop(k)                                     # the setup placeholder becomes the real Telegram owner
    owners[i] = {"name": name, "aliases": []}
    engine.save_registry(reg, "owner added: %s (by %s)" % (name, me))
    hire.directory(reg)
    team.order_log(me, "owner", "Make %s an owner" % name, "done", "Telegram id %s" % i)
    return "%s is now an owner" % name


class Handler(BaseHTTPRequestHandler):
    server_version = "Staffroom"

    def log_message(self, fmt, *args):  # quiet; errors go to staffd.log
        pass

    def _allowed_host(self):
        h = (self.headers.get("Host") or "").lower()
        return h in ("127.0.0.1:%d" % port(), "localhost:%d" % port())

    def _authed(self):
        c = self.headers.get("Cookie") or ""
        for part in c.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sr" and hmac.compare_digest(v, token()):
                return True
        return False

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "same-origin")   # no-referrer would make form posts send "Origin: null"
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", "sr=%s; HttpOnly; SameSite=Strict; Path=/" % cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _me(self):
        owners = engine.registry().get("owners", {})
        return next(iter(owners.values()), {}).get("name", "Owner")

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, "Forbidden", "text/plain")
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if "t" in q:
            if hmac.compare_digest(q["t"][0], token()):
                return self._redirect(u.path or "/", cookie=token())
            return self._send(403, "Wrong link. Run `staff panel` in Terminal to open the panel.", "text/plain")
        if not self._authed():
            return self._send(401, "Open the panel with `staff panel` in Terminal.", "text/plain")
        flash, err = q.get("m", [None])[0], q.get("err", ["0"])[0] == "1"
        try:
            if u.path == "/":
                return self._send(200, page("Team", "team", team_page(self._me()), flash, err))
            if u.path == "/abilities":
                return self._send(200, page("Abilities", "abilities", abilities_page(), flash, err))
            if u.path == "/settings":
                return self._send(200, page("Settings", "settings", settings_page(), flash, err))
        except Exception as ex:  # noqa: BLE001
            team.log("panel error: %r" % ex)
            return self._send(500, page("Error", "", "<p>Something broke (logged in team/staffd.log).</p>"))
        return self._send(404, "Not found", "text/plain")

    def do_POST(self):
        if not self._allowed_host() or not self._authed():
            return self._send(403, "Forbidden", "text/plain")
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:%d" % port(), "http://localhost:%d" % port()):
            return self._send(403, "Forbidden", "text/plain")
        n = min(int(self.headers.get("Content-Length") or 0), 200_000)
        f = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
        me = self._me()
        back = {"/order": None, "/settings": "/settings", "/owner": "/"}.get(urllib.parse.urlparse(self.path).path, "/")
        if back is None:
            kind = f.get("kind", [""])[0]
            back = "/abilities" if kind == "set_abilities" else "/"
        try:
            if self.path == "/order":
                p = {k: (v if k == "abilities" else v[0]) for k, v in f.items()}
                msg = orders.execute(me, p.pop("kind", ""), p)
            elif self.path == "/settings":
                msg = save_settings(f)
            elif self.path == "/owner":
                msg = approve_owner(f, me)
            else:
                return self._send(404, "Not found", "text/plain")
            return self._redirect("%s?m=%s" % (back, urllib.parse.quote(msg)))
        except orders.OrderError as ex:
            return self._redirect("%s?err=1&m=%s" % (back, urllib.parse.quote(str(ex))))
        except Exception as ex:  # noqa: BLE001
            team.log("panel order error: %r" % ex)
            return self._redirect("%s?err=1&m=%s" % (back, urllib.parse.quote("Something broke (logged)")))


def serve():
    token()
    srv = ThreadingHTTPServer(("127.0.0.1", port()), Handler)
    team.log("panel on http://127.0.0.1:%d" % port())
    srv.serve_forever()


if __name__ == "__main__":
    print(url())
    serve()
