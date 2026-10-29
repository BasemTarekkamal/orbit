#!/usr/bin/env python3
"""staff-watch: watch RSS/Atom feeds, sitemaps, JSON endpoints and pages; report only what is NEW.

    staff-watch add <name> <url> [--kind auto|rss|page] [--match REGEX] [--css SELECTOR] [--ignore REGEX]
    staff-watch list
    staff-watch check [name ...] [--dry-run] [--json]
    staff-watch remove <name>

  --kind auto   (default) a feed or sitemap if the URL is one; an HTML page that advertises a feed
                is watched through that feed; anything else is watched as a page
  --kind rss    new items in an RSS/Atom feed (or new URLs in an XML sitemap)
  --kind page   changes to the page's readable text (HTML, JSON or plain text): added/removed lines
  --match RE    only report items/lines matching RE (case-insensitive). Arabic and other languages
                work; there are no word boundaries in Arabic regexes, so match a stem: "زراع"
  --css SEL     (page) only watch the part of the page matching a CSS selector, e.g. "main .prices"
  --ignore RE   (page) drop lines matching RE before comparing (dates, counters, "updated 3 min ago")

`add` fetches the URL once and records what is there now, so the first `check` reports only genuinely
new things. `check` prints only new items/changes (or "NO CHANGES"), then marks them seen; with
--dry-run nothing is marked, so the same items come back next time. State lives in your workspace:
state/watch.json (+ state/watch/<name>.txt snapshots of watched pages).

Fetching goes through staff-fetch's rules (public URLs only, robots.txt, ~1 request/s per site,
size caps). JavaScript-only pages can't be watched here: watch their feed, sitemap or JSON endpoint
instead (staff-browse <url> --network shows the endpoints). Run as ONE plain command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402

MAX_SEEN = 3000
MAX_REPORT = 25
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,59}$")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def state_path() -> str:
    return os.path.join(_kit.workspace(), "state", "watch.json")


def snap_path(name: str) -> str:
    return os.path.join(_kit.workspace(), "state", "watch", name + ".txt")


def load() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
        if isinstance(st, dict) and isinstance(st.get("watches"), dict):
            return st
    except (OSError, ValueError):
        pass
    return {"watches": {}}


def save(st: dict) -> None:
    p = state_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, p)


def default_fetcher(url: str):
    """(final_url, content_type, bytes). Raises fetch.Wall / fetch.FetchError."""
    import fetch
    r = fetch.http_get(url)
    if r.status >= 400:
        raise fetch.FetchError("HTTP %s" % r.status)
    return r.url, r.ctype, r.content


def _is_feedish(ctype: str, data: bytes) -> bool:
    head = data[:500].lstrip().lower()
    return "xml" in ctype or "rss" in ctype or "atom" in ctype or head.startswith(
        (b"<?xml", b"<rss", b"<feed", b"<urlset", b"<sitemapindex", b"<rdf"))


def parse_items(data: bytes) -> list:
    import fetch
    feed = fetch.parse_feed(data)
    out = []
    for it in feed["items"]:
        ident = it.get("id") or it.get("link") or hashlib.sha1(
            (it.get("title", "") + it.get("date", "")).encode("utf-8")).hexdigest()
        out.append(dict(it, id=ident))
    return out


def page_lines(ctype: str, data: bytes, css: str = None, ignore: str = None) -> list:
    """The comparable content of a page: readable text lines (HTML), pretty JSON lines, or text."""
    import fetch
    head = data[:300].lstrip()
    if "json" in ctype or head[:1] in (b"{", b"["):
        try:
            text = json.dumps(json.loads(data.decode("utf-8", "replace")), ensure_ascii=False, indent=1,
                              sort_keys=True)
            lines = text.splitlines()
        except ValueError:
            lines = data.decode("utf-8", "replace").splitlines()
    elif "html" in ctype or head.lower().startswith((b"<!doctype", b"<html")):
        soup = fetch._soup(data)
        if css:
            parts = soup.select(css)
            if not parts:
                raise ValueError("CSS selector %r matches nothing on the page" % css)
            text = "\n".join(fetch._readable(fetch._soup(str(p))) for p in parts)
        else:
            text = fetch._readable(soup)
        lines = text.splitlines()
    else:
        lines = data.decode("utf-8", "replace").splitlines()
    rx = re.compile(ignore, re.I) if ignore else None
    out = []
    for ln in lines:
        ln = " ".join(ln.split())
        if ln and not (rx and rx.search(ln)):
            out.append(ln)
    return out


def line_changes(old: list, new: list):
    """(lines that appear now but not before, lines that were there but are gone), in page order.
    Reordered lines are not changes."""
    old_set, new_set = set(old), set(new)
    added = list(dict.fromkeys(l for l in new if l not in old_set))
    removed = list(dict.fromkeys(l for l in old if l not in new_set))
    return added, removed


def _match(rx, *texts) -> bool:
    return rx is None or any(rx.search(t or "") for t in texts)


def observe(w: dict, fetcher):
    """Fetch a watch's URL. Returns ("rss", items) or ("page", lines)."""
    final, ctype, data = fetcher(w["url"])
    if w["kind"] == "rss" or (w["kind"] == "auto" and _is_feedish(ctype, data)):
        return "rss", parse_items(data)
    return "page", page_lines(ctype, data, w.get("css"), w.get("ignore"))


