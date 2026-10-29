#!/usr/bin/env python3
"""Demo mode: a pretend team to look around the control panel with. No bot, no Claude run, nothing
to set up, and nothing real: the business, the people and the companies are invented (their links
end in .example), and the employees' answers are canned. `staff demo` seeds ~/.staffroom-demo, runs
the service on port 7318 with STAFFROOM_DEMO=1 and opens the panel; `staff demo --stop` ends it.

As a program:  STAFFROOM_HOME=<folder> STAFFROOM_DEMO=1 python3 core/demo.py   (seeds, then runs staffd)
Harness-owned. Python 3.9 compatible.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import re
import sys
import threading
import time

CORE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(CORE, "tools"))
import engine  # noqa: E402

PORT = 7318
OWNER = "Alex"
TEAM_NAME = "Northwind Coffee"
PEOPLE = [
    ("sara", "Sara", "Market researcher", "Competitors, prices and demand signals for our coffee; the Monday digest", "sonnet",
     ["telegram", "team_room", "voice", "files", "reminders", "web", "fetch", "browser", "apify", "watchers", "documents", "build_tools", "learn", "brief"]),
    ("omar", "Omar", "Competitor watcher", "Watches Harbor Roast, Bluebird Beans and Kettle & Co: sites, feeds, social. Speaks only when something changed", "haiku",
     ["telegram", "team_room", "reminders", "web", "fetch", "browser", "watchers", "build_tools", "learn", "brief"]),
    ("lina", "Lina", "Personal assistant", "Alex's requests: reminders, documents, quick research, meeting minutes", "sonnet",
     ["telegram", "team_room", "voice", "files", "reminders", "meetings", "web", "fetch", "documents", "build_tools", "learn", "brief", "eod"]),
]
NAMES = {k: n for k, n, *_ in PEOPLE}


def when(days_ago=0, hhmm="09:00", fmt="%Y-%m-%d %H:%M:%S"):
    h, m = [int(x) for x in hhmm.split(":")]
    d = (dt.datetime.now() - dt.timedelta(days=days_ago)).replace(hour=h, minute=m, second=random.randint(0, 59))
    return d.strftime(fmt)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.strip() + "\n")


def jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ canned answers
DEMO_NOTE = "\n\n(demo: nothing was looked up; a real employee researches live)"
REPLIES = [
    (r"tiktok|instagram|social|post", "Harbor Roast's TikTok this week: 6 posts, best one 41k views (the \"cupping at 6am\" clip). The comments ask "
     "the same two things: where to buy in bulk, and whether the beans are decaf. Nobody answers them. My view: a reply-as-a-brand "
     "opening for us. Source: https://tiktok.example/@harborroast (demo data)."),
    (r"price|cost|cheap|expensive|\$", "Price check, 1 kg bags, today: Harbor Roast $34 (was $38 on 21 Oct), Bluebird Beans $36, Kettle & Co $41, us $37. "
     "We're now second-cheapest, not cheapest. Sources: https://harborroast.example/pricing, https://bluebirdbeans.example/shop, "
     "https://kettleandco.example/bags (demo data)."),
    (r"remind|tomorrow|next week", "Reminder set: tomorrow 09:00, to you: \"%s\". I'll send it here. (Change it any time: tell me, or Reminders in my page.)"),
    (r"digest|weekly|monday", "Monday digest (3 competitors, 9 bullets, 118 words): Harbor Roast cut 1 kg bags to $34 and launched a subscription; "
     "Bluebird Beans added a 'Subscribe & save 15%' banner; Kettle & Co is hiring a wholesale manager (demand signal). Full note: "
     "research/digest-this-week.md. Sources inside (demo data)."),
    (r"hello|^hi\b|hey|who are you", "Hi %s. I'm %s, %s. Ask me for anything in my scope and I'll do it now and report back in a few lines."),
    (r"minutes|meeting", "Minutes written: research/minutes-latest.md. Decisions: 2. Action items: 3 (two reminders set). Open question: the "
     "packaging supplier's lead time, flagged (check)."),
    (r".", "Done. Short version: nothing in that needs you today; the detail is in my notes (research/). Say the word and I'll go deeper."),
]
JOB_TEXT = {
    "brief": "Morning brief: Harbor Roast's price cut holds ($34, day 8). Bluebird Beans' subscription banner is gone. Needs you: approve "
             "the Q4 competitor list (TASKS.md). Sources in research/ (demo data).",
    "standup": "Today: price tracker run, TikTok comment scan for Harbor Roast, digest draft. Blocking question: do we care about decaf?",
    "eod": "Done: price tracker, comment scan. Slipped: digest draft (moved to tomorrow). Nothing for tonight.",
    "scout": "Self-improvement: tried a cheaper way to read Kettle & Co's shop (their JSON feed instead of the page). Logged in growth/changelog.md.",
    "evals": "Self-test: 7 of 8 cases pass. Failed: 'quote the exact price with its date' (I rounded). Lesson written.",
}
UPDATES = [
    ("omar", "Watcher: Kettle & Co changed its wholesale page: minimum order down from 20 kg to 10 kg. Source: https://kettleandco.example/wholesale (demo data)."),
    ("sara", "Harbor Roast's subscription page now shows 'over 2,000 subscribers'. Last month it said 1,500. Source: https://harborroast.example/subscribe (demo data)."),
    ("lina", "Reminder for tomorrow 09:00 set: send the roastery the November forecast."),
    ("omar", "Watcher: Bluebird Beans' 'Subscribe & save 15%' banner is gone after 9 days. Source: https://bluebirdbeans.example (demo data)."),
    ("sara", "Someone asked on Harbor Roast's TikTok where to buy 5 kg bags; no reply from them in 3 days. Source: https://tiktok.example/@harborroast (demo data)."),
]


FIRST_DAY = ("Hi %s, I'm %s, your %s. I research, remember what you tell me, and report back here or on your phone.\n\n"
             "Already done: I read about Northwind Coffee and checked your three competitors. Harbor Roast cut its 1 kg bag to $34 "
             "this week (you're at $37), and Kettle & Co lowered its wholesale minimum to 10 kg. Sources: "
             "https://harborroast.example/pricing, https://kettleandco.example/wholesale (demo data).\n\n"
             "What I can't do: spend money, post anywhere, or message anyone but you.\n\n"
             "Try next:\n→ What are my competitors posting on TikTok?\n→ Remind me Friday at 10 to review prices\n"
             "→ From now on, keep every answer under 100 words")
STEPS = [   # what a real run shows in the live view, per kind of request (same wording as core/steps.py)
    (r"first day", ["Checking my notes", "Reading about the business", 'Searching the web: "Harbor Roast coffee prices"',
                    "Reading harborroast.example", "Reading kettleandco.example", "Updating my notes (STATE.md)"]),
    (r"tiktok|instagram|social|post", ["Checking my notes", "Using the social-media playbook", "Running the TikTok scraper",
                                       "Writing research/tiktok-harbor-roast.md", "Updating my notes (STATE.md)"]),
    (r"price|cost|cheap|expensive|\$", ["Checking my notes", 'Searching the web: "Harbor Roast 1 kg bag price"', "Reading harborroast.example",
                                        "Reading bluebirdbeans.example", "Opening kettleandco.example in the browser",
                                        "Writing research/prices-%s.md" % time.strftime("%Y-%m")]),
    (r"remind|tomorrow|next week", ["Checking my notes", "Setting a reminder", "Updating my notes (TASKS.md)"]),
    (r"from now on|always|never|next time", ["Checking my notes", "Writing down a new skill", "Updating my notes (LESSONS.md)"]),
    (r"digest|weekly|monday", ["Using the monday-competitor-digest skill", "Asking Omar", "Reading research/competitors.md",
                               "Writing research/digest-this-week.md"]),
    (r"minutes|meeting", ["Reading the file you sent", "Writing research/minutes-latest.md", "Setting a reminder"]),
    (r".", ["Checking my notes", "Reading about the business", "Updating my notes (STATE.md)"]),
]


def said_of(prompt):
    said = prompt.split("\n", 1)[1] if "\n" in prompt else prompt
    return re.split(r"\n\nFollow CLAUDE\.md", said)[0].strip()


def canned(emp, prompt, job):
    if job in JOB_TEXT:
        return JOB_TEXT[job]
    if job == "first_day":
        return FIRST_DAY % (OWNER, emp["name"], emp["role"].lower())
    said = said_of(prompt)
    low = said.lower()
    if re.search(r"from now on|always|never|next time", low):
        return ("Got it, and written down as a skill so I do it every time from now on: \"%s\". You can read or change it in my "
                "Knowledge tab." % said[:120]) + DEMO_NOTE
    for pat, text in REPLIES:
        if re.search(pat, low):
            if "%s" in text:
                text = text % ((said[:80],) if text.startswith("Reminder") else (OWNER, emp["name"], emp["role"].lower()))
            return text + DEMO_NOTE
    return REPLIES[-1][1] + DEMO_NOTE


def fake_run(emp, prompt, job="chat", session_key=None, on_step=None):
    """Stands in for engine.run: works through plausible steps for a few seconds (so the panel shows the
    live view), then answers from the script."""
    t0 = time.time()
    key = "first day" if job == "first_day" else ("brief" if job in JOB_TEXT else said_of(prompt).lower())
    plan = next(s for pat, s in STEPS if re.search(pat, key)) if job not in JOB_TEXT else \
        ["Checking my notes", "Checking my watchers", "Updating my notes (STATE.md)"]
    steps = []
    for text in plan:
        time.sleep(random.uniform(0.9, 1.8))
        steps.append({"t": round(time.time() - t0), "text": text})
        if on_step:
            on_step(steps[-1], steps)
    time.sleep(random.uniform(0.6, 1.2))
    text = canned(emp, prompt, job)
    ws = emp["workspace"]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "employee": emp["id"], "job": job, "ok": True,
           "secs": round(time.time() - t0), "model": emp.get("model", "sonnet"), "turns": random.randint(3, 9),
           "cost_usd": round(random.uniform(0.03, 0.22), 3), "error": None, "steps": steps}
    os.makedirs(os.path.join(ws, "state"), exist_ok=True)
    with open(os.path.join(ws, "state", "runs.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return {"ok": True, "text": text, "error": "", "model": rec["model"], "steps": steps, "secs": rec["secs"], "cost_usd": rec["cost_usd"]}


def animate():
    """Every couple of minutes an employee posts something, so the room doesn't go quiet."""
    import team
    i = 0
    while True:
        time.sleep(150)
        k, text = UPDATES[i % len(UPDATES)]
        team.feed(k, NAMES[k], OWNER, text, "job")
        i += 1


