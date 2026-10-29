"""Live work steps: each tool call an employee makes, said in plain words ("Reading tiktok.com",
"Asking Omar", "Writing research/prices.md"), for the control panel's live view and the work receipt
under each answer. Pure functions, no I/O. Python 3.9 compatible.

    describe("WebSearch", {"query": "harbor roast prices"}, ws)  →  'Searching the web: "harbor roast prices"'
    describe("Glob", {...}, ws)                                    →  None for noise (skipped)
"""
from __future__ import annotations

import os
import re
import shlex
import urllib.parse

MEMORY = {"STATE.md", "TASKS.md", "GOALS.md", "LESSONS.md", "CLAUDE.md"}
APIFY = {"google-search": "Google", "crawl": "the website crawler", "rag-browser": "the web browser scraper",
         "google-news": "Google News", "google-trends": "Google Trends", "maps-places": "Google Maps",
         "maps-reviews": "Google Maps reviews", "contact-info": "the contact finder", "youtube": "YouTube",
         "youtube-transcript": "YouTube transcripts", "tiktok": "TikTok", "instagram": "Instagram",
         "facebook-page": "Facebook pages", "facebook-posts": "Facebook posts", "facebook-comments": "Facebook comments",
         "fb-ads": "the Meta Ad Library", "x": "X (Twitter)", "threads": "Threads", "linkedin-company": "LinkedIn",
         "reddit": "Reddit", "amazon-reviews": "Amazon reviews"}
QUIET = {"ls", "cat", "head", "tail", "wc", "find", "grep", "rg", "sed", "awk", "echo", "pwd", "cd", "sort", "uniq",
         "jq", "date", "mkdir", "cp", "mv", "touch", "stat", "file", "diff", "tree", "printf"}


def host(url) -> str:
    try:
        h = urllib.parse.urlparse(str(url).strip()).hostname or ""
    except ValueError:
        h = ""
    h = h[4:] if h.startswith("www.") else h
    return h or "a web page"


def rel(path, ws) -> str:
    p = str(path or "")
    if ws and p.startswith(ws.rstrip("/") + "/"):
        p = p[len(ws.rstrip("/")) + 1:]
    return p.replace(os.path.expanduser("~"), "~")


def _file_step(verb, path, ws):
    name = os.path.basename(str(path or ""))
    r = rel(path, ws)
    if name in MEMORY and verb == "Reading":
        return "Checking my notes"
    if name in MEMORY:
        return "Updating my notes (%s)" % name
    if name == "handbook.md":
        return "Checking the handbook"
    if name == "ABOUT.md":
        return "Reading about the business"
    if name == "DIRECTORY.md":
        return "Checking who's on the team"
    if name == "SKILL.md":
        skill = os.path.basename(os.path.dirname(str(path)))
        return ("Using the %s skill" % skill) if verb == "Reading" else ("Writing down the %s skill" % skill)
    if "/state/inbox/" in str(path):
        return "Reading the file you sent"
    if r.startswith(("state/", ".claude/", ".git/")) or "/.runtime/" in str(path):
        return None
    return "%s %s" % (verb, r)


def _bash_step(command, ws):
    cmd = str(command or "").strip()
    try:
        words = shlex.split(cmd)
    except ValueError:
        words = cmd.split()
    if not words:
        return None
    while words and re.match(r"^[A-Z_]+=", words[0]):         # FOO=bar staff-fetch …
        words = words[1:]
    if not words:
        return None
    tool, args = os.path.basename(words[0]), words[1:]
    urls = [a for a in args if a.startswith(("http://", "https://"))]
    first = args[0] if args else ""
    if tool == "staff-fetch":
        if first == "robots":
            return "Checking whether %s allows reading" % host(urls[0] if urls else "")
        if "--links" in args:
            return "Listing the links on %s" % host(urls[0] if urls else "")
        return "Reading %s" % host(urls[0] if urls else "")
    if tool == "staff-browse":
        where = host(urls[0] if urls else "")
        if "--screenshot" in args:
            return "Opening %s in the browser and taking a screenshot" % where
        if "--scroll" in args or "--click" in args:
            return "Opening %s in the browser and scrolling through it" % where
        return "Opening %s in the browser" % where
    if tool == "staff-apify":
        if first == "run" and len(args) > 1:
            return "Running the %s scraper" % APIFY.get(args[1], args[1])
        if first == "results":
            return "Collecting the scraper's results"
        if first in ("list", "schema", "budget"):
            return "Checking the research budget" if first == "budget" else "Picking the right scraper"
        return "Using Apify"
    if tool == "staff-watch":
        return {"add": "Setting up a watcher", "check": "Checking my watchers", "list": "Checking my watchers",
                "remove": "Removing a watcher"}.get(first, "Checking my watchers")
    if tool == "staff-docs":
        f = next((a for a in args[1:] if not a.startswith("-")), "")
        what = os.path.basename(f) or "a document"
        return ("Reading %s with OCR" % what) if first == "ocr" else ("Reading %s" % what)
    if tool == "staff-bus":
        if first == "ask" and len(args) > 1:
            return "Asking %s" % args[1].capitalize()
        return "Posting to the team" if first == "post" else "Checking who's on the team"
    if tool == "staff-remind":
        return {"add": "Setting a reminder", "cancel": "Cancelling a reminder"}.get(first, "Checking reminders")
    if tool == "staff-skill":
        return {"new": "Writing down a new skill", "check": "Checking a skill", "share": "Sharing a skill with the team",
                "drop": "Dropping a skill"}.get(first, "Checking my skills")
    if tool in ("python3", "python"):
        script = next((a for a in args if a.endswith(".py")), "")
        if script:
            return "Running my tool %s" % rel(script, ws)
        return "Running a calculation"
    if tool == "git" or tool in QUIET:
        return None
    return "Running a command"


def describe(tool, inp, ws=""):
    """One tool call → one short line, or None when it's noise not worth showing."""
    inp = inp if isinstance(inp, dict) else {}
    if tool == "WebSearch":
        q = " ".join(str(inp.get("query") or "").split())
        return 'Searching the web: "%s"' % (q[:70] + ("…" if len(q) > 70 else "")) if q else "Searching the web"
    if tool == "WebFetch":
        return "Reading %s" % host(inp.get("url"))
    if tool == "Read":
        return _file_step("Reading", inp.get("file_path"), ws)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return _file_step("Writing" if tool == "Write" else "Updating", inp.get("file_path") or inp.get("notebook_path"), ws)
    if tool in ("Glob", "Grep"):
        return "Looking through my files"
    if tool == "Skill":
        name = str(inp.get("skill") or inp.get("name") or "").split(":")[-1]
        return ("Using the %s playbook" % name) if name else "Using a playbook"
    if tool == "TodoWrite":
        todos = inp.get("todos") or []
        now = next((t.get("activeForm") or t.get("content") for t in todos if t.get("status") == "in_progress"), None)
        return ("Planning: %s" % now[:80]) if now else "Planning the steps"
    if tool == "Bash":
        return _bash_step(inp.get("command"), ws)
    if tool in ("Task", "Agent"):
        return "Working on a sub-task"
    return None