def cmd_add(name: str, url: str, kind: str, match: str, css: str, ignore: str, fetcher=None) -> int:
    import fetch
    if not NAME_RX.match(name):
        raise ValueError("name: letters, digits, - _ . only (max 60), e.g. competitor-blog")
    for rx in (match, ignore):
        if rx:
            re.compile(rx)
    url = fetch.check_url(url)
    st = load()
    if name in st["watches"]:
        raise ValueError("a watch called %r already exists (remove it first)" % name)
    fetcher = fetcher or default_fetcher
    final, ctype, data = fetcher(url)
    note = ""
    if kind == "auto" and not _is_feedish(ctype, data) and "html" in (ctype or "html"):
        page = fetch.parse_html(data, final)
        if page["feeds"]:
            feed_url = page["feeds"][0]
            try:
                f2, c2, d2 = fetcher(feed_url)
                if _is_feedish(c2, d2):
                    note = "the page advertises a feed, so the feed is watched: %s (use --kind page to watch " \
                           "the page text instead)" % feed_url
                    url, final, ctype, data = feed_url, f2, c2, d2
            except Exception:  # noqa: BLE001  keep watching the page
                pass
    w = {"url": url, "kind": kind, "match": match or "", "css": css or "", "ignore": ignore or "",
         "added": now(), "last_check": now(), "last_ok": now(), "last_error": "", "seen": {}, "hash": ""}
    w["kind"] = "rss" if (kind == "rss" or (kind == "auto" and _is_feedish(ctype, data))) else "page"
    if w["kind"] == "rss":
        items = parse_items(data)
        for it in items:
            w["seen"][it["id"]] = now()
        desc = "%d items now" % len(items)
    else:
        lines = page_lines(ctype, data, css, ignore)
        _write_snap(name, lines)
        w["hash"] = _hash(lines)
        desc = "%d lines of text now" % len(lines)
        if len(lines) < 5:
            note = (note + "; " if note else "") + "the page has very little text here (JavaScript-rendered?). " \
                   "Watch its feed or JSON endpoint instead (staff-browse <url> --network)"
    st["watches"][name] = w
    save(st)
    print("added %s: %s watch of %s (%s; recorded, so the next check shows only what's new)" % (
        name, w["kind"], url, desc))
    if note:
        print("Note: " + note)
    return 0


