#!/usr/bin/env python3
"""staff-fetch: read one public web page the cheap way (requests + BeautifulSoup), safely.

    staff-fetch <url>                        readable text + what the page is: title, dates, author,
                                             JSON-LD, OpenGraph, contacts, feeds, the site's own
                                             JSON/API endpoints, embedded page data
    staff-fetch <url> --links [--match RE]   every link on the page (text TAB absolute URL)
    staff-fetch <url> --json                 the same result as structured JSON
    staff-fetch <url> --save                 also keep the raw body + metadata in your workspace
    staff-fetch <url> --render auto|never|always
                                             auto (default): escalate to headless Chromium only when
                                             the page is a JavaScript shell or TLS fails here
    staff-fetch <url> --wait "<css>"         (with the browser) wait for this element first
    staff-fetch <url> --lang ar              ask the site for a language (Accept-Language)
    staff-fetch <url> --max-chars 20000      print more text (default 8000; full text is saved)
    staff-fetch robots <url>                 may this URL be fetched? + crawl-delay and sitemaps

Handles HTML (readable text as light markdown), JSON endpoints (shape + first records), RSS/Atom
feeds and XML sitemaps (item / URL lists), PDFs and other files (saved under
<workspace>/research/files; read them with staff-docs). There is no search command: every free
search page either disallows robots or bot-walls scripts, so search with WebSearch.

This runs OUTSIDE the sandbox, so it is the security boundary and enforces, for every call:
  * public http(s) only: every URL, every redirect hop and every socket connection is checked, so
    nothing reaches this Mac, its control panel or its local network;
  * GET only, no cookies kept between runs, never logs in; robots.txt respected (incl. crawl-delay);
  * about 1 request/second per site, shared by all employees; 30 s timeouts; 10 MB pages, 50 MB files;
  * CAPTCHAs, bot checks and login walls are reported (exit 3), never solved or worked around;
  * files are written only inside the employee's workspace.

Exit codes: 0 ok, 1 failed (network/HTTP), 2 bad usage, 3 wall (robots, CAPTCHA, login, unsafe URL).
On a 3, don't work around it: use another source or report the blocker.
Import: from fetch import http_get, fetch_page, robots_for, parse_feed (watch/browse/apify use them).
Python 3.9+; needs requests + beautifulsoup4 (+ playwright for the browser step).
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html as htmllib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import warnings
from urllib.parse import unquote, urldefrag, urljoin, urlparse

warnings.filterwarnings("ignore", message=r".*(OpenSSL|LibreSSL).*")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402

try:
    import requests  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("staff-fetch needs the 'requests' package: python3 -m pip install --user requests beautifulsoup4")

try:
    import fcntl  # noqa: E402
except ImportError:  # pragma: no cover (not macOS/Linux)
    fcntl = None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
ROBOTS_AGENT = "StaffroomBot"          # the product token we match robots.txt groups against
ROBOTS_UA = "Mozilla/5.0 (compatible; StaffroomBot/1.0)"
TIMEOUT = (10, 30)                     # connect, read (seconds)
DEADLINE = 90                          # max seconds to download one body
PAGE_MAX = 10 * 1024 * 1024
FILE_MAX = 50 * 1024 * 1024
ROBOTS_MAX = 512 * 1024
MAX_HOPS = 8
MIN_INTERVAL = 1.0                     # seconds between hits on one host (all employees)
MAX_CRAWL_DELAY = 10.0
ROBOTS_TTL = 3600
TEXT_DEFAULT = 8000

FILE_TYPES = {
    "application/pdf": ".pdf", "application/zip": ".zip", "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc", "application/rtf": ".rtf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
    "image/tiff": ".tiff", "image/heic": ".heic", "audio/mpeg": ".mp3", "video/mp4": ".mp4",
}
FILE_EXTS = tuple(sorted(set(FILE_TYPES.values()) | {".xlsm", ".odt", ".ods", ".7z", ".gz"}))

# Bot checks / CAPTCHAs. Only treated as a wall when the page is short or the status says "refused":
# a reCAPTCHA widget on a long article's comment form is not a wall.
WALL_MARKERS = (
    "cf-challenge", "cf_chl_opt", "challenge-platform", "just a moment...", "attention required! | cloudflare",
    "g-recaptcha", "h-captcha", "hcaptcha.com", "verify you are human", "are you a robot", "i'm not a robot",
    "unusual traffic from your computer", "px-captcha", "perimeterx", "captcha-delivery.com", "datadome",
    "_incapsula_resource", "request unsuccessful. incapsula", "anomaly-modal", "bot detection",
    "please complete the security check", "access denied | ", "/captcha",
)
LOGIN_PATH = re.compile(r"/(log-?in|sign-?in|signin|sign_in|accounts/login|authwall|uas/login|checkpoint/|"
                        r"auth/login|session/new|i/flow/login)\b", re.I)
PLATFORMS = {   # hosts that show little to logged-out readers -> the social-media skill
    "instagram.com": "instagram", "facebook.com": "facebook-page, facebook-posts, fb-ads",
    "fb.com": "facebook-page", "tiktok.com": "tiktok", "x.com": "x", "twitter.com": "x",
    "linkedin.com": "linkedin-company (public company pages only)", "threads.net": "threads",
    "threads.com": "threads", "reddit.com": "reddit", "youtube.com": "youtube, youtube-transcript",
    "google.com": "google-search, maps-places (or WebSearch)", "amazon.": "amazon-reviews",
}


class Wall(Exception):
    """Something we must not get past: unsafe URL, robots.txt, CAPTCHA/bot check, login wall."""


class FetchError(Exception):
    """An ordinary failure: network, TLS, HTTP error, too big, too slow."""

    def __init__(self, msg, tls=False, status=None):
        super().__init__(msg)
        self.tls = tls
        self.status = status


# ---------------------------------------------------------------------------------------------
# The network boundary


def check_url(url: str) -> str:
    """_kit.safe_url, as a Wall: public http(s) only, never this Mac or its network."""
    try:
        return _kit.safe_url(url)
    except ValueError as e:
        raise Wall("blocked URL: %s" % e)


def ip_ok(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global) and not ip.is_multicast


def install_socket_guard() -> None:
    """Check the address every requests/urllib3 socket actually connects to (defeats DNS rebinding and
    any URL check we might miss): resolve once, refuse private/local addresses, connect to the
    validated IP itself. TLS still verifies the certificate against the hostname."""
    try:
        import urllib3.util.connection as uc
    except ImportError:  # pragma: no cover
        return
    if getattr(uc.create_connection, "_staff_guard", False):
        return
    original = uc.create_connection

    def guarded(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
        host, port = address[0], address[1]
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        ips = []
        for info in infos:
            ip = info[4][0]
            if not ip_ok(ip):
                raise OSError("STAFF-BLOCKED: %s resolves to a private or local address (%s)" % (host, ip))
            if ip not in ips:
                ips.append(ip)
        err = OSError("no address for %s" % host)
        for ip in ips:
            try:
                return original((ip, port), timeout, source_address, socket_options)
            except OSError as e:  # try the next validated address
                err = e
        raise err

    guarded._staff_guard = True
    uc.create_connection = guarded


_SESSION = None


def session():
    global _SESSION
    if _SESSION is None:
        install_socket_guard()
        s = requests.Session()
        s.trust_env = False          # no proxy env vars, no ~/.netrc credentials
        # (redirects are followed by hand in http_get, every hop checked; don't set max_redirects=0:
        # requests then raises TooManyRedirects even with allow_redirects=False)
        _SESSION = s
    return _SESSION


def _request(url: str, headers: dict):
    """One GET, no redirects followed (tests replace this)."""
    return session().get(url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=False)


_LAST_HIT = {}


def throttle(host: str, interval: float = MIN_INTERVAL) -> None:
    """At most one request per `interval` seconds per host, across processes and employees."""
    interval = max(MIN_INTERVAL, min(float(interval or 0), MAX_CRAWL_DELAY))
    host = (host or "").lower()
    if fcntl is not None:
        try:
            d = os.path.join(_kit.HOME, "state", "ratelimit")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, re.sub(r"[^a-z0-9.\-]", "_", host)[:120] or "_")
            with open(path, "a+") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                fh.seek(0)
                try:
                    last = float(fh.read().strip() or 0)
                except ValueError:
                    last = 0.0
                wait = last + interval - time.time()
                if wait > 0:
                    time.sleep(min(wait, interval))
                fh.seek(0)
                fh.truncate()
                fh.write("%.3f" % time.time())
            return
        except OSError:
            pass
    wait = _LAST_HIT.get(host, 0) + interval - time.time()
    if wait > 0:
        time.sleep(min(wait, interval))
    _LAST_HIT[host] = time.time()


# ---------------------------------------------------------------------------------------------
# robots.txt (RFC 9309: most specific group, longest match wins, Allow wins ties, * and $)


class Robots:
    def __init__(self, text: str = "", status: int = 404, note: str = ""):
        self.status, self.note = status, note
        self.groups = []           # [(agents set, rules [(allow, pattern)], delay)]
        self.sitemaps = []
        self.disallow_all = 500 <= status < 600
        self.allow_all = not self.disallow_all and not (200 <= status < 300 and text.strip())
        if 200 <= status < 300:
            self._parse(text)

    def _parse(self, text: str) -> None:
        group, last_agent = None, False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_agent:
                    group = {"agents": set(), "rules": [], "delay": 0.0}
                    self.groups.append(group)
                group["agents"].add(val.lower())
                last_agent = True
                continue
            if key == "sitemap":
                if val:
                    self.sitemaps.append(val)
                continue
            last_agent = False
            if group is None:
                continue
            if key in ("allow", "disallow") and val:
                group["rules"].append((key == "allow", val))
            elif key == "crawl-delay":
                try:
                    group["delay"] = max(group["delay"], float(val))
                except ValueError:
                    pass

    def _groups_for(self, agent: str):
        a = agent.lower()
        specific = [g for g in self.groups if any(x != "*" and (a == x or a.startswith(x)) for x in g["agents"])]
        return specific or [g for g in self.groups if "*" in g["agents"]]

    def delay(self, agent: str = ROBOTS_AGENT) -> float:
        return max([g["delay"] for g in self._groups_for(agent)] or [0.0])

    @staticmethod
    def _match(pattern: str, path: str) -> int:
        end = pattern.endswith("$")
        body = pattern[:-1] if end else pattern
        rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return len(pattern) if re.match(rx + ("$" if end else ""), path, re.S) else -1

    def verdict(self, url: str, agent: str = ROBOTS_AGENT):
        """(allowed, matching rule or reason)."""
        if self.disallow_all:
            return False, "robots.txt answered HTTP %s: the standard says treat the site as off-limits for now" % self.status
        if self.allow_all:
            return True, "no robots.txt rules (%s)" % (self.note or "HTTP %s" % self.status)
        u = urlparse(url)
        path = unquote(u.path or "/") + ("?" + unquote(u.query) if u.query else "")
        if path == "/robots.txt":
            return True, "robots.txt itself"
        best, best_allow, best_rule = -1, True, ""
        for g in self._groups_for(agent):
            for allow, pat in g["rules"]:
                n = self._match(unquote(pat), path)
                if n > best or (n == best and n >= 0 and allow):
                    best, best_allow, best_rule = n, allow, "%s: %s" % ("Allow" if allow else "Disallow", pat)
        if best < 0:
            return True, "no rule matches"
        return best_allow, best_rule

    def allowed(self, url: str, agent: str = ROBOTS_AGENT) -> bool:
        return self.verdict(url, agent)[0]


def _robots_txt(base: str, ua: str = None):
    """(status, text) of base/robots.txt; follows up to 5 safe redirects; (0, '') when unreachable.
    Asked for with a robot's user agent: some sites (Instagram) answer a browser's with an HTML page."""
    url = base + "/robots.txt"
    for _ in range(6):
        try:
            url = check_url(url)
        except Wall:
            return 0, ""
        throttle(urlparse(url).hostname or "")
        try:
            r = _request(url, {"User-Agent": ua or ROBOTS_UA, "Accept": "text/plain,*/*;q=0.5"})
        except Exception:  # noqa: BLE001  network trouble: treat as unreachable
            return 0, ""
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            r.close()
            continue
        try:
            body, _ = _read_capped(r, ROBOTS_MAX, hard=False)
        except FetchError:
            return 0, ""
        text = body.decode("utf-8", "replace")
        if 200 <= r.status_code < 300 and text.lstrip()[:1] == "<":   # an HTML page, not robots.txt
            if ua is None:
                return _robots_txt(base, UA)
            return r.status_code, ""
        return r.status_code, text
    return 0, ""


_ROBOTS = {}


def robots_for(url: str) -> Robots:
    u = urlparse(url)
    base = "%s://%s" % (u.scheme, u.netloc.lower())
    if base in _ROBOTS:
        return _ROBOTS[base]
    cache = os.path.join(_kit.HOME, "cache", "robots", hashlib.sha1(base.encode()).hexdigest()[:20] + ".json")
    rb = None
    try:
        with open(cache, encoding="utf-8") as fh:
            d = json.load(fh)
        if time.time() - d.get("at", 0) < ROBOTS_TTL:
            rb = Robots(d.get("text", ""), int(d.get("status", 404)), d.get("note", ""))
    except (OSError, ValueError):
        pass
    if rb is None:
        status, text = _robots_txt(base)
        note = "robots.txt unreachable" if status == 0 else ""
        rb = Robots(text, status, note)
        if status:  # don't cache "unreachable"
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fh:
                    json.dump({"at": time.time(), "base": base, "status": status, "text": text[:ROBOTS_MAX]}, fh)
            except OSError:
                pass
    _ROBOTS[base] = rb
    return rb


def robots_check(url: str) -> Robots:
    rb = robots_for(url)
    ok, why = rb.verdict(url)
    if not ok:
        raise Wall("robots.txt of %s disallows %s (%s). Don't fetch it; use another source, the site's feed or "
                   "sitemap if allowed, or report the blocker." % (urlparse(url).netloc, url, why))
    return rb


# ---------------------------------------------------------------------------------------------
# GET


class Response:
    def __init__(self, url, status, headers, content, truncated, hops, elapsed):
        headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.url, self.status, self.headers, self.content = url, status, headers, content
        self.truncated, self.hops, self.elapsed = truncated, hops, elapsed
        ct = headers.get("Content-Type", "") or ""
        self.ctype = ct.split(";")[0].strip().lower()
        m = re.search(r"charset=([\w\-:.]+)", ct, re.I)
        self.charset = m.group(1).strip('"\'').lower() if m else None

    def text(self) -> str:
        for enc in (self.charset, "utf-8"):
            if enc:
                try:
                    return self.content.decode(enc)
                except (LookupError, UnicodeDecodeError):
                    pass
        return self.content.decode("utf-8", "replace")


def _read_capped(r, limit: int, hard: bool):
    """Body bytes up to `limit`. hard=True: refuse bigger bodies; False: truncate."""
    try:
        declared = int(r.headers.get("Content-Length") or 0)
    except ValueError:
        declared = 0
    if hard and declared > limit:
        r.close()
        raise FetchError("the file is %.1f MB, over the %d MB cap" % (declared / 1e6, limit // (1024 * 1024)))
    chunks, size, t0 = [], 0, time.time()
    truncated = False
    try:
        for chunk in r.iter_content(65536):
            if not chunk:
                continue
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                if hard:
                    raise FetchError("the body is over the %d MB cap" % (limit // (1024 * 1024)))
                truncated = True
                break
            if time.time() - t0 > DEADLINE:
                raise FetchError("download took longer than %ds" % DEADLINE)
    except requests.exceptions.RequestException as e:
        raise FetchError("download failed: %s" % type(e).__name__)
    finally:
        r.close()
    body = b"".join(chunks)
    return (body[:limit] if truncated else body), truncated


def _looks_file(url: str, ctype: str) -> bool:
    return ctype in FILE_TYPES or urlparse(url).path.lower().endswith(FILE_EXTS)


def http_get(url: str, lang: str = None, accept: str = None, robots: bool = True,
             max_bytes: int = None) -> Response:
    """GET a public URL with every rule applied (safe URL per hop, robots per hop, throttle, caps).
    Raises Wall or FetchError. Returns even for 4xx/5xx (check .status)."""
    headers = {
        "User-Agent": UA,
        "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
        "Accept-Language": ("%s,en;q=0.7,*;q=0.5" % lang) if lang else "en-US,en;q=0.9,*;q=0.5",
    }
    hops, t0 = [], time.time()
    for _ in range(MAX_HOPS + 1):
        url = check_url(url)
        host = urlparse(url).hostname or ""
        delay = robots_check(url).delay() if robots else 0.0
        throttle(host, delay)
        try:
            r = _request(url, headers)
        except requests.exceptions.SSLError as e:
            raise FetchError("TLS handshake with %s failed here (%s)" % (host, str(e)[:160]), tls=True)
        except requests.exceptions.ConnectionError as e:
            if "STAFF-BLOCKED" in str(e):
                raise Wall("blocked: %s resolves to a private or local address" % host)
            raise FetchError("couldn't connect to %s (%s)" % (host, str(e)[:160]))
        except requests.exceptions.Timeout:
            raise FetchError("%s timed out" % host)
        except requests.exceptions.RequestException as e:
            raise FetchError("request failed: %s" % str(e)[:200])
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            nxt = urldefrag(urljoin(url, r.headers["Location"].strip()))[0]
            r.close()
            hops.append("%s %s" % (r.status_code, url))
            if LOGIN_PATH.search(urlparse(nxt).path or ""):
                raise Wall("%s redirects to a login page (%s). Never log in; use a public source%s."
                           % (url, nxt, _platform_tip(url)))
            url = nxt
            continue
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        is_file = _looks_file(url, ctype)
        limit = max_bytes or (FILE_MAX if is_file else PAGE_MAX)
        body, truncated = _read_capped(r, limit, hard=is_file)
        return Response(r.url if isinstance(getattr(r, "url", None), str) else url, r.status_code,
                        dict(r.headers), body, truncated, hops, time.time() - t0)
    raise FetchError("more than %d redirects" % MAX_HOPS)


def _platform_tip(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for key, alias in PLATFORMS.items():
        if host == key or host.endswith("." + key) or (key.endswith(".") and key in host):
            return " (for %s, see the social-media skill: staff-apify run %s)" % (key.rstrip("."), alias)
    return ""


def wall_reason(text_head: str, status: int, text_len: int):
    low = text_head.lower()
    for m in WALL_MARKERS:
        if m in low and (status in (401, 403, 429, 503) or text_len < 1500):
            return m
    return None


# ---------------------------------------------------------------------------------------------
# Understanding what came back


def _soup(content, charset=None):
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        raise FetchError("beautifulsoup4 is missing: python3 -m pip install --user beautifulsoup4")
    if isinstance(content, bytes):
        return BeautifulSoup(content, "html.parser", from_encoding=charset)
    return BeautifulSoup(content, "html.parser")


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def _meta(soup, *names):
    for n in names:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: n})
            if tag and tag.get("content"):
                return _clean(tag["content"])
    return ""


def _ld_objects(soup):
    out = []
    for s in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = s.string or s.get_text() or ""
        try:
            data = json.loads(raw)
        except ValueError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw), strict=False)
            except ValueError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            it = stack.pop(0)
            if isinstance(it, list):
                stack.extend(it)
            elif isinstance(it, dict):
                if "@graph" in it:
                    stack.extend(it["@graph"] if isinstance(it["@graph"], list) else [it["@graph"]])
                if "@type" in it:
                    out.append(it)
    return out


def _names(v):
    if isinstance(v, list):
        return ", ".join(filter(None, (_names(x) for x in v)))
    if isinstance(v, dict):
        return _clean(v.get("name") or v.get("@id") or "")
    return _clean(v)


def _ld_brief(obj: dict) -> str:
    t = obj.get("@type")
    t = "/".join(t) if isinstance(t, list) else str(t)
    bits = []
    for k in ("headline", "name", "datePublished", "dateModified", "author", "publisher", "telephone",
              "email", "priceRange", "address", "ratingValue", "aggregateRating", "offers", "sameAs"):
        v = obj.get(k)
        if v in (None, "", [], {}):
            continue
        if k == "address" and isinstance(v, dict):
            v = ", ".join(_clean(v.get(x)) for x in ("streetAddress", "addressLocality", "addressRegion",
                                                       "postalCode", "addressCountry") if v.get(x))
        elif k == "aggregateRating" and isinstance(v, dict):
            v = "%s/5 (%s)" % (v.get("ratingValue"), v.get("reviewCount") or v.get("ratingCount"))
        elif k == "offers":
            o = v[0] if isinstance(v, list) and v else v
            v = ("%s %s" % (o.get("price", ""), o.get("priceCurrency", ""))).strip() if isinstance(o, dict) else ""
        elif k == "sameAs":
            v = " ".join(v[:4]) if isinstance(v, list) else v
        elif k in ("author", "publisher"):
            v = _names(v)
        v = _clean(v)
        if v:
            bits.append("%s=%s" % (k, v[:120]))
    return "%s(%s)" % (t, "; ".join(bits)) if bits else t


API_RX = re.compile(r"""["'`]((?:https?:)?//[^"'`\s<>]+?/(?:api|graphql|wp-json|ajax|rest|_api|v\d)/[^"'`\s<>]*"""
                    r"""|/(?:api|graphql|wp-json|ajax|rest|_api)/[^"'`\s<>]*|[^"'`\s<>(){}]+\.json(?:\?[^"'`\s<>]*)?)["'`]""")
API_JUNK = re.compile(r"(/(stats|log|logs|ping|beacon|collect|metrics|telemetry|qoe|pixel|track)\b|/img/|emoji|lottie|"
                      r"manifest|package|tsconfig|\.map|\.m?js(\?|$)|\.css(\?|$)|/_next/static|/static/|schema\.org|sentry|analytics|"
                      r"gtag|segment|hotjar|onetrust|cookie|consent|i18n|locales?/|translations?)", re.I)
SOCIAL_RX = re.compile(r"https?://(?:[a-z]+\.)?(facebook\.com|fb\.com|instagram\.com|linkedin\.com/(?:company|in|school)|"
                       r"x\.com|twitter\.com|tiktok\.com/@|youtube\.com/(?:@|channel/|c/|user/)|wa\.me|t\.me|"
                       r"threads\.(?:net|com)|pinterest\.com|snapchat\.com/add)", re.I)
BLOCKS = ("p", "div", "section", "article", "header", "footer", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
          "br", "dt", "dd", "blockquote", "pre", "figcaption", "table", "ul", "ol", "form", "main", "aside", "nav")


def _links(soup, base: str):
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:", "sms:")):
            continue
        href = urldefrag(urljoin(base, href))[0]
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        text = _clean(a.get_text(" ")) or _clean(a.get("title") or a.get("aria-label") or "")
        out.append({"text": text[:140], "href": href})
    return out


def _readable(soup) -> str:
    for t in soup(["script", "style", "noscript", "svg", "template", "iframe", "canvas", "object", "embed", "link",
                   "meta"]):
        t.decompose()
    root = None
    for sel in ("article", "main", "[role=main]"):
        cands = soup.select(sel)
        best = max(cands, key=lambda c: len(c.get_text(" ", strip=True)), default=None)
        if best is not None and len(best.get_text(" ", strip=True)) >= 400:
            root = best
            break
    if root is None:
        root = soup.body or soup
        for t in root.find_all("nav"):
            t.decompose()
    for level in range(1, 5):
        for h in root.find_all("h%d" % level):
            h.insert_before("\n%s " % ("#" * level))
    for li in root.find_all("li"):
        li.insert_before("\n- ")
    for cell in root.find_all(["td", "th"]):
        cell.insert_after(" | ")
    for t in root.find_all(BLOCKS):
        t.insert_after("\n")
    lines, prev = [], None
    for ln in root.get_text(" ").splitlines():
        ln = re.sub(r"[ \t\u00a0\u200b]+", " ", ln).strip()
        ln = re.sub(r"(\s*\|\s*)+$", "", ln)
        if ln in ("", "-", "|") or ln == prev or re.match(r"^#+$", ln):
            continue
        lines.append(ln)
        prev = ln
    return "\n".join(lines)


def parse_html(content, url: str, charset: str = None) -> dict:
    """Everything useful about an HTML page, plus its readable text."""
    soup = _soup(content, charset)
    raw = str(soup)
    html_el = soup.find("html")
    title = _meta(soup, "og:title", "twitter:title") or _clean(soup.title.string if soup.title else "")
    if not title and soup.find("h1"):
        title = _clean(soup.find("h1").get_text(" "))
    ld = _ld_objects(soup)
    published = _meta(soup, "article:published_time", "og:published_time", "datePublished", "pubdate",
                      "publishdate", "date", "DC.date.issued", "dc.date", "sailthru.date", "parsely-pub-date")
    modified = _meta(soup, "article:modified_time", "og:updated_time", "dateModified", "last-modified")
    author = _meta(soup, "author", "article:author", "parsely-author", "dc.creator")
    for o in ld:
        published = published or _clean(o.get("datePublished") or "")
        modified = modified or _clean(o.get("dateModified") or "")
        author = author or _names(o.get("author"))
    if not published:
        t = soup.find("time", attrs={"datetime": True})
        published = _clean(t["datetime"]) if t else ""
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    feeds = []
    for ln in soup.find_all("link", href=True):
        typ = (ln.get("type") or "").lower()
        rel = " ".join(ln.get("rel") or []).lower()
        if "alternate" in rel and any(x in typ for x in ("rss", "atom", "feed+json")):
            feeds.append(urljoin(url, ln["href"]))
    wordpress = bool(re.search(r"/wp-content/|/wp-json/|wp-includes", raw[:400000]))
    if not feeds and wordpress:
        u = urlparse(url)
        feeds.append("%s://%s/feed/" % (u.scheme, u.netloc))   # WordPress always serves one
    hints = []
    wp = soup.find("link", rel=lambda v: v and "https://api.w.org/" in v)
    if wp and wp.get("href"):
        hints.append(urljoin(url, wp["href"]) + "  (WordPress REST API: wp/v2/posts?search=...&per_page=20)")
    for m in API_RX.finditer(raw):
        h = m.group(1).replace("\\u0026", "&").replace("\\/", "/")
        if API_JUNK.search(h) or len(h) > 300:
            continue
        h = urljoin(url, h)
        if h.startswith(("http://", "https://")) and h not in hints:
            hints.append(h)
        if len(hints) >= 12:
            break
    embedded = []
    for s in soup.find_all("script"):
        sid, typ = s.get("id") or "", (s.get("type") or "").lower()
        body = s.string or ""
        if len(body) < 300:
            continue
        if sid == "__NEXT_DATA__" or sid == "__NUXT_DATA__" or (typ == "application/json" and len(body) > 1500):
            embedded.append({"kind": sid or "application/json", "chars": len(body), "data": body})
        elif typ in ("", "text/javascript", "application/javascript", "module"):
            m = re.search(r"(?:window\.|var\s+|self\.)(__[A-Za-z_]+__|__INITIAL_STATE__|__PRELOADED_STATE__|"
                          r"ytInitial[A-Za-z]+|initialState|__remixContext)\s*=", body)
            if m:
                data = body
                start = min([i for i in (body.find("{", m.end()), body.find("[", m.end())) if i >= 0] or [-1])
                if start >= 0:   # pull the JSON literal out of `var x = {...};`
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(body[start:])
                        data = json.dumps(obj, ensure_ascii=False)
                    except ValueError:
                        pass
                embedded.append({"kind": m.group(1), "chars": len(data), "data": data})
    emails, phones, socials = [], [], []
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if h.lower().startswith("mailto:"):
            e = unquote(h[7:].split("?")[0]).strip()
            if e and e not in emails:
                emails.append(e)
        elif h.lower().startswith("tel:"):
            p = unquote(h[4:]).strip()
            if p and p not in phones:
                phones.append(p)
        elif SOCIAL_RX.match(h) and h not in socials:
            socials.append(h)
    description = _meta(soup, "description", "og:description", "twitter:description")
    site, og_type = _meta(soup, "og:site_name"), _meta(soup, "og:type")
    lang = ((html_el.get("lang") if html_el else "") or "").strip()
    canonical = canonical.get("href", "") if canonical is not None else ""
    js_markers = bool(re.search(r'id=["\'](root|app|__next|__nuxt|svelte)["\']|ng-app|data-reactroot|'
                                r'enable javascript|javascript is (required|disabled)|requires javascript', raw, re.I))
    links = _links(soup, url)
    text = _readable(soup)
    return {
        "title": title, "description": description, "lang": lang, "site": site,
        "published": published, "modified": modified, "author": author, "canonical": canonical,
        "og_type": og_type, "wordpress": wordpress, "jsonld": ld, "jsonld_brief": [_ld_brief(o) for o in ld[:8]],
        "feeds": feeds[:6], "api_hints": hints, "embedded": embedded,
        "contacts": {"emails": emails[:10], "phones": phones[:10], "socials": socials[:12]},
        "js_shell": len(text) < 400 and (len(text) < 150 or js_markers),
        "links": links, "text": text,
    }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _kid(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _kid_text(el, *names) -> str:
    c = _kid(el, *names)
    return (c.text or "").strip() if c is not None and c.text else ""


def _iso(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d is not None:
            if d.tzinfo is not None:
                d = d.astimezone(dt.timezone.utc)
            return d.strftime("%Y-%m-%d %H:%MZ")
    except (TypeError, ValueError, IndexError):
        pass
    return s[:16].replace("T", " ")


def _strip_tags(s: str) -> str:
    return _clean(htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")))


def parse_feed(data: bytes) -> dict:
    """RSS 2.0 / RSS 1.0 (RDF) / Atom / XML sitemap -> {"kind", "title", "items": [{id,title,link,date,summary}]}.
    Refuses XML that declares entities (no entity-expansion bombs)."""
    import xml.etree.ElementTree as ET
    if re.search(rb"<!ENTITY", data[:200000], re.I):
        raise FetchError("this XML declares entities; refusing to parse it")
    try:
        root = ET.fromstring(data.lstrip())
    except ET.ParseError as e:
        raise FetchError("not valid XML (%s)" % e)
    tag = _local(root.tag).lower()
    out = {"kind": tag, "title": "", "items": []}
    if tag in ("urlset", "sitemapindex"):
        out["kind"] = "sitemap" if tag == "urlset" else "sitemap-index"
        for u in root:
            loc = _kid_text(u, "loc")
            if loc:
                out["items"].append({"id": loc, "title": "", "link": loc, "date": _kid_text(u, "lastmod")[:10],
                                     "summary": ""})
        return out
    if tag == "feed":  # Atom
        out["kind"] = "atom"
        out["title"] = _kid_text(root, "title")
        entries = [e for e in root if _local(e.tag) == "entry"]
        for e in entries:
            link = ""
            for ln in e:
                if _local(ln.tag) == "link" and ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                    link = ln.get("href")
                    break
            summ = _kid(e, "summary") if _kid(e, "summary") is not None else _kid(e, "content")
            out["items"].append({
                "id": _kid_text(e, "id") or link, "title": _strip_tags(_kid_text(e, "title")), "link": link,
                "date": _iso(_kid_text(e, "published") or _kid_text(e, "updated")),
                "summary": _strip_tags(summ.text if summ is not None and summ.text else "")[:600]})
        return out
    if tag in ("rss", "rdf"):
        out["kind"] = "rss"
        channel = _kid(root, "channel")
        out["title"] = _kid_text(channel, "title") if channel is not None else ""
        items = [i for i in root.iter() if _local(i.tag) == "item"]
        for i in items:
            link = _kid_text(i, "link") or (i.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "")
            desc = _kid_text(i, "description") or _kid_text(i, "encoded")
            out["items"].append({
                "id": _kid_text(i, "guid") or link or _kid_text(i, "title"),
                "title": _strip_tags(_kid_text(i, "title")), "link": link,
                "date": _iso(_kid_text(i, "pubDate") or _kid_text(i, "date")),
                "summary": _strip_tags(desc)[:600]})
        return out
    raise FetchError("XML but not a feed or sitemap (root <%s>)" % tag)


def json_shape(obj, depth: int = 0) -> str:
    if isinstance(obj, dict):
        if depth >= 2:
            return "object{%d keys}" % len(obj)
        parts = ["%s: %s" % (k, json_shape(v, depth + 1)) for k, v in list(obj.items())[:12]]
        more = ", +%d more" % (len(obj) - 12) if len(obj) > 12 else ""
        return "{%s%s}" % (", ".join(parts), more)
    if isinstance(obj, list):
        return "list[%d]%s" % (len(obj), (" of " + json_shape(obj[0], depth + 1)) if obj and depth < 2 else "")
    if isinstance(obj, str):
        return "str"
    return type(obj).__name__


def main_records(obj):
    """The biggest list of objects within two levels: usually the data you want."""
    best, best_path = None, ""
    stack = [(obj, "")]
    for _ in range(200):
        if not stack:
            break
        cur, path = stack.pop(0)
        if isinstance(cur, list) and cur and isinstance(cur[0], dict):
            if best is None or len(cur) > len(best):
                best, best_path = cur, path or "(top level)"
        if isinstance(cur, dict) and path.count(".") < 2:
            stack.extend((v, (path + "." + k).lstrip(".")) for k, v in cur.items() if isinstance(v, (dict, list)))
    return best, best_path


# ---------------------------------------------------------------------------------------------
# Saving (only inside the workspace)


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n] or "page"


def save_bytes(sub: str, name: str, data: bytes) -> str:
    folder = _kit.out_dir("research", sub)
    path = os.path.join(folder, os.path.basename(name))
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def save_text(sub: str, name: str, text: str) -> str:
    return save_bytes(sub, name, text.encode("utf-8"))


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _page_name(url: str, ext: str) -> str:
    u = urlparse(url)
    return "%s-%s-%s%s" % (_stamp(), slug(u.hostname or "", 40), slug(u.path, 50), ext)


def _file_name(url: str, ctype: str, data: bytes) -> str:
    u = urlparse(url)
    base = os.path.basename(unquote(u.path)) or "download"
    stem, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in FILE_EXTS else FILE_TYPES.get(ctype, ext.lower() or ".bin")
    if data[:5] == b"%PDF-":
        ext = ".pdf"
    return "%s-%s-%s%s" % (slug(u.hostname or "", 40), slug(stem, 60), hashlib.sha1(data).hexdigest()[:8], ext)


# ---------------------------------------------------------------------------------------------
# The command


def _can_browse() -> bool:
    try:
        _kit.require("browser")
        return True
    except SystemExit:
        return False


def _from_browser(url: str, lang: str, wait: str) -> dict:
    import browse  # noqa: E402  (same folder)
    return browse.render(url, lang=lang, wait=wait)


def fetch_page(url: str, render: str = "auto", lang: str = None, wait: str = None) -> dict:
    """Fetch and understand one URL. Returns a result dict (see main() for how it's shown)."""
    res = {"url": url, "notes": [], "saved": {}}
    resp, tls_fail = None, None
    if render != "always":
        try:
            resp = http_get(url, lang=lang)
        except FetchError as e:
            if not (e.tls and render == "auto"):
                raise
            tls_fail = str(e)
    if resp is not None:
        res.update(final_url=resp.url, status=resp.status, ctype=resp.ctype, via="requests",
                   elapsed=round(resp.elapsed, 1), hops=resp.hops)
        if resp.status >= 400:
            head = resp.content[:20000].decode("utf-8", "replace")
            reason = wall_reason(head, resp.status, len(head))
            if reason:
                raise Wall("%s is behind a bot check / CAPTCHA (%r, HTTP %s). Don't try to solve or get around it; "
                           "use another source%s, or report the blocker." % (url, reason, resp.status, _platform_tip(url)))
            raise FetchError("HTTP %s from %s%s" % (resp.status, urlparse(resp.url).netloc,
                                                   " - the site refused; don't work around it, use another source"
                                                   if resp.status in (401, 403, 451) else ""), status=resp.status)
        data = resp.content
        if _looks_file(resp.url, resp.ctype) or data[:5] == b"%PDF-":
            path = save_bytes("files", _file_name(resp.url, resp.ctype, data), data)
            res.update(kind="file", size=len(data), saved={"file": path})
            if path.endswith(".pdf"):
                res["notes"].append("PDF saved. Read it: staff-docs text %s   (scanned? staff-docs ocr %s)" % (path, path))
            elif path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".heic")):
                res["notes"].append("Image saved. Look at it with the Read tool, or OCR it: staff-docs ocr %s" % path)
            elif path.endswith((".xlsx", ".xlsm", ".csv", ".docx", ".doc", ".rtf", ".odt", ".pptx")):
                res["notes"].append("File saved. Read it: staff-docs %s %s" % (
                    "tables" if path.endswith((".xlsx", ".xlsm", ".csv")) else "text", path))
            return res
        head = data[:600].lstrip().lower()
        if resp.ctype in ("application/json", "text/json") or resp.ctype.endswith("+json") or (
                head[:1] in (b"{", b"[") and resp.ctype in ("", "text/plain", "text/javascript")):
            try:
                obj = json.loads(resp.text())
            except ValueError:
                obj = None
            if obj is not None:
                recs, rpath = main_records(obj)
                res.update(kind="json", json=obj, shape=json_shape(obj),
                           records_path=rpath, records=len(recs) if recs else 0,
                           first=recs[0] if recs else None)
                return res
        if "xml" in resp.ctype or head.startswith((b"<?xml", b"<rss", b"<feed", b"<urlset", b"<sitemapindex", b"<rdf")):
            try:
                feed = parse_feed(data)
                res.update(kind=feed["kind"], feed=feed)
                return res
            except FetchError as e:
                if "html" not in resp.ctype:
                    res.update(kind="text", text=resp.text())
                    res["notes"].append(str(e))
                    return res
        if "html" not in resp.ctype and resp.ctype and not head.startswith((b"<!doctype", b"<html")):
            res.update(kind="text", text=resp.text())
            return res
        page = parse_html(data, resp.url, resp.charset)
        res["raw"] = data
        reason = wall_reason(data[:20000].decode("utf-8", "replace"), resp.status, len(page["text"]))
        if reason:
            raise Wall("%s shows a bot check / CAPTCHA (%r). Don't try to solve or get around it; use another "
                       "source%s, or report the blocker." % (url, reason, _platform_tip(url)))
        res.update(kind="html", page=page)
        if resp.truncated:
            res["notes"].append("page was over %d MB; only the first part was read" % (PAGE_MAX // (1024 * 1024)))
        if not page["js_shell"] or render == "never":
            if page["js_shell"]:
                res["notes"].append("page text is thin and looks JavaScript-rendered; try --render always "
                                    "or staff-browse, or the site's JSON endpoints")
            return res
        big = [e for e in page["embedded"] if e["chars"] > 2000]
        if big:
            res["notes"].append("page text is thin but the data is embedded in <script> (%s) - saved below; "
                                "no browser needed" % ", ".join(e["kind"] for e in big))
            return res
    # The browser step: render == "always", a JavaScript shell, or TLS that fails in this Python.
    if not _can_browse():
        if resp is None:
            raise FetchError(("%s, and " % tls_fail if tls_fail else "") + "the headless browser is switched off for "
                             "you (ask your owner to switch on 'Headless browser')")
        res["notes"].append("page looks JavaScript-rendered, but the headless browser is switched off for you; "
                            "ask your owner to switch on 'Headless browser', or use the site's JSON endpoints")
        return res
    why = "requested" if render == "always" else ("TLS failed in Python" if tls_fail else "page needed JavaScript")
    try:
        b = _from_browser(url, lang, wait)
    except FetchError as e:
        if resp is None:
            raise
        res["notes"].append("browser step failed (%s); showing what plain HTTP returned" % e)
        return res
    rendered = parse_html(b["html"], b["final_url"])
    if b.get("text") and len(b["text"]) > len(rendered["text"]):
        rendered["text"] = b["text"]
    if res.get("page"):   # the server's own metadata is more reliable than a page that JS has rewritten
        page = dict(res["page"])
        for k in ("text", "links", "contacts", "api_hints"):
            page[k] = rendered[k] or page[k]
        page["embedded"] = page["embedded"] or rendered["embedded"]
        for k in ("title", "description", "published", "author", "jsonld", "jsonld_brief", "feeds"):
            page[k] = page[k] or rendered[k]
        page["js_shell"] = False
    else:
        page = rendered
    res.update(final_url=b["final_url"], status=b.get("status"), ctype="text/html", via="browser (%s)" % why,
               elapsed=b.get("elapsed"), kind="html", page=page, raw=b["html"].encode("utf-8"))
    res["notes"].extend(b.get("notes") or [])
    return res


def _print_result(res: dict, a) -> None:
    p = print
    via = res.get("via", "")
    p("%s  [%s %s, %s, %ss]" % (res.get("final_url", res["url"]), res.get("status", "-"), res.get("ctype") or "?",
                                via, res.get("elapsed", "?")))
    if res.get("hops"):
        p("Redirects: " + " -> ".join(res["hops"]))
    kind = res.get("kind")
    full_text = ""
    if kind == "file":
        p("File: %s (%.1f KB)" % (res["saved"]["file"], res["size"] / 1024.0))
    elif kind == "json":
        p("JSON: %s" % res["shape"])
        if res.get("records"):
            p("Records: %d at %s. First: %s" % (res["records"], res["records_path"],
                                                json.dumps(res["first"], ensure_ascii=False)[:900]))
        full_text = json.dumps(res["json"], ensure_ascii=False, indent=1)
        res["saved"]["json"] = save_text("pages", _page_name(res.get("final_url", res["url"]), ".json"), full_text)
        if len(full_text) <= a.max_chars:
            p("----")
            p(full_text)
        p("Saved: %s" % res["saved"]["json"])
        full_text = ""
    elif kind in ("rss", "atom", "sitemap", "sitemap-index"):
        feed = res["feed"]
        p("%s%s: %d items" % (kind.upper(), (" '%s'" % feed["title"]) if feed["title"] else "", len(feed["items"])))
        rows = ["%s | %s | %s" % (i["date"] or "-", (i["title"] or "")[:110], i["link"]) for i in feed["items"]]
        shown = 40 if kind.startswith("sitemap") else 25
        for r in rows[:shown]:
            p("- " + r)
        if len(rows) > shown:
            path = save_text("pages", _page_name(res.get("final_url", res["url"]), ".txt"), "\n".join(rows))
            res["saved"]["items"] = path
            p("... %d more, all saved: %s" % (len(rows) - shown, path))
        if kind == "sitemap-index":
            p("Sitemap index: fetch the child sitemaps above for page URLs.")
    elif kind == "text":
        full_text = res.get("text", "")
    elif kind == "html":
        pg = res["page"]
        p("Title: %s" % (pg["title"] or "-"))
        line = []
        for k, label in (("site", "Site"), ("lang", "Lang"), ("published", "Published"), ("modified", "Modified"),
                         ("author", "Author"), ("og_type", "Type")):
            if pg.get(k):
                line.append("%s: %s" % (label, pg[k][:80]))
        if line:
            p(" | ".join(line))
        if pg["description"]:
            p("Description: %s" % pg["description"][:300])
        if pg["canonical"] and pg["canonical"].rstrip("/") != res.get("final_url", "").rstrip("/"):
            p("Canonical: %s" % pg["canonical"])
        if pg["jsonld_brief"]:
            p("JSON-LD: %s" % " || ".join(pg["jsonld_brief"])[:900])
        c = pg["contacts"]
        if c["emails"] or c["phones"]:
            p("Contacts on page: %s" % " | ".join(c["emails"] + c["phones"])[:400])
        if c["socials"]:
            p("Social profiles: %s" % " ".join(c["socials"])[:500])
        if pg["feeds"]:
            p("Feeds: %s" % " ".join(pg["feeds"]))
        if pg["api_hints"]:
            p("Site data endpoints (try them with staff-fetch): %s" % " | ".join(pg["api_hints"][:8]))
        keep = a.save or pg["js_shell"] or len(pg["text"]) < 1500
        for e in pg["embedded"]:
            if not keep:
                p("Embedded data: %s (%d KB) - add --save to keep it as JSON" % (e["kind"], e["chars"] // 1024))
                continue
            data = e["data"]
            try:
                data = json.dumps(json.loads(data), ensure_ascii=False, indent=1)
                ext = ".json"
            except ValueError:
                ext = ".js.txt"
            path = save_text("pages", _page_name(res.get("final_url", res["url"]), "-%s%s" % (slug(e["kind"], 30), ext)),
                             data)
            res["saved"].setdefault("embedded", []).append(path)
            p("Embedded data: %s (%d KB) saved: %s" % (e["kind"], e["chars"] // 1024, path))
        full_text = pg["text"]
        if a.links:
            rows = ["%s\t%s" % (l["text"] or "-", l["href"]) for l in pg["links"]
                    if not a.match or re.search(a.match, l["href"] + " " + l["text"], re.I)]
            p("Links: %d%s" % (len(rows), (" matching /%s/" % a.match) if a.match else ""))
            for r in rows[:300]:
                p(r)
            if len(rows) > 300:
                path = save_text("pages", _page_name(res.get("final_url", res["url"]), "-links.tsv"), "\n".join(rows))
                p("... %d more, all saved: %s" % (len(rows) - 300, path))
            full_text = ""
    if full_text:
        p("----")
        p(full_text[:a.max_chars])
        p("----")
        if len(full_text) > a.max_chars or a.save:
            path = save_text("pages", _page_name(res.get("final_url", res["url"]), ".md"), full_text)
            res["saved"]["text"] = path
            if len(full_text) > a.max_chars:
                p("[showing %d of %d chars; full text: %s]" % (a.max_chars, len(full_text), path))
    for n in res["notes"]:
        p("Note: " + n)
    tip = _platform_tip(res.get("final_url", res["url"]))
    if tip and kind == "html" and len(res["page"]["text"]) < 1500:
        p("Tip: little public content%s" % tip)


def _save_all(res: dict) -> None:
    if res.get("raw"):
        path = save_bytes("pages", _page_name(res.get("final_url", res["url"]), ".html"), res["raw"])
        res["saved"]["html"] = path
        print("Saved HTML: %s" % path)
    meta = {k: v for k, v in res.items() if k not in ("json", "raw")}
    if "page" in meta:
        meta["page"] = {k: v for k, v in meta["page"].items() if k not in ("embedded",)}
    path = save_text("pages", _page_name(res.get("final_url", res["url"]), "-meta.json"),
                     json.dumps(meta, ensure_ascii=False, indent=1, default=str))
    res["saved"]["meta"] = path
    print("Saved metadata: %s" % path)


def cmd_robots(url: str) -> int:
    url = check_url(url)
    rb = robots_for(url)
    ok, why = rb.verdict(url)
    print("%s: %s (%s)" % (url, "ALLOWED" if ok else "DISALLOWED", why))
    if rb.delay():
        print("Crawl-delay: %ss (staff tools wait at least this long between requests)" % rb.delay())
    if rb.sitemaps:
        print("Sitemaps: %s" % " ".join(rb.sitemaps[:10]))
    return 0 if ok else 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="staff-fetch", description="Read one public web page, safely.")
    ap.add_argument("url", help="http(s) URL, or 'robots' followed by a URL")
    ap.add_argument("extra", nargs="?", help=argparse.SUPPRESS)
    ap.add_argument("--links", action="store_true", help="list the page's links")
    ap.add_argument("--match", help="regex filter for --links (URL or link text)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--save", action="store_true", help="keep raw body + metadata in the workspace")
    ap.add_argument("--render", choices=("auto", "never", "always"), default="auto")
    ap.add_argument("--wait", help="CSS selector to wait for (browser step)")
    ap.add_argument("--lang", help="preferred language, e.g. ar, fr, es-MX")
    ap.add_argument("--max-chars", type=int, default=TEXT_DEFAULT)
    a = ap.parse_args(argv)
    _kit.require("fetch")
    try:
        if a.url == "robots":
            if not a.extra:
                ap.error("usage: staff-fetch robots <url>")
            return cmd_robots(a.extra)
        if a.extra:
            ap.error("one URL at a time (quote URLs that contain & or ?)")
        res = fetch_page(a.url, render=a.render, lang=a.lang, wait=a.wait)
    except Wall as e:
        sys.stderr.write("WALL: %s\n" % e)
        return 3
    except FetchError as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1
    if a.json:
        out = {k: v for k, v in res.items() if k != "raw"}
        if "page" in out:
            pg = dict(out["page"])
            pg["text"] = pg["text"][:a.max_chars]
            pg["links"] = pg["links"][:200]
            pg["embedded"] = [{"kind": e["kind"], "chars": e["chars"]} for e in pg["embedded"]]
            pg["jsonld"] = pg["jsonld"][:5]
            out["page"] = pg
        if "json" in out:
            text = json.dumps(out.pop("json"), ensure_ascii=False)
            out["saved"]["json"] = save_text("pages", _page_name(res.get("final_url", res["url"]), ".json"), text)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0
    _print_result(res, a)
    if a.save:
        _save_all(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
