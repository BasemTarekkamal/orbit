# Staffroom

**Turn your own Claude Code into a team of AI employees.** They research anything, work on their own
schedule, talk to each other, and report to you on Telegram. Everything runs on your Mac, signed in
with your own Claude account.

```bash
git clone <this repo> ~/staffroom && ~/staffroom/install.sh
```

Setup takes about five minutes: it checks Claude Code, asks about your business, connects a
Telegram bot, and hires your first employee.

---

## What makes them different: they know *how* to find things

Most AI assistants stop at "I searched the web". Every Staffroom employee carries a **toolbelt**
and a set of **research playbooks** (Claude Code skills that load only when needed), so they pick
the right method for each source, the way an experienced researcher would.

| You ask about… | What the employee does |
|---|---|
| A TikTok account, video or trend | Apify's TikTok scraper: captions, stats, subtitles, and the comments, which show what people ask and doubt |
| A Facebook page, post, reel or ad | The page reader for reel and share links, then the Facebook pages and posts scrapers; Meta Ad Library to see who advertises what, and where |
| Instagram, X, Threads, Reddit, LinkedIn companies | The matching vetted scraper, public data only (what a logged-out visitor sees) |
| Demand, prices, who advertises | Meta Ad Library, Google Trends and News, Amazon and Google Maps reviews, competitors' pricing pages |
| What someone said in a video | YouTube search, then the transcript, quoted with a timestamp and a link |
| Local businesses, suppliers, leads | Google Maps places and reviews, with phone and website, enriched from their own sites |
| Any website | Its own JSON feeds, sitemap or RSS first; then clean page text; then a headless browser for JavaScript pages, infinite scroll and "load more" |
| PDFs, scans, photos of documents | Text extraction, or OCR on your Mac, in any language, with the original wording quoted |
| "Tell me when this changes" | A watcher on the feed or page that speaks only when something new appears |
| Something no tool covers | It writes its own small scraper, tests it, and keeps it for next time |

They follow one ladder: **free first** (search, page reader, browser), **then the specialist tool**
(Apify, within your budget), **then build it**. At most three approaches or thirty minutes per
blocker; after that you get a clean report of what they tried and what they recommend. Every number
and claim comes with a source link.

## A team, not a chatbot

- **Hire in one line:** `staff hire --name Sara --role "Market researcher" --scope "Competitors and prices in our market"`,
  or use the control panel. A new hire has the full toolbelt from day one.
- **Colleagues:** employees ask each other on the team bus (your researcher asks your finance
  assistant for last month's ad spend) and you see every exchange in the team room.
- **Routines:** morning brief, standup, end of day, a daily self-improvement scout, and a weekly
  self-test against their own test cases. Each one can be switched on or off.
- **Memory in files:** each employee keeps STATE, TASKS, GOALS and LESSONS in its own folder (a git
  repository). Correct them once and they write the lesson down.
- **Telegram:** `/sara what did our competitors post this week?`, voice notes (transcribed on your
  Mac), photos and PDFs, meeting recordings turned into minutes, and a team group.

## The control panel

![Today](docs/screens/today-dark.jpg)

`staff panel` opens a small app on your Mac (no account, no cloud, light and dark) with:

- **Today:** what needs you (approvals, reminders, failed runs, people who messaged your bot),
  what the team said today, a setup checklist until everything is connected, and your plan use.
- **Team:** who is working on what, their next routine, runs and plan use today.
- **An employee's page:** a **chat** with them, their **memory** (state, tasks, goals, lessons,
  instructions, and a box for rules you set), their **work** (every file they wrote, readable in
  place), their **activity** (every run, with duration and plan use) and their **abilities**.
- **Hire:** pick a role (personal assistant, market researcher, social media analyst, lead finder,
  competitor watcher, document analyst, content researcher, or from scratch); the scope, abilities
  and model come pre-filled, and the first message to send is suggested.
- **Abilities:** a checkbox for every ability, per employee. **Default** is a capable, low-cost
  setup. **Super agent** ticks everything.
- **Settings:** your business description (every employee reads it), workdays, routine times, the
  Apify budget, who may direct the team, and the sites their own scripts may reach.

