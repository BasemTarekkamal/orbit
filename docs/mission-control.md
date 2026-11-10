# Orbit mission control: the plan

Branch `mission-control`. Draft for the owner's OK. Nothing here is released until one real crew
member has worked seven real days on it (see "Done").

## 1. What Orbit is

Mission control for the Claude agents that work for you.

Claude already does the work, and the Claude app already has the chat. Orbit adds what a chat
cannot show: who is on your crew, what each one can do, what they are aiming at, what they shipped,
what needs you, and the controls.

The benchmark is the open-source agent kits (Hermes Agent and the like): memory, skills that grow,
schedules, messaging. Orbit should match them there and win on three things:

- **No API keys, no extra bill.** It runs on the owner's own Claude plan.
- **Safe by default.** Three fixed limits (section 6), not a wall of switches.
- **A real product.** A designed interface for people who are not developers.

## 2. Who it is for

An owner who does not know how far they can push Claude. The interface's first job is to show them
what their agent can do and how to ask for it. Its second job is control: see, steer, stop.

## 3. Rules for every screen

1. **Show, don't write.** No block of text longer than two lines. Work is shown as the thing itself
   (a thumbnail, a link, a file). Progress is a bar. Time is a timeline. A status is one word plus a
   color.
2. **No chat inside Orbit.** Every place that talks to an agent is a button that opens that agent's
   chat in the Claude app. Telegram, Slack and Discord stay as optional notifications.
3. **One screen answers one question** (section 4).
4. **Every capability carries an example ask.** "Try: …" opens the agent's chat with that sentence
   ready. This is how people learn what to ask.
5. **Numbers are real and labelled.** Plan use is plan use, never a bill. Failures are shown.
6. Zero-build stays: plain HTML, CSS and JS served by `core/panel.py`. No new dependency.
   PRODUCT.md's accessibility rules stay (AA contrast, status never by color alone, phone width).

## 4. Screens

| Screen | The question it answers | What is on it |
|---|---|---|
| Home | What is going on, and what needs me? | The crew in orbit around the owner (status at a glance), at most three "needs you" cards with buttons, this week's four numbers, today's results as a strip |
| Crew member | What is this one doing and what can it do? | Status and "Open chat", its objective and key results, its capabilities with example asks, its week as a timeline, its results as a gallery, its controls (trust level, pause, model, budget) |
| Objectives | Are we getting where we said? | Every objective and key result across the crew, with progress and due date |
| Hire | How do I add one? | A guided interview: one question per step with choices, then the card to approve. Not a chat |
| Metrics | Is it worth it? | Per week: results shipped, times the owner was needed, blocked messages, failed runs, plan use |
| Settings | | Connections, limits, advanced (the full abilities list lives here) |

Removed from the panel: the chat tab, the team room chat, the unread-reports list. The feed file
stays as the record; the screens read results and asks from it, not paragraphs.

## 5. What agents write down

The panel is text today because agents report in free text. The screens above need three small
records, written by one tool an agent can call (`core/tools/record.py`), kept in the crew member's
own `state/` folder:

- **result**: `{ts, title, kind, where, objective}`. `where` is a file path or a link. One per
  thing shipped.
- **ask**: `{id, ts, title, why, options, kind, status, answer}`. `kind` is `decision`, `approval`
  or `blocked`. It becomes a "needs you" card; the owner's click writes the answer back and wakes
  the agent.
- **objectives** (`state/objectives.json`): `[{id, title, due, key_results: [{name, unit, target,
  current}]}]`. Set at hiring, updated by the agent's weekly review.

The handbook tells agents: every shipped thing is a result, every question to the owner is an ask,
and the message in their chat is two lines that point at them.

## 6. The core underneath

- **One brain.** A crew member uses one model for all its work, the owner's choice, by default the
  best the plan has. Falling back to a smaller model is shown on its card, never silent.
- **Three limits, fixed:** spending money, passwords and secrets, the owner's personal accounts and
  files. Everything else is allowed.
- **Trust levels replace the abilities matrix** on the main screens: 1 asks before acting outside
  its folder, 2 works alone and asks before publishing, 3 publishes on its own on the sites the
  owner named. The matrix moves to Settings → Advanced.
- **A "can't" is a bug.** Every blocked message is counted on Metrics and reviewed.

## 7. Phases

Each phase is one brief, one review, one commit on this branch.

1. **Records.** `core/tools/record.py`, the three records, the handbook lines, demo data seeded with
   them (`core/demo.py`), `/api/state` and `/api/employee/<id>` return them. Tests.
2. **Home.** The orbit view, needs-you cards wired to asks, the four numbers, the results strip.
3. **Crew member page.** Objective and key results, capabilities with example asks, week timeline,
   results gallery, controls. The chat tab goes; "Open chat" stays.
4. **Objectives and Metrics.**
5. **Hire.** The interview as a stepper with choices and the card preview.
6. **Core.** Trust levels, one-brain default, handbook cut to what a new human hire would be told.
7. **Polish.** Audit against PRODUCT.md, light and dark, phone width, keyboard, empty states.

## 8. How the work is done

- The lead writes a brief per phase: the files, the data shapes, the acceptance checks.
- A cheaper model builds it in this worktree. The lead reviews the diff, runs the tests, opens the
  demo panel in a browser at desktop and phone width in light and dark, and sends comments. The
  builder fixes them. Then it is committed.
- Look at it running: `STAFFROOM_HOME=~/.orbit-next-demo STAFFROOM_DEMO=1 python3 core/demo.py`
  from this worktree (port 7318, a pretend team, no Claude runs).
- Tests: `for t in test_core test_channels test_tools test_calls test_platforms; do python3 -m unittest tests.$t; done`
  and `claude plugin test core/guard/staff-guard`.
- The builder never touches the live install or its service, never pushes, and adds no dependency.

## 9. Done

A phase is done when its acceptance checks pass in the demo panel. The branch is released when a
real crew member has worked seven real days on it and the week's numbers are better than the week
before: more results shipped without the owner, fewer times the owner was needed, fewer blocked
messages.

## 10. Frozen until this ships

Windows and Linux work, calls and meetings, cloud runs, new connectors, new channels. They stay in
the kit as they are; nothing is added to them.