# ------------------------------------------------------------------ seeding
def seed(home):
    import hire
    import skillbook
    import team
    random.seed(7)
    os.makedirs(os.path.join(home, "team"), exist_ok=True)
    reg = {"team_name": TEAM_NAME, "owners": {"telegram:1": {"name": OWNER, "aliases": []}}, "employees": {},
           "auth": "subscription", "defaults": {"model": "sonnet", "fallback_model": "haiku", "effort": "medium"},
           "workdays": ["Mon", "Tue", "Wed", "Thu", "Fri"], "network_domains": ["api.harborroast.example"],
           "apify": {"monthly_budget_usd": 5, "max_run_usd": 0.5}, "team_chats": {"telegram": "-100777"}, "panel": {"port": PORT}}
    engine.save_registry(reg, "demo team")
    write(os.path.join(home, "team", "ABOUT.md"), """
# Northwind Coffee

A small specialty coffee roaster: we roast twice a week and sell 250 g and 1 kg bags online and to twelve cafés.
Three competitors matter: Harbor Roast (bigger, cheaper), Bluebird Beans (subscriptions), Kettle & Co (wholesale).
What matters most this quarter: hold our price without losing the cafés, and find out whether a subscription is worth it.

Owner: Alex. (This is the demo's invented business.)
""")
    for k, name, role, scope, model, picked in PEOPLE:
        hire.hire(name, role, scope, supervisor=OWNER, emp_id=k, picked=picked, model=model)
    reg = engine.registry()
    for i, (k, *_) in enumerate(PEOPLE):
        reg["employees"][k]["hired"] = (dt.date.today() - dt.timedelta(days=24 - 3 * i)).isoformat()
    engine.save_registry(reg, "demo: hire dates")
    hire.directory(reg)

    ws = {k: engine.employee(k)["workspace"] for k, *_ in PEOPLE}
    today = dt.date.today()
    d = lambda n: (today - dt.timedelta(days=n)).strftime("%d %b")  # noqa: E731
    write(os.path.join(ws["sara"], "STATE.md"), """
# State

## Priorities
1. Monday digest (3 competitors, ≤ 150 words, every bullet sourced).
2. Price tracker: 1 kg bags, daily, flag any move over 5%%.
3. Is a subscription worth it for us? Evidence from Harbor Roast and Bluebird Beans.

## Decisions
- %s: Alex: ignore decaf for now (we don't roast it).
- %s: digest goes out Mondays 08:30, to Alex only.

## Open questions
- Do the twelve cafés see Harbor Roast's $34 price? (Asked Alex %s.)
""" % (d(6), d(12), d(2)))
    write(os.path.join(ws["sara"], "TASKS.md"), """
# Tasks

## Today
- Price tracker run (done 08:05)
- TikTok comment scan, Harbor Roast

## This week
- Digest draft for Monday
- Subscription evidence note (research/subscriptions.md)

## Waiting on owners
- Approve the Q4 competitor list (research/competitors.md) · since %s

## Done
- Price tracker tool (tools/price_check.py)
""" % d(2))
    write(os.path.join(ws["sara"], "LESSONS.md"), """
# Lessons

- %s: Alex: "quote the exact price with its date, don't round". Rule: every price carries its date and link.
- %s: Alex: "three bullets per competitor is enough". Rule: digest ≤ 150 words.
""" % (d(9), d(13)))
    write(os.path.join(ws["sara"], "research", "competitors.md"), """
# Competitors (Q4 list, for approval)

| Company | Why it matters | Watch |
|---|---|---|
| Harbor Roast | Bigger, cheaper, loud on TikTok | pricing page, TikTok |
| Bluebird Beans | Subscription model, 2,000+ subscribers | subscribe page |
| Kettle & Co | Wholesale, hiring | wholesale page, jobs page |

Sources: https://harborroast.example, https://bluebirdbeans.example, https://kettleandco.example (demo data).
""")
    write(os.path.join(ws["sara"], "research", "prices-%s.md" % today.strftime("%Y-%m")), """
# 1 kg bag prices, %s

| Date | Harbor Roast | Bluebird Beans | Kettle & Co | Us |
|---|---|---|---|---|
| %s | $38 | $36 | $41 | $37 |
| %s | $34 | $36 | $41 | $37 |
| %s | $34 | $36 | $41 | $37 |

Harbor Roast cut 1 kg bags from $38 to $34 on %s: https://harborroast.example/pricing (demo data).
""" % (today.strftime("%B %Y"), d(10), d(8), d(0), d(8)))
    write(os.path.join(ws["sara"], "research", "tiktok-harbor-roast.md"), """
# Harbor Roast on TikTok, this week

6 posts, 41k views on the best one ("cupping at 6am"). Comments: 23 ask where to buy in bulk, 9 ask about decaf; none answered.
Source: https://tiktok.example/@harborroast (demo data).

My view: reply-as-a-brand opening for us on bulk; ignore decaf (decision %s).
""" % d(6))
    write(os.path.join(ws["sara"], "tools", "price_check.py"), '''
"""Reads the three competitors' 1 kg bag prices from their pricing pages (staff-fetch) and appends a row to
research/prices-<month>.md. Needs: nothing beyond the toolbelt. Demo data: the pages end in .example."""
''')
    write(os.path.join(ws["sara"], "growth", "changelog.md"), """
# Changelog

- %s: price_check.py reads Kettle & Co's shop JSON instead of the HTML page (3× faster). Undo: git revert.
""" % d(1))
    write(os.path.join(ws["omar"], "STATE.md"), """
# State

## Priorities
1. Four watchers: Harbor Roast pricing, Bluebird Beans home page, Kettle & Co wholesale and jobs pages.
2. Speak only when something changed; one line, with the source.

## Open questions
- Should the jobs page count as a demand signal? (Sara thinks yes.)
""")
    write(os.path.join(ws["omar"], "TASKS.md"), "# Tasks\n\n## Today\n- Watchers checked 07:00, 13:00\n\n## Waiting on owners\n\n## Done\n- Feed finder skill shared with the team\n")
    write(os.path.join(ws["omar"], "research", "watchers.md"), """
# Watchers

| Page | Last change | Note |
|---|---|---|
| https://harborroast.example/pricing | %s | 1 kg bag $38 → $34 |
| https://bluebirdbeans.example | %s | 'Subscribe & save 15%%' banner |
| https://kettleandco.example/wholesale | %s | minimum order 20 kg → 10 kg |
| https://kettleandco.example/jobs | %s | wholesale manager vacancy |

(demo data)
""" % (d(8), d(9), d(1), d(4)))
    write(os.path.join(ws["lina"], "STATE.md"), """
# State

## Priorities
1. Alex's reminders and follow-ups.
2. Minutes within an hour of a recording.

## Open questions
- Thursday's call with the packaging supplier: confirmed? (Asked %s.)
""" % d(1))
    write(os.path.join(ws["lina"], "TASKS.md"), """
# Tasks

## Today
- Send the roastery the November forecast (reminder 09:00)

## Waiting on owners
- Confirm Thursday's call with the packaging supplier · since %s

## Done
- Minutes, Monday team call
""" % d(1))
    write(os.path.join(ws["lina"], "research", "minutes-%s.md" % (today - dt.timedelta(days=2)).isoformat()), """
# Minutes: Monday team call (%s)

Summary: cafés are happy with the roast, two asked about 5 kg bags.
Decisions: (1) try 5 kg bags with two cafés in November; (2) no decaf this year.
Action items: Alex: price for 5 kg bags by Friday (reminder set) · Alex: confirm the packaging supplier call (reminder set).
Open questions: packaging lead time (check).
My view: the 5 kg bag is the cheapest test we have of wholesale demand.
""" % d(2))
    with open(os.path.join(ws["lina"], "state", "reminders.json"), "w") as fh:          # a list, not jsonl
        json.dump([{"id": "R-0001", "at": when(0, "09:00", "%Y-%m-%d %H:%M"), "to": OWNER, "text": "Send the roastery the November forecast",
                    "repeat": "none", "agent": False, "created": when(1, "17:10", "%Y-%m-%d %H:%M")},
                   {"id": "R-0002", "at": when(-2, "16:00", "%Y-%m-%d %H:%M"), "to": OWNER, "text": "Price for 5 kg bags is due Friday",
                    "repeat": "none", "agent": False, "created": when(2, "11:30", "%Y-%m-%d %H:%M")}], fh, indent=1)

    for k, _, _, _, model, _ in PEOPLE:
        rows = []
        for days in range(7, -1, -1):
            for job, hh in (("brief", "08:30"), ("chat", "10:%02d" % random.randint(0, 59)), ("bus", "14:%02d" % random.randint(0, 59))):
                if job == "bus" and random.random() < 0.5:
                    continue
                rows.append({"ts": when(days, hh, "%Y-%m-%dT%H:%M:%S"), "employee": k, "job": job, "ok": not (days == 3 and job == "bus" and k == "omar"),
                             "secs": random.randint(18, 140), "model": model, "turns": random.randint(3, 11),
                             "cost_usd": round(random.uniform(0.02, 0.34 if model != "haiku" else 0.06), 3),
                             "error": "timed out after 30 min" if (days == 3 and job == "bus" and k == "omar") else None})
        rows.sort(key=lambda r: r["ts"])
        jsonl(os.path.join(ws[k], "state", "runs.jsonl"), rows)
    with open(os.path.join(ws["sara"], "state", "claude_usage.json"), "w") as fh:
        json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rateLimits": [{"kind": "five_hour", "percentUsed": 23}, {"kind": "seven_day", "percentUsed": 41}]}, fh)
    os.makedirs(os.path.join(home, "state"), exist_ok=True)
    with open(os.path.join(home, "state", "apify_spend.json"), "w") as fh:
        json.dump({"runs": [{"month": time.strftime("%Y-%m"), "cost_usd": 0.41, "actor": "tiktok"}, {"month": time.strftime("%Y-%m"), "cost_usd": 0.96, "actor": "maps"}]}, fh)

    skillbook.create("sara", "monday-competitor-digest", "How Alex wants the Monday competitor digest. Use when asked for the digest, or on Monday mornings.",
                     "## When to use\nMonday mornings, or when Alex asks for the digest.\n\n## Steps\n1. Pull the week's changes from Omar's watchers and the price tracker.\n"
                     "2. Three bullets per competitor: what changed, why it matters, the source link.\n3. One line on top: the single most important change.\n\n"
                     "## Checks before you answer\n- Every bullet has a link and a date.\n- Under 150 words.\n\n## Example\nAsked: the digest\nDid: 3 competitors, 9 bullets, 118 words.\n",
                     by=OWNER, how="taught")
    skillbook.create("omar", "feed-finder", "Finding a site's hidden JSON or RSS feed before scraping its HTML. Use when a page is slow, JavaScript-heavy, or watched daily.",
                     "## When to use\nAny page we'll read more than once.\n\n## Steps\n1. staff-fetch --feeds <url>: lists the RSS/Atom/JSON endpoints the page links to.\n"
                     "2. Try /feed/, /rss, /sitemap.xml and the /api/ paths seen in the page source.\n3. If one works, watch the feed, not the page.\n\n"
                     "## Checks before you answer\n- Prefer the feed that carries dates.\n\n## Example\nAsked: watch Kettle & Co's shop\nDid: found their shop JSON in 20 s; watcher added.\n",
                     by="self", how="learned")
    skillbook.share("omar", "feed-finder", "self")

    F = lambda days, hhmm, frm, to, body, ch: {"id": "%012x" % random.getrandbits(48), "ts": when(days, hhmm), "from_id": frm,  # noqa: E731
                                              "from_name": NAMES.get(frm, OWNER if frm == OWNER else frm), "to_id": to, "body": body, "channel": ch}
    feed = [
        F(1, "08:30", "sara", OWNER, "Morning brief: Harbor Roast's price cut holds ($34, day 7). Needs you: approve the Q4 competitor list (TASKS.md). Sources in research/ (demo data).", "job"),
        F(1, "08:31", "omar", OWNER, "Morning brief: no change on four watched pages since yesterday. SILENT otherwise.", "job"),
        F(1, "11:12", "sara", "omar", "Which Harbor Roast page changed on %s: pricing or the shop? I need the exact URL for the digest." % d(8), "bus"),
        F(1, "11:14", "omar", "sara", "The pricing page: https://harborroast.example/pricing, 1 kg bag $38 → $34, first seen 07:00 (demo data).", "bus"),
        F(1, "15:40", "lina", OWNER, "Minutes written for Monday's team call: research/minutes-%s.md. 2 decisions, 3 action items, 2 reminders set." % (today - dt.timedelta(days=2)).isoformat(), "job"),
        F(0, "08:30", "sara", OWNER, JOB_TEXT["brief"], "job"),
        F(0, "08:31", "omar", OWNER, "Watcher: Kettle & Co's wholesale minimum order is down from 20 kg to 10 kg. Source: https://kettleandco.example/wholesale (demo data).", "job"),
        F(0, "08:32", "lina", OWNER, "Morning: one reminder for you at 09:00 (November forecast). Thursday's supplier call is still unconfirmed.", "job"),
        F(0, "09:05", OWNER, "sara", "Are we still the cheapest 1 kg bag after Harbor Roast's cut?", "panel"),
        F(0, "09:06", "sara", OWNER, "No: Harbor Roast $34, us $37, Bluebird Beans $36, Kettle & Co $41 (today, 1 kg bags). We're second-cheapest. Sources: research/prices-%s.md (demo data)." % today.strftime("%Y-%m"), "panel"),
    ]
    jsonl(os.path.join(home, "team", "feed.jsonl"), feed)
    jsonl(os.path.join(home, "team", "chatlog.jsonl"), [
        {"ts": when(2, "18:20"), "who": OWNER, "employee": "sara", "channel": "telegram", "text": "what did harbor roast post this week?",
         "answer": "6 TikTok posts; the best one 41k views ('cupping at 6am'). Comments ask about bulk and decaf, unanswered. Note: research/tiktok-harbor-roast.md (demo data)."},
        {"ts": when(1, "07:50"), "who": OWNER, "employee": "lina", "channel": "telegram", "text": "[voice note, transcribed on the Mac]\nremind me tomorrow at nine to send the roastery the november forecast",
         "answer": "Reminder set: tomorrow 09:00, \"Send the roastery the November forecast\". I'll send it here."},
        {"ts": when(1, "09:02"), "who": OWNER, "employee": "sara", "channel": "telegram", "text": "from now on the monday digest is three bullets per competitor max, with a link on every bullet",
         "answer": "Noted and written down as a skill (monday-competitor-digest): three bullets per competitor, a link and a date on each, under 150 words. From next Monday."},
    ])
    jsonl(os.path.join(home, "team", "orders.jsonl"), [
        {"id": "%012x" % random.getrandbits(48), "ts": when(24, "10:00"), "by": OWNER, "kind": "hire", "summary": "Hire Sara (Market researcher)", "status": "done", "result": "Hired: handle /sara"},
        {"id": "%012x" % random.getrandbits(48), "ts": when(21, "10:00"), "by": OWNER, "kind": "hire", "summary": "Hire Omar (Competitor watcher)", "status": "done", "result": "Hired: handle /omar"},
        {"id": "%012x" % random.getrandbits(48), "ts": when(18, "10:00"), "by": OWNER, "kind": "hire", "summary": "Hire Lina (Personal assistant)", "status": "done", "result": "Hired: handle /lina"},
        {"id": "%012x" % random.getrandbits(48), "ts": when(6, "12:15"), "by": OWNER, "kind": "set_abilities", "summary": "Abilities for Omar", "status": "done", "result": "−Voice notes, −Photos and files"},
        {"id": "%012x" % random.getrandbits(48), "ts": when(0, "09:05"), "by": OWNER, "kind": "message", "summary": "Message to Sara", "status": "done", "result": "Passed to Sara"},
    ])
    team.jsave(os.path.join(home, "team", "pending_owners.json"),
               {"telegram:777": {"name": "Nadia", "username": "nadia_k", "channel": "telegram", "at": when(0, "08:12", "%Y-%m-%d %H:%M")}})
    write(os.path.join(home, "team", "DECISIONS.md"), "# Decisions\n\n- %s, Alex: no decaf this year.\n- %s, Alex: try 5 kg bags with two cafés in November.\n" % (d(6), d(2)))
    write(os.path.join(home, "team", "demo.seeded"), time.strftime("%F %T"))


def main():
    home = engine.HOME
    if not os.path.exists(os.path.join(home, "team", "demo.seeded")):
        seed(home)
    import staffd
    threading.Thread(target=animate, daemon=True).start()
    staffd.main()


if __name__ == "__main__":
    main()