## Safe by design

An autonomous agent that reads the open web needs locks, not promises. Every run gets:

- **The macOS sandbox:** shell commands reach only the sites you approve, and can't read your
  secrets, your Documents, Desktop or Downloads, or a colleague's folder.
- **A guard** (a Claude Code hooks module, tested): no money movement, no banking, payment or
  crypto sites, no outside messages (no email, no posting, no raw Telegram), no secrets, no editing
  the kit, its registry or the guard, no nested Claude runs. Card numbers and IBANs are masked before
  the model sees them.
- **Gateways for the open web:** the page reader, the browser, Apify and the watchers run outside
  the sandbox but enforce their own rules: public http(s) pages only (never your Mac or your local
  network), read-only, no logins, no form filling, robots.txt respected, rate-limited. Apify only
  runs vetted scrapers, under a per-run cap and a monthly budget.
- **Content is data, not orders:** pages, posts, PDFs and transcripts can't instruct an employee.
  Attempts get logged.
- **Owners only:** only people you approve can direct the team. Strangers who message the bot are
  ignored and listed in the panel for you to approve or ignore.

## What it costs

- **Claude:** employees run on your own Claude subscription through the official, unmodified
  Claude Code, each signed in through Anthropic's own login on your Mac. Nothing is billed per run;
  runs use your plan's limits, which you share with your own Claude use. The panel shows "plan use"
  (what the runs would cost on the API) and your 5-hour and weekly limits. When usage is high,
  employees switch to a lighter model on their own. A busy team uses a lot, so start with one or two
  employees on Sonnet or Haiku. You can also use your own API key (`staff secret anthropic`), billed
  to your Anthropic account.
- **Apify** (optional, paid per use; the free plan includes monthly credit): only when you add a
  token, and never beyond the budget you set.
- **Everything else is free and local**, including voice transcription (whisper.cpp) and OCR
  (macOS Vision).

## Commands

```
staff setup | start | stop | restart | status | panel | logs | doctor
staff hire --name … --role … [--scope …] [--super] [--model opus|sonnet|haiku]
staff list | pause <h> | resume <h> | retire <h>
staff abilities <h> [--default | --super | --on a,b --off c]
staff run <h> "message"          talk to an employee in the terminal
staff secret telegram|apify|anthropic
staff group <telegram chat id>   use a Telegram group as the team room
```

## Requirements

macOS, [Claude Code](https://claude.com/claude-code) signed in with your Claude account, and
Python 3.9 or newer (the one macOS ships is fine). Optional: Homebrew for voice notes
(`ffmpeg`, `whisper-cpp`), a Telegram bot from @BotFather, an Apify token.

## How it fits together

```
~/staffroom/                 the kit (this repository; update with git pull)
  staff                      the command
  core/engine.py             runs one employee turn: claude -p + sandbox + guard + abilities
  core/staffd.py             the service: Telegram, routines, reminders, team bus, control panel
  core/abilities.json        the ability catalog (what the checkboxes mean)
  core/skills/               the research playbooks
  core/tools/ + bin/         the toolbelt (staff-fetch, staff-browse, staff-apify, staff-watch, staff-docs, staff-bus, staff-remind)
  core/guard/staff-guard/    the guard
~/Staff/                     your team (yours, never in the repository)
  staff.json                 owners, employees, ticks, settings
  team/                      directory, about the business, team bus, team room, decisions
  employees/<handle>/        each employee's folder, memory and work (a git repository)
  .secrets/                  tokens (readable by you, never by employees)
```

More: [docs/toolbelt.md](docs/toolbelt.md) (every tool and skill).

## Terms

This kit runs Anthropic's unmodified Claude Code. Each user signs in with their own Claude account
through Claude Code's own login; the kit never sees, stores or shares that login. If you choose
API-key mode, your own key stays in `~/Staff/.secrets` on your Mac. Usage is billed to you under your
own agreement with Anthropic. It's an independent
project, not made or endorsed by Anthropic. Respect the terms of the sites you research, and
people's privacy.

## License

MIT