def _hash(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _write_snap(name: str, lines) -> None:
    p = snap_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _read_snap(name: str) -> list:
    try:
        with open(snap_path(name), encoding="utf-8") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def check(names=None, dry_run: bool = False, fetcher=None) -> dict:
    """Check watches. Returns {"new": [...], "changed": [...], "errors": [...], "checked": n}."""
    st = load()
    fetcher = fetcher or default_fetcher
    names = names or sorted(st["watches"])
    out = {"new": [], "changed": [], "errors": [], "checked": 0, "at": now()}
    for name in names:
        w = st["watches"].get(name)
        if w is None:
            out["errors"].append({"name": name, "error": "no such watch"})
            continue
        out["checked"] += 1
        rx = re.compile(w["match"], re.I) if w.get("match") else None
        try:
            kind, payload = observe(w, fetcher)
        except Exception as e:  # noqa: BLE001  report, keep going
            out["errors"].append({"name": name, "url": w["url"], "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
            if not dry_run:
                w["last_check"], w["last_error"] = now(), str(e)[:200]
            continue
        if kind == "rss":
            seen = w.setdefault("seen", {})
            fresh = [it for it in payload if it["id"] not in seen]
            for it in fresh:
                if _match(rx, it.get("title"), it.get("summary"), it.get("link")):
                    out["new"].append(dict(it, watch=name))
            if not dry_run:
                for it in fresh:
                    seen[it["id"]] = now()
                if len(seen) > MAX_SEEN:
                    for k in sorted(seen, key=seen.get)[:len(seen) - MAX_SEEN]:
                        del seen[k]
        else:
            h = _hash(payload)
            if h != w.get("hash"):
                added, removed = line_changes(_read_snap(name), payload)
                if rx:
                    added = [l for l in added if rx.search(l)]
                    removed = [l for l in removed if rx.search(l)]
                if added or removed:
                    out["changed"].append({"watch": name, "url": w["url"], "added": added, "removed": removed,
                                           "since": w.get("last_ok", "")})
                if not dry_run:
                    _write_snap(name, payload)
                    w["hash"] = h
        if not dry_run:
            w["last_check"] = w["last_ok"] = now()
            w["last_error"] = ""
    if not dry_run:
        save(st)
    return out


def print_report(r: dict, dry_run: bool) -> None:
    if not r["new"] and not r["changed"]:
        print("NO CHANGES (%d watch%s checked, %s)%s" % (r["checked"], "" if r["checked"] == 1 else "es", r["at"],
                                                        " [dry run]" if dry_run else ""))
    if r["new"]:
        print("%d NEW item(s)%s:" % (len(r["new"]), " [dry run: not marked seen]" if dry_run else ""))
        for it in r["new"][:MAX_REPORT * 2]:
            print("- [%s] %s | %s" % (it["watch"], it.get("date") or "no date", (it.get("title") or "(no title)")[:150]))
            print("    %s" % it.get("link", ""))
            if it.get("summary"):
                print("    > %s" % it["summary"][:240])
        if len(r["new"]) > MAX_REPORT * 2:
            print("... and %d more (use --json for all)" % (len(r["new"]) - MAX_REPORT * 2))
    for c in r["changed"]:
        print("CHANGED [%s] %s (since %s)%s" % (c["watch"], c["url"], c["since"] or "?",
                                               " [dry run]" if dry_run else ""))
        for l in c["added"][:MAX_REPORT]:
            print("  + %s" % l[:240])
        for l in c["removed"][:MAX_REPORT]:
            print("  - %s" % l[:240])
        extra = max(0, len(c["added"]) - MAX_REPORT) + max(0, len(c["removed"]) - MAX_REPORT)
        if extra:
            print("  ... %d more changed lines (snapshot: %s)" % (extra, snap_path(c["watch"])))
    for e in r["errors"]:
        print("ERROR [%s] %s" % (e["name"], e["error"]))


def cmd_list() -> int:
    st = load()
    if not st["watches"]:
        print("No watches yet. Add one: staff-watch add <name> <url> [--match REGEX]")
        return 0
    for name, w in sorted(st["watches"].items()):
        extra = " ".join("%s=%s" % (k, w[k]) for k in ("match", "css", "ignore") if w.get(k))
        status = ("ERROR %s" % w["last_error"][:80]) if w.get("last_error") else "ok"
        print("%-24s %-4s %s %s| last check %s, %s" % (name, w["kind"], w["url"], (extra + " ") if extra else "",
                                                      w.get("last_check", "-"), status))
    return 0


def cmd_remove(name: str) -> int:
    st = load()
    if name not in st["watches"]:
        raise ValueError("no watch called %r (see: staff-watch list)" % name)
    del st["watches"][name]
    save(st)
    try:
        os.remove(snap_path(name))
    except OSError:
        pass
    print("removed %s" % name)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="staff-watch", description="Watch feeds and pages; report only what's new.")
    sub = ap.add_subparsers(dest="cmd")
    a_add = sub.add_parser("add")
    a_add.add_argument("name")
    a_add.add_argument("url")
    a_add.add_argument("--kind", choices=("auto", "rss", "page"), default="auto")
    a_add.add_argument("--match")
    a_add.add_argument("--css")
    a_add.add_argument("--ignore")
    sub.add_parser("list")
    a_chk = sub.add_parser("check")
    a_chk.add_argument("names", nargs="*")
    a_chk.add_argument("--dry-run", action="store_true")
    a_chk.add_argument("--json", action="store_true")
    a_rm = sub.add_parser("remove")
    a_rm.add_argument("name")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    _kit.require("watchers")
    import fetch
    try:
        if a.cmd == "add":
            return cmd_add(a.name, a.url, a.kind, a.match, a.css, a.ignore)
        if a.cmd == "list":
            return cmd_list()
        if a.cmd == "remove":
            return cmd_remove(a.name)
        r = check(a.names, a.dry_run)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            print_report(r, a.dry_run)
        return 0
    except fetch.Wall as e:
        sys.stderr.write("WALL: %s\n" % e)
        return 3
    except (fetch.FetchError, ValueError, re.error) as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
