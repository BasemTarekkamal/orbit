#!/usr/bin/env python3
"""staff-browse: open a JavaScript-heavy public page in headless Chromium, read it, optionally scroll,
click "load more" / tabs / "show transcript", and take a screenshot you can look at.

    staff-browse <url>                          rendered text (what a person would see)
    staff-browse <url> --scroll 8               scroll to the bottom up to 8 times (infinite feeds)
    staff-browse <url> --click "Load more" --click-max 5
                                                click a button/link by its visible text (repeatable,
                                                in order); --click-max N clicks each up to N times
    staff-browse <url> --wait ".price"          wait for a CSS selector before reading
    staff-browse <url> --screenshot [--full-page]
                                                PNG in <workspace>/research/browse/ (open it with Read)
    staff-browse <url> --links [--match RE]     the rendered page's links
    staff-browse <url> --html                   save the rendered HTML (path printed)
    staff-browse <url> --network                list the JSON/XHR requests the page made: these are
                                                the site's own data endpoints, usually better to fetch
                                                directly with staff-fetch
    staff-browse <url> --lang ar                browser language (Accept-Language + navigator.language)

This runs OUTSIDE the sandbox and is a security boundary. Every run:
  * uses a fresh browser context (no profile, no stored cookies), never logs in, never types;
  * passes every request (page, scripts, XHR, redirects, popups) through a check: public http(s)
    only, never this Mac or its network; GET/HEAD only, so nothing is ever posted; WebSockets and
    service workers are blocked; each response's server address is re-checked (DNS rebinding);
  * blocks form submission (in the page and by the request filter); refuses to click inputs, submit
    buttons, or anything labelled like log in / sign up / buy / pay / send / post / accept / delete;
  * respects robots.txt for every page it navigates to, ~1 page/second per site;
  * downloads nothing (PDF or file? use staff-fetch, which saves it to your workspace);
  * stops at CAPTCHAs, bot checks and login walls (exit 3) instead of trying to pass them.
Cookie banner in the way? --click "Reject all" (or the site's "decline" wording). Never accept.

Exit codes: 0 ok, 1 failed, 2 bad usage, 3 wall. Python 3.9+, needs playwright (Chromium is
installed automatically the first time: python3 -m playwright install chromium, free).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402
import fetch  # noqa: E402
from fetch import FetchError, Wall  # noqa: E402

NAV_TIMEOUT_MS = 45000
TOTAL_BUDGET_S = 150          # whole run, so a Bash call with the default 2-minute timeout rarely dies
TEXT_DEFAULT = 8000
DENY_CLICK = re.compile(
    r"\b(log ?in|log ?on|sign ?in|sign ?up|register|create account|subscribe|buy|purchase|check ?out|pay|"
    r"order|donate|submit|send|post|publish|delete|remove|accept|agree|allow all|allow cookies|follow|like|"
    r"share|comment|reply|upload|install|book now|reserve|add to (cart|bag|basket)|apply|vote|report|"
    r"unsubscribe|confirm)\b|تسجيل الدخول|دخول|سجل|اشترك|اشتراك|شراء|اشتر|ادفع|دفع|إرسال|ارسال|أرسل|نشر|حذف|"
    r"موافق|أوافق|قبول|connexion|s'inscrire|acheter|envoyer|accepter|anmelden|kaufen|senden|akzeptieren|"
    r"iniciar sesi[oó]n|registrarse|comprar|enviar|aceptar", re.I)
NO_SUBMIT_JS = """
(() => {
  const stop = (e) => { e.preventDefault(); e.stopImmediatePropagation(); };
  window.addEventListener('submit', stop, true);
  try {
    HTMLFormElement.prototype.submit = function () {};
    HTMLFormElement.prototype.requestSubmit = function () {};
  } catch (e) {}
  try { navigator.sendBeacon = function () { return false; }; } catch (e) {}
})();
"""
LAUNCH_ARGS = [
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-background-networking", "--disable-sync", "--no-first-run", "--disable-component-update",
    "--disable-domain-reliability", "--disable-features=InterestFeedContentSuggestions,MediaRouter",
]


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise FetchError("playwright is not installed: python3 -m pip install --user playwright && "
                         "python3 -m playwright install chromium")


def _launch(p):
    try:
        return p.chromium.launch(headless=True, args=LAUNCH_ARGS)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Executable doesn't exist" not in msg and "playwright install" not in msg:
            raise FetchError("Chromium failed to start: %s" % msg.splitlines()[0][:200])
    sys.stderr.write("[staff-browse] installing Playwright's Chromium (one time, free, ~150 MB)...\n")
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True,
                       timeout=900)
    if r.returncode != 0:
        raise FetchError("couldn't install Chromium: %s" % (r.stderr or r.stdout)[-300:])
    return p.chromium.launch(headless=True, args=LAUNCH_ARGS)


class _Guard:
    """The request filter: one per run."""

    def __init__(self, block_media: bool):
        self.block_media = block_media
        self.hosts = {}          # (scheme, host, port) -> None (ok) or reason
        self.blocked = []        # (reason, url)
        self.rebinding = None
        self.navigations = 0
        self.robots_wall = None
        self.data_requests = []  # XHR/fetch GETs: the site's own endpoints
        self.main_frame = None

    def _host_ok(self, url: str):
        u = urlparse(url)
        key = (u.scheme, u.hostname, u.port)
        if key not in self.hosts:
            try:
                fetch.check_url(url)
                self.hosts[key] = None
            except Wall as e:
                self.hosts[key] = str(e)
        return self.hosts[key]

    def route(self, route, request):
        url = request.url
        if url.startswith(("data:", "blob:", "about:")):
            return route.continue_()
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            self.blocked.append(("%s blocked (GET only)" % request.method, url))
            return route.abort("blockedbyclient")
        why = self._host_ok(url)
        if why:
            self.blocked.append((why, url))
            return route.abort("blockedbyclient")
        rtype = request.resource_type
        if self.block_media and rtype in ("image", "media", "font"):
            return route.abort("blockedbyclient")
        try:
            top = request.is_navigation_request() and request.frame.parent_frame is None
        except Exception:  # noqa: BLE001  requests without a frame (workers)
            top = False
        if top:
            try:
                rb = fetch.robots_check(url)
            except Wall as e:
                self.robots_wall = str(e)
                self.blocked.append(("robots.txt", url))
                return route.abort("blockedbyclient")
            fetch.throttle(urlparse(url).hostname or "", rb.delay())
            self.navigations += 1
            if fetch.LOGIN_PATH.search(urlparse(url).path or "") and self.navigations > 1:
                self.robots_wall = "the page sent the browser to a login page (%s). Never log in; use a public " \
                                   "source%s." % (url, fetch._platform_tip(url))
                return route.abort("blockedbyclient")
        if rtype in ("xhr", "fetch") and len(self.data_requests) < 60:
            self.data_requests.append(url)
        return route.continue_()

    def websocket(self, ws):
        self.sockets = getattr(self, "sockets", 0) + 1   # not connected to the server: nothing leaves

    def response(self, resp):
        try:
            addr = resp.server_addr()
        except Exception:  # noqa: BLE001
            addr = None
        if addr and addr.get("ipAddress"):
            try:
                if not fetch.ip_ok(addr["ipAddress"]):
                    self.rebinding = "%s was served from a private address (%s)" % (resp.url, addr["ipAddress"])
            except ValueError:
                pass


def _settle(page, ms: int = 6000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:  # noqa: BLE001  pages with long-polling never go idle
        pass


def _find(page, text: str):
    exact_rx = re.compile(r"^\s*%s\s*$" % re.escape(text), re.I)
    cands = [page.get_by_role("button", name=exact_rx), page.get_by_role("link", name=exact_rx),
             page.get_by_role("tab", name=exact_rx), page.get_by_text(exact_rx),
             page.get_by_role("button", name=re.compile(re.escape(text), re.I)),
             page.get_by_role("link", name=re.compile(re.escape(text), re.I)),
             page.get_by_text(text, exact=False)]
    for loc in cands:
        try:
            n = min(loc.count(), 15)
        except Exception:  # noqa: BLE001
            continue
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:  # noqa: BLE001
                continue
    return None


def _refuse_reason(el, asked: str):
    if DENY_CLICK.search(asked):
        return "'%s' looks like an action with consequences (login/purchase/send/accept...)" % asked
    try:
        info = el.evaluate("""e => ({tag: e.tagName, type: (e.getAttribute('type') || '').toLowerCase(),
            form: !!(e.form || e.closest('form')), editable: e.isContentEditable,
            label: (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 80)})""")
    except Exception:  # noqa: BLE001
        return None
    tag = (info.get("tag") or "").upper()
    if tag in ("INPUT", "SELECT", "TEXTAREA", "OPTION") or info.get("editable"):
        return "it is a form field (staff-browse never types or fills forms)"
    if tag == "BUTTON" and (info.get("type") == "submit" or (info.get("form") and info.get("type") in ("", "submit"))):
        return "it is a form's submit button"
    label = info.get("label") or ""
    if len(label) <= 60 and DENY_CLICK.search(label):
        return "its label '%s' looks like an action with consequences" % label
    return None


def render(url: str, scroll: int = 0, clicks=(), click_max: int = 1, wait: str = None, screenshot: bool = False,
           full_page: bool = False, want_html: bool = False, lang: str = None, block_media: bool = True) -> dict:
    """Open url in a fresh headless Chromium with every rule applied. Returns a dict with final_url,
    status, title, text, html, links, notes, screenshot path, data_requests. Raises Wall/FetchError."""
    url = fetch.check_url(url)
    fetch.robots_check(url)
    sync_playwright = _playwright()
    guard = _Guard(block_media=block_media and not screenshot)
    notes, t0 = [], time.time()
    out = {"url": url, "notes": notes}
    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(
                user_agent=fetch.UA, locale=lang or "en-US", viewport={"width": 1280, "height": 900},
                accept_downloads=False, service_workers="block", java_script_enabled=True,
                extra_http_headers={"Accept-Language": ("%s,en;q=0.7" % lang) if lang else "en-US,en;q=0.9"})
            ctx.add_init_script(NO_SUBMIT_JS)
            ctx.route("**/*", guard.route)
            try:
                # WebSockets are mocked and never connected to the server. (Closing them instead makes
                # pages like TikTok reconnect in a tight loop.)
                ctx.route_web_socket(re.compile(".*"), guard.websocket)
            except Exception:  # noqa: BLE001  older playwright: no WebSocket routing
                pass
            ctx.on("response", guard.response)
            page = ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            ctx.on("page", lambda pg: pg.close())   # popups and new tabs: closed
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as e:  # noqa: BLE001
                if guard.robots_wall:
                    raise Wall(guard.robots_wall)
                if guard.blocked and any(r[1].rstrip("/") == url.rstrip("/") for r in guard.blocked):
                    raise Wall("blocked: %s" % guard.blocked[0][0])
                raise FetchError("couldn't load %s: %s" % (url, str(e).splitlines()[0][:200]))
            out["status"] = resp.status if resp else None
            _settle(page)
            if wait:
                try:
                    page.wait_for_selector(wait, timeout=15000)
                except Exception:  # noqa: BLE001
                    notes.append("selector %r never appeared within 15s" % wait)
            for text in clicks:
                done = 0
                for _ in range(max(1, click_max)):
                    if time.time() - t0 > TOTAL_BUDGET_S:
                        notes.append("stopped clicking: time budget used")
                        break
                    el = _find(page, text)
                    if el is None:
                        break
                    why = _refuse_reason(el, text)
                    if why:
                        notes.append("refused to click %r: %s" % (text, why))
                        break
                    try:
                        el.scroll_into_view_if_needed(timeout=3000)
                        el.click(timeout=5000)
                    except Exception as e:  # noqa: BLE001
                        notes.append("click on %r failed: %s" % (text, str(e).splitlines()[0][:120]))
                        break
                    done += 1
                    _settle(page, 5000)
                    page.wait_for_timeout(600)
                notes.append("clicked %r %dx" % (text, done) if done else "no visible element with text %r" % text)
            if scroll:
                last, same, n = 0, 0, 0
                for n in range(1, scroll + 1):
                    if time.time() - t0 > TOTAL_BUDGET_S:
                        notes.append("stopped scrolling: time budget used")
                        break
                    page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
                    page.wait_for_timeout(1200)
                    _settle(page, 3000)
                    h = page.evaluate("document.body ? document.body.scrollHeight : 0")
                    same = same + 1 if h == last else 0
                    last = h
                    if same >= 2:
                        break
                notes.append("scrolled %dx (page height %dpx%s)" % (n, last, ", no more content" if same >= 2 else ""))
            if guard.robots_wall:
                raise Wall(guard.robots_wall)
            if guard.rebinding:
                raise Wall("blocked: %s (DNS rebinding?); result discarded" % guard.rebinding)
            final = page.url
            html = page.content()
            text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            title = page.title() or ""
            reason = fetch.wall_reason(html[:20000], out.get("status") or 200, len(text))
            if reason:
                raise Wall("%s shows a bot check / CAPTCHA (%r). Don't try to solve or get around it; use another "
                           "source%s, or report the blocker." % (url, reason, fetch._platform_tip(url)))
            if fetch.LOGIN_PATH.search(urlparse(final).path or ""):
                raise Wall("%s ended on a login page (%s). Never log in; use a public source%s."
                           % (url, final, fetch._platform_tip(url)))
            links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().replace(/\\s+/g, ' ')
                      .slice(0, 140), href: a.href})).filter(l => /^https?:/.test(l.href))""")
            shot = None
            if screenshot:
                name = "%s-%s.png" % (time.strftime("%Y%m%d-%H%M%S"), fetch.slug(urlparse(final).hostname or "", 40))
                shot = os.path.join(_kit.out_dir("research", "browse"), name)
                if full_page:
                    h = min(page.evaluate("document.body ? document.body.scrollHeight : 900") or 900, 12000)
                    page.screenshot(path=shot, clip={"x": 0, "y": 0, "width": 1280, "height": h}, full_page=True)
                else:
                    page.screenshot(path=shot)
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    seen, uniq = set(), []
    for l in links or []:
        h = l["href"].split("#")[0]
        if h not in seen:
            seen.add(h)
            uniq.append({"text": l["text"], "href": h})
    lines, prev = [], None
    for ln in text.splitlines():
        ln = " ".join(ln.split())
        if ln and ln != prev:
            lines.append(ln)
        prev = ln or prev
    blocked = [b for b in guard.blocked if b[0] != "robots.txt"]
    if blocked:
        kinds = sorted(set(b[0].split(":")[0][:60] for b in blocked))
        notes.append("blocked %d request(s): %s" % (len(blocked), "; ".join(kinds)[:300]))
    out.update(final_url=final, title=title, html=html, text="\n".join(lines), links=uniq, screenshot=shot,
               data_requests=guard.data_requests, elapsed=round(time.time() - t0, 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="staff-browse", description="Read a JavaScript-heavy public page.")
    ap.add_argument("url")
    ap.add_argument("--scroll", type=int, default=0, help="scroll to the bottom up to N times")
    ap.add_argument("--click", action="append", default=[], help="visible text of a button/link to click (repeatable)")
    ap.add_argument("--click-max", type=int, default=1, help="click each --click target up to N times")
    ap.add_argument("--wait", help="CSS selector to wait for")
    ap.add_argument("--screenshot", action="store_true")
    ap.add_argument("--full-page", action="store_true", help="screenshot the whole page (max 12000px)")
    ap.add_argument("--links", action="store_true")
    ap.add_argument("--match", help="regex filter for --links")
    ap.add_argument("--html", action="store_true", help="save the rendered HTML")
    ap.add_argument("--network", action="store_true", help="list the page's XHR/fetch data requests")
    ap.add_argument("--lang")
    ap.add_argument("--max-chars", type=int, default=TEXT_DEFAULT)
    a = ap.parse_args(argv)
    _kit.require("browser")
    if a.scroll < 0 or a.scroll > 50 or a.click_max < 1 or a.click_max > 30:
        ap.error("--scroll is 0-50, --click-max is 1-30")
    try:
        r = render(a.url, scroll=a.scroll, clicks=a.click, click_max=a.click_max, wait=a.wait,
                   screenshot=a.screenshot or a.full_page, full_page=a.full_page, want_html=a.html, lang=a.lang)
    except Wall as e:
        sys.stderr.write("WALL: %s\n" % e)
        return 3
    except FetchError as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1
    host = urlparse(r["final_url"]).hostname or ""
    print("%s  [%s, browser, %ss]" % (r["final_url"], r.get("status"), r["elapsed"]))
    print("Title: %s" % (r["title"] or "-"))
    page = fetch.parse_html(r["html"], r["final_url"])
    if page["published"]:
        print("Published: %s" % page["published"])
    if page["jsonld_brief"]:
        print("JSON-LD: %s" % " || ".join(page["jsonld_brief"])[:700])
    if a.network:
        reqs = [u for u in r["data_requests"] if not fetch.API_JUNK.search(u)]
        print("Data requests the page made (%d): fetch them directly with staff-fetch" % len(reqs))
        for u in reqs[:40]:
            print("  " + u)
    if a.links:
        rows = ["%s\t%s" % (l["text"] or "-", l["href"]) for l in r["links"]
                if not a.match or re.search(a.match, l["href"] + " " + l["text"], re.I)]
        print("Links: %d" % len(rows))
        for row in rows[:300]:
            print(row)
        if len(rows) > 300:
            path = fetch.save_text("browse", "%s-%s-links.tsv" % (time.strftime("%Y%m%d-%H%M%S"), fetch.slug(host)),
                                   "\n".join(rows))
            print("... %d more, all saved: %s" % (len(rows) - 300, path))
    else:
        text = r["text"]
        print("----")
        print(text[:a.max_chars])
        print("----")
        if len(text) > a.max_chars:
            path = fetch.save_text("browse", "%s-%s.md" % (time.strftime("%Y%m%d-%H%M%S"), fetch.slug(host)), text)
            print("[showing %d of %d chars; full text: %s]" % (a.max_chars, len(text), path))
    if a.html:
        path = fetch.save_text("browse", "%s-%s.html" % (time.strftime("%Y%m%d-%H%M%S"), fetch.slug(host)), r["html"])
        print("HTML: %s" % path)
    if r["screenshot"]:
        print("Screenshot: %s  (look at it with the Read tool)" % r["screenshot"])
    for n in r["notes"]:
        print("Note: " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
