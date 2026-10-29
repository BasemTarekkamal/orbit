"""Tests for the toolbelt (core/tools: fetch, browse, apify, watch, docs) and its bin/ shims.

    cd ~/staffroom && python3 -m unittest tests.test_tools -v

Offline except the live smoke tests (example.com), which skip without internet. Nothing here
starts an Apify run: the HTTP layer is mocked. Uses temporary STAFFROOM_HOME / STAFF_WORKSPACE
folders; STAFF_EMPLOYEE stays unset, so no ability checks.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(KIT, "core", "tools")
BIN = os.path.join(KIT, "bin")
TMP = tempfile.mkdtemp(prefix="staff-tools-test-")
HOME = os.path.join(TMP, "home")
WS = os.path.join(TMP, "workspace")
os.makedirs(HOME)
os.makedirs(WS)
os.environ.pop("STAFF_EMPLOYEE", None)
os.environ["STAFFROOM_HOME"] = HOME
os.environ["STAFF_WORKSPACE"] = WS
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import _kit  # noqa: E402

_kit.HOME = HOME            # in case another test module imported _kit first with a different home
import fetch  # noqa: E402
import browse  # noqa: E402
import apify  # noqa: E402
import watch  # noqa: E402
import docs  # noqa: E402

PUBLIC_IP = "93.184.215.14"   # an IP literal resolves offline; it is a global address


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def online(host="example.com", port=443) -> bool:
    try:
        socket.create_connection((host, port), 3).close()
        return True
    except OSError:
        return False


class FakeResp:
    def __init__(self, status=200, body=b"", headers=None, url=""):
        self.status_code, self._body, self.url = status, body, url
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]

    def close(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        fetch._ROBOTS.clear()
        shutil.rmtree(os.path.join(HOME, "cache"), ignore_errors=True)
        p = mock.patch.object(fetch, "MIN_INTERVAL", 0.0)
        p.start()
        self.addCleanup(p.stop)


# ---------------------------------------------------------------------------------------------
# The URL boundary


class SafeUrlTests(Base):
    BAD = ["http://127.0.0.1/", "http://127.0.0.1:8765/panel", "http://localhost/", "http://LOCALHOST:3000/x",
           "http://foo.localhost/", "http://10.0.0.1/", "http://10.255.1.2:8080/", "http://192.168.1.1/",
           "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd",
           "ftp://example.com/file", "http://[::1]/", "http://[::1]:8080/", "http://0.0.0.0/",
           "http://2130706433/", "http://[::ffff:127.0.0.1]/", "http://printer.local/", "javascript:alert(1)",
           "http:///nohost"]

    def test_rejections(self):
        for url in self.BAD:
            with self.subTest(url=url):
                with self.assertRaises(fetch.Wall):
                    fetch.check_url(url)
                with self.assertRaises(fetch.Wall):
                    fetch.http_get(url)

    def test_public_ip_passes(self):
        self.assertEqual(fetch.check_url("http://%s/a" % PUBLIC_IP), "http://%s/a" % PUBLIC_IP)

    def test_ip_ok(self):
        self.assertFalse(fetch.ip_ok("127.0.0.1"))
        self.assertFalse(fetch.ip_ok("::ffff:192.168.0.1"))
        self.assertFalse(fetch.ip_ok("fe80::1%en0"))
        self.assertTrue(fetch.ip_ok(PUBLIC_IP))

    def test_socket_guard_blocks_private_connect(self):
        fetch.install_socket_guard()
        import urllib3.util.connection as uc
        with self.assertRaises(OSError) as cm:
            uc.create_connection(("127.0.0.1", 9), timeout=1)
        self.assertIn("STAFF-BLOCKED", str(cm.exception))

    def test_redirect_to_private_blocked(self):
        for target in ("http://127.0.0.1:8765/", "http://localhost/admin", "http://192.168.0.10/",
                       "file:///etc/passwd"):
            calls = []

            def fake(url, headers, target=target):
                calls.append(url)
                return FakeResp(302, headers={"Location": target})
            with self.subTest(target=target), mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                    mock.patch.object(fetch, "_request", side_effect=fake):
                with self.assertRaises(fetch.Wall):
                    fetch.http_get("http://%s/start" % PUBLIC_IP)
                self.assertEqual(calls, ["http://%s/start" % PUBLIC_IP])   # never requested the target

    def test_redirect_to_login_is_a_wall(self):
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", return_value=FakeResp(302, headers={"Location": "/accounts/login/?next=/x"})):
            with self.assertRaises(fetch.Wall):
                fetch.http_get("http://%s/x" % PUBLIC_IP)

    def test_public_redirect_followed(self):
        seq = [FakeResp(301, headers={"Location": "/new"}),
               FakeResp(200, b"<html><title>ok</title><body>hi</body></html>")]
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", side_effect=seq):
            r = fetch.http_get("http://%s/old" % PUBLIC_IP)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.hops, ["301 http://%s/old" % PUBLIC_IP])

    def test_redirects_through_the_real_session(self):
        """Regression: max_redirects=0 on the session made requests raise on any redirect."""
        import requests

        class Adapter(requests.adapters.BaseAdapter):
            def send(self, request, **kw):
                r = requests.Response()
                r.request, r.url, r.raw = request, request.url, io.BytesIO(b"<html><body>landed</body></html>")
                if request.url.endswith("/old"):
                    r.status_code, r.headers["Location"] = 302, "/new"
                else:
                    r.status_code, r.headers["content-type"] = 200, "text/html"
                return r

            def close(self):
                pass
        s = fetch.session()
        s.mount("http://%s/" % PUBLIC_IP, Adapter())
        try:
            with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")):
                r = fetch.http_get("http://%s/old" % PUBLIC_IP)
        finally:
            s.adapters.pop("http://%s/" % PUBLIC_IP, None)
        self.assertEqual((r.status, r.ctype, r.url), (200, "text/html", "http://%s/new" % PUBLIC_IP))

    def test_lowercase_headers(self):
        body = json.dumps([{"a": 1}]).encode()
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", return_value=FakeResp(200, body, {"content-type": "application/json"})):
            self.assertEqual(fetch.fetch_page("http://%s/x" % PUBLIC_IP, render="never")["kind"], "json")

    def test_size_cap_on_files(self):
        big = FakeResp(200, b"%PDF-" + b"x" * 100, {"Content-Type": "application/pdf", "Content-Length": str(10 ** 9)})
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", return_value=big):
            with self.assertRaises(fetch.FetchError):
                fetch.http_get("http://%s/huge.pdf" % PUBLIC_IP)


# ---------------------------------------------------------------------------------------------
# robots.txt


class RobotsTests(Base):
    def test_longest_match_and_allow(self):
        rb = fetch.Robots("User-agent: *\nDisallow: /private\nAllow: /private/ok\nDisallow: /*.pdf$\n", 200)
        self.assertFalse(rb.allowed("https://s.test/private/x"))
        self.assertTrue(rb.allowed("https://s.test/private/ok/page"))
        self.assertTrue(rb.allowed("https://s.test/public"))
        self.assertFalse(rb.allowed("https://s.test/a/b.pdf"))
        self.assertTrue(rb.allowed("https://s.test/a/b.pdf?download=1"))

    def test_specific_group_wins(self):
        rb = fetch.Robots("User-agent: *\nDisallow: /\n\nUser-agent: StaffroomBot\nAllow: /\nDisallow: /secret\n", 200)
        self.assertTrue(rb.allowed("https://s.test/page"))
        self.assertFalse(rb.allowed("https://s.test/secret/1"))
        rb2 = fetch.Robots("User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n", 200)
        self.assertFalse(rb2.allowed("https://s.test/page"))

    def test_grouped_agents_and_delay(self):
        rb = fetch.Robots("User-agent: a\nUser-agent: *\nCrawl-delay: 4\nDisallow: /x\nSitemap: https://s.test/sm.xml\n", 200)
        self.assertFalse(rb.allowed("https://s.test/x/1"))
        self.assertEqual(rb.delay(), 4.0)
        self.assertEqual(rb.sitemaps, ["https://s.test/sm.xml"])

    def test_status_rules(self):
        self.assertFalse(fetch.Robots("", 503).allowed("https://s.test/"))
        self.assertTrue(fetch.Robots("", 404).allowed("https://s.test/"))
        self.assertTrue(fetch.Robots("", 0, "robots.txt unreachable").allowed("https://s.test/"))

    def test_http_get_respects_robots(self):
        calls = []

        def fake(url, headers):
            calls.append(url)
            return FakeResp(200, b"<html>x</html>")
        with mock.patch.object(fetch, "_robots_txt", return_value=(200, "User-agent: *\nDisallow: /no\n")), \
                mock.patch.object(fetch, "_request", side_effect=fake):
            with self.assertRaises(fetch.Wall):
                fetch.http_get("http://%s/no/page" % PUBLIC_IP)
            self.assertEqual(calls, [])
            fetch.http_get("http://%s/yes" % PUBLIC_IP)
            self.assertEqual(calls, ["http://%s/yes" % PUBLIC_IP])

    def test_html_robots_retried_with_browser_agent(self):
        seen = []

        def fake(url, headers):
            seen.append(headers["User-Agent"])
            if len(seen) == 1:
                return FakeResp(200, b"<!DOCTYPE html><html>login</html>")
            return FakeResp(200, b"User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"})
        with mock.patch.object(fetch, "_request", side_effect=fake):
            status, text = fetch._robots_txt("http://%s" % PUBLIC_IP)
        self.assertEqual(seen[0], fetch.ROBOTS_UA)
        self.assertIn("Disallow: /", text)

    def test_robots_cache(self):
        with mock.patch.object(fetch, "_robots_txt", return_value=(200, "User-agent: *\nDisallow: /a\n")) as m:
            fetch.robots_for("http://%s/x" % PUBLIC_IP)
            fetch._ROBOTS.clear()
            fetch.robots_for("http://%s/y" % PUBLIC_IP)    # from the on-disk cache
            self.assertEqual(m.call_count, 1)

    def test_throttle_spaces_requests(self):
        with mock.patch.object(fetch, "MIN_INTERVAL", 0.3):
            t0 = time.time()
            fetch.throttle("throttle.test", 0.3)
            fetch.throttle("throttle.test", 0.3)
            self.assertGreaterEqual(time.time() - t0, 0.25)


# ---------------------------------------------------------------------------------------------
# Understanding pages


PAGE = b"""<!doctype html><html lang="ar"><head><title>T</title>
<meta property="og:title" content="Story title"><meta name="description" content="A summary.">
<meta property="article:published_time" content="2026-10-01T09:00:00Z">
<link rel="canonical" href="https://news.test/story">
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"NewsArticle",
 "headline":"Story title","datePublished":"2026-10-01","author":{"@type":"Person","name":"R. Writer"}},
 {"@type":"Organization","name":"News Co","telephone":"+1 555 0100"}]}</script>
<script id="__NEXT_DATA__" type="application/json">%s</script>
</head><body><nav>Home | About</nav><article><h1>Story title</h1><p>%s</p>
<p>Call <a href="tel:+15550100">us</a> or <a href="mailto:desk@news.test">email</a>.
<a href="https://www.facebook.com/newsco">fb</a> <a href="/next">Next story</a></p></article>
<script>fetch("/api/v2/stories?page=2")</script></body></html>""" % (
    json.dumps({"props": {"items": [{"id": i} for i in range(200)]}}).encode(), ("Body text. " * 60).encode())


class ParseTests(Base):
    def test_html_metadata(self):
        pg = fetch.parse_html(PAGE, "https://news.test/story")
        self.assertEqual(pg["title"], "Story title")
        self.assertEqual(pg["description"], "A summary.")
        self.assertEqual(pg["lang"], "ar")
        self.assertTrue(pg["published"].startswith("2026-10-01"))
        self.assertEqual(pg["author"], "R. Writer")
        self.assertEqual(pg["canonical"], "https://news.test/story")
        self.assertIn("https://news.test/feed.xml", pg["feeds"])
        self.assertTrue(any(h.endswith("/api/v2/stories?page=2") for h in pg["api_hints"]))
        self.assertEqual(pg["contacts"]["emails"], ["desk@news.test"])
        self.assertEqual(pg["contacts"]["phones"], ["+15550100"])
        self.assertIn("https://www.facebook.com/newsco", pg["contacts"]["socials"])
        self.assertEqual([e["kind"] for e in pg["embedded"]], ["__NEXT_DATA__"])
        self.assertTrue(any("NewsArticle" in b for b in pg["jsonld_brief"]))
        self.assertIn("# Story title", pg["text"])
        self.assertNotIn("Home | About", pg["text"])
        self.assertFalse(pg["js_shell"])
        self.assertIn({"text": "Next story", "href": "https://news.test/next"}, pg["links"])

    def test_js_shell_detected(self):
        pg = fetch.parse_html(b'<html><body><div id="root"></div><script src="/app.js"></script></body></html>',
                              "https://app.test/")
        self.assertTrue(pg["js_shell"])

    def test_wall_markers(self):
        self.assertTrue(fetch.wall_reason("<title>Just a moment...</title>", 403, 20))
        self.assertIsNone(fetch.wall_reason("<div class='g-recaptcha'>comment form</div>", 200, 9000))

    def test_rss_atom_sitemap(self):
        rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
          <item><title>One &amp; only</title><link>https://s.test/1</link><guid>g1</guid>
          <pubDate>Tue, 28 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Hi&lt;/p&gt;</description></item>
          </channel></rss>"""
        f = fetch.parse_feed(rss)
        self.assertEqual((f["kind"], f["title"]), ("rss", "Feed"))
        self.assertEqual(f["items"][0], {"id": "g1", "title": "One & only", "link": "https://s.test/1",
                                         "date": "2026-10-28 10:00Z", "summary": "Hi"})
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><entry><id>e1</id><title>E</title>
          <link rel="alternate" href="https://s.test/e"/><updated>2026-10-27T08:00:00Z</updated></entry></feed>"""
        self.assertEqual(fetch.parse_feed(atom)["items"][0]["link"], "https://s.test/e")
        sm = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://s.test/a</loc>
          <lastmod>2026-10-01</lastmod></url></urlset>"""
        self.assertEqual(fetch.parse_feed(sm)["items"][0]["link"], "https://s.test/a")

    def test_entity_xml_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss>&b;</rss>'
        with self.assertRaises(fetch.FetchError):
            fetch.parse_feed(bomb)

    def test_fetch_page_json_and_pdf(self):
        body = json.dumps({"data": {"items": [{"id": 1, "t": "x"}, {"id": 2, "t": "y"}]}}).encode()
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", return_value=FakeResp(200, body, {"Content-Type": "application/json"})):
            res = fetch.fetch_page("http://%s/api/items" % PUBLIC_IP, render="never")
        self.assertEqual((res["kind"], res["records"], res["records_path"]), ("json", 2, "data.items"))
        pdf = b"%PDF-1.4 fake"
        with mock.patch.object(fetch, "_robots_txt", return_value=(404, "")), \
                mock.patch.object(fetch, "_request", return_value=FakeResp(200, pdf, {"Content-Type": "application/pdf"})):
            res = fetch.fetch_page("http://%s/doc/report.pdf" % PUBLIC_IP, render="never")
        self.assertEqual(res["kind"], "file")
        self.assertTrue(res["saved"]["file"].startswith(os.path.realpath(WS)) or res["saved"]["file"].startswith(WS))
        self.assertTrue(res["saved"]["file"].endswith(".pdf"))
        self.assertIn("staff-docs text", res["notes"][0])


# ---------------------------------------------------------------------------------------------
# The browser's request filter (no browser needed)


class FakeFrame:
    parent_frame = None


class FakeRequest:
    def __init__(self, url, method="GET", rtype="document", nav=False):
        self.url, self.method, self.resource_type, self._nav, self.frame = url, method, rtype, nav, FakeFrame()

    def is_navigation_request(self):
        return self._nav


class FakeRoute:
    def __init__(self):
        self.result = None

    def continue_(self):
        self.result = "continue"

    def abort(self, reason=None):
        self.result = "abort"


class BrowserGuardTests(Base):
    def run_route(self, guard, req):
        r = FakeRoute()
        guard.route(r, req)
        return r.result

    def test_filter(self):
        g = browse._Guard(block_media=True)
        with mock.patch.object(fetch, "_robots_txt", return_value=(200, "User-agent: *\nDisallow: /private\n")):
            self.assertEqual(self.run_route(g, FakeRequest("http://%s/form" % PUBLIC_IP, "POST", "xhr")), "abort")
            self.assertEqual(self.run_route(g, FakeRequest("http://127.0.0.1:8765/api", "GET", "fetch")), "abort")
            self.assertEqual(self.run_route(g, FakeRequest("http://192.168.1.1/", "GET", "image")), "abort")
            self.assertEqual(self.run_route(g, FakeRequest("http://%s/a.png" % PUBLIC_IP, "GET", "image")), "abort")
            self.assertEqual(self.run_route(g, FakeRequest("http://%s/data.json" % PUBLIC_IP, "GET", "xhr")), "continue")
            self.assertEqual(self.run_route(g, FakeRequest("http://%s/private/x" % PUBLIC_IP, nav=True)), "abort")
            self.assertTrue(g.robots_wall)
        self.assertIn("http://%s/data.json" % PUBLIC_IP, g.data_requests)

    def test_click_words(self):
        for bad in ("Log in", "Sign up", "Accept all cookies", "Buy now", "Submit", "Send message",
                    "تسجيل الدخول", "Add to cart"):
            self.assertTrue(browse.DENY_CLICK.search(bad), bad)
        for ok in ("Load more", "Show more", "Reject all", "Show transcript", "Next page", "Reviews", "عرض المزيد"):
            self.assertFalse(browse.DENY_CLICK.search(ok), ok)


# ---------------------------------------------------------------------------------------------
# Apify gateway (HTTP mocked: nothing is ever run)


class ApifyTests(Base):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(HOME, ".secrets"), exist_ok=True)
        with open(os.path.join(HOME, ".secrets", "apify_token"), "w") as fh:
            fh.write("test-token")
        self.set_config(5.0, 0.5)
        try:
            os.remove(apify.ledger_path())
        except OSError:
            pass

    def set_config(self, monthly, per_run):
        with open(os.path.join(HOME, "staff.json"), "w") as fh:
            json.dump({"apify": {"monthly_budget_usd": monthly, "max_run_usd": per_run}}, fh)

    def test_catalog_shape(self):
        self.assertGreaterEqual(len(apify.CATALOG), 15)
        for alias, spec in apify.CATALOG.items():
            with self.subTest(alias=alias):
                self.assertRegex(alias, r"^[a-z][a-z0-9-]*$")
                self.assertRegex(spec["actor"], r"^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$")
                for k in ("what", "cost", "verified"):
                    self.assertTrue(spec.get(k), k)
                self.assertTrue(spec.get("needs"))
                self.assertIsInstance(spec.get("defaults", {}), dict)
                self.assertGreater(spec.get("items", 0), 0)
                inp, dropped, notes = apify.build_input(alias, apify.example_input(alias), 10)   # examples are valid
                self.assertEqual(dropped, [])
        covered = " ".join(apify.CATALOG)
        for need in ("google-search", "crawl", "rag-browser", "maps-places", "maps-reviews", "google-news",
                     "google-trends", "youtube", "youtube-transcript", "x", "tiktok", "instagram", "facebook-page",
                     "facebook-posts", "fb-ads", "linkedin-company", "reddit"):
            self.assertIn(need, covered)

    def test_no_arbitrary_actors(self):
        with self.assertRaises(ValueError):
            apify.resolve("someone/evil-actor")
        self.assertEqual(apify.resolve("apify/instagram-scraper"), "instagram")
        self.assertEqual(apify.resolve("tweets"), "x")

    def test_sanitising(self):
        user = {"postURLs": ["https://www.tiktok.com/@a/video/1"], "webhooks": [{"requestUrl": "https://evil.test"}],
                "proxyConfiguration": {"proxyUrls": ["http://evil.test:8080"]}, "outputConnector": "notion",
                "maxFollowersPerProfile": 500, "shouldDownloadVideos": True, "resultsPerPage": 5000,
                "initialCookies": [{"name": "sessionid", "value": "x"}], "customMapFunction": "(o) => o"}
        inp, dropped, notes = apify.build_input("tiktok", user, 10)
        for k in ("webhooks", "proxyConfiguration", "outputConnector", "maxFollowersPerProfile", "initialCookies",
                  "customMapFunction"):
            self.assertNotIn(k, inp)
            self.assertIn(k, dropped)
        self.assertIs(inp["shouldDownloadVideos"], False)
        self.assertEqual(inp["resultsPerPage"], 10)
        crawl, dropped, _ = apify.build_input("crawl", {"startUrls": [
            {"url": "https://s.test/", "method": "POST", "payload": "a=1", "headers": {"Cookie": "x"}}, "https://s.test/b"]}, 10)
        self.assertEqual(crawl["startUrls"], [{"url": "https://s.test/"}, {"url": "https://s.test/b"}])
        self.assertIs(crawl["respectRobotsTxtFile"], True)
        self.assertEqual(crawl["proxyConfiguration"], {"useApifyProxy": True})      # the gateway's own default
        red, dropped, _ = apify.build_input("reddit", {"searchTerms": ["x"], "mcpServerUrl": "https://evil.test",
                                                       "mcpServerToken": "t", "includeNSFW": True}, 10)
        self.assertNotIn("mcpServerUrl", red)
        self.assertIs(red["includeNSFW"], False)
        maps, _, _ = apify.build_input("maps-reviews", {"startUrls": ["https://maps.test/p"], "personalData": True}, 10)
        self.assertIs(maps["personalData"], False)
        with self.assertRaises(ValueError):
            apify.build_input("tiktok", {"resultsPerPage": 5}, 10)        # no source at all
        with self.assertRaises(ValueError):
            apify.build_input("crawl", {"startUrls": ["file:///etc/passwd"]}, 10)

    def test_budget_refusal(self):
        self.set_config(1.0, 0.5)
        with apify.Ledger() as lg:
            lg.data["runs"].append({"id": "old", "month": apify.month(), "cost_usd": 0.8, "alias": "x"})
            lg.save()
        with mock.patch.object(apify, "_http") as http:
            with self.assertRaises(PermissionError) as cm:
                apify.cmd_run("google-search", '{"queries": "test"}')
            http.assert_not_called()
        self.assertIn("ask them to raise", str(cm.exception))

    def test_cap_limits(self):
        with mock.patch.object(apify, "_http") as http:
            with self.assertRaises(ValueError):
                apify.cmd_run("x", '{"searchTerms": ["a"]}', max_usd="1.5")   # over the owner's $0.50 cap
            self.set_config(5.0, 0.3)
            with self.assertRaises(ValueError):
                apify.cmd_run("tiktok", '{"postURLs": ["https://t.test/1"]}')  # tiktok needs a $0.50 cap
            http.assert_not_called()
        self.set_config(5.0, 50)
        self.assertEqual(apify.settings()["max_run"], apify.HARD_MAX_RUN_USD)

    def test_mocked_run(self):
        calls = []
        run_done = {"id": "run1", "status": "SUCCEEDED", "defaultDatasetId": "ds1", "usageTotalUsd": 0.001,
                    "pricingInfo": {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": {
                        "result": {"eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": 0.004}}}}}},
                    "chargedEventCounts": {"result": 3}}

        def fake(method, path, params=None, body=None, auth=True, timeout=90):
            calls.append((method, path, params, body))
            if method == "POST":
                return {"data": {"id": "run1", "status": "RUNNING", "defaultDatasetId": "ds1"}}
            if path.startswith("/actor-runs/"):
                return {"data": run_done}
            if path.startswith("/datasets/"):
                return [{"title": "Video %d" % i, "url": "https://y.test/%d" % i} for i in range(3)]
            raise AssertionError(path)
        out = io.StringIO()
        with mock.patch.object(apify, "_http", side_effect=fake), redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = apify.cmd_run("youtube", '{"searchQueries": ["heat pumps"], "webhooks": [1]}', max_items="5",
                               tag="Heat Pumps!")
        self.assertEqual(rc, 0)
        method, path, params, body = calls[0]
        self.assertEqual((method, path), ("POST", "/acts/streamers~youtube-scraper/runs"))
        self.assertEqual(params["maxItems"], 5)
        self.assertLessEqual(float(params["maxTotalChargeUsd"]), 0.5)
        self.assertNotIn("webhooks", body)
        self.assertEqual(body["maxResults"], 5)
        with apify.Ledger() as lg:
            run = lg.data["runs"][-1]
        self.assertAlmostEqual(run["cost_usd"], 0.013, places=4)
        self.assertEqual(run["status"], "SUCCEEDED")
        files = os.listdir(os.path.join(WS, "research", "scrapes"))
        self.assertTrue(any(f.endswith("-youtube-heat-pumps.json") for f in files), files)
        self.assertIn("3 items", out.getvalue())

    def test_unfinished_run_keeps_reservation(self):
        def fake(method, path, params=None, body=None, auth=True, timeout=90):
            return {"data": {"id": "run2", "status": "RUNNING", "defaultDatasetId": "ds2"}}
        with mock.patch.object(apify, "_http", side_effect=fake), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()), mock.patch.object(apify, "DEFAULT_WAIT_S", 10), \
                mock.patch("time.sleep"):
            apify.cmd_run("x", '{"searchTerms": ["a"]}', wait="10")
        with apify.Ledger() as lg:
            spent, pending = apify.month_spend(lg.data)
        self.assertEqual((spent, pending), (0.0, 0.5))

    def test_input_file_must_be_in_workspace(self):
        with open(os.path.join(WS, "in.json"), "w") as fh:
            fh.write('{"queries": "a"}')
        self.assertEqual(apify._read_input("@in.json"), {"queries": "a"})
        with self.assertRaises(ValueError):
            apify._read_input("@../../etc/passwd")

    def test_run_cost(self):
        self.assertEqual(apify.run_cost({"usageTotalUsd": 0.05}), 0.05)
        ppr = {"usageTotalUsd": 0, "pricingInfo": {"pricingModel": "PRICE_PER_DATASET_ITEM", "pricePerUnitUsd": 0.002}}
        self.assertEqual(apify.run_cost(ppr, 10), 0.02)


# ---------------------------------------------------------------------------------------------
# Watchers (fetcher injected: no network)


def rss(*items):
    body = "".join("<item><title>%s</title><link>https://s.test/%s</link><guid>%s</guid></item>" % (t, i, i)
                   for i, t in items)
    return ("<?xml version='1.0'?><rss version='2.0'><channel><title>F</title>%s</channel></rss>" % body).encode()


class WatchTests(Base):
    def setUp(self):
        super().setUp()
        shutil.rmtree(os.path.join(WS, "state"), ignore_errors=True)
        self.content = {}

    def fetcher(self, url):
        ctype, data = self.content[url]
        return url, ctype, data

    def quiet(self, fn, *a, **kw):
        with redirect_stdout(io.StringIO()):
            return fn(*a, **kw)

    def test_feed_seed_new_dry_run(self):
        url = "http://%s/feed" % PUBLIC_IP
        self.content[url] = ("application/rss+xml", rss(("1", "Old news"), ("2", "Older news")))
        self.quiet(watch.cmd_add, "news", url, "auto", None, None, None, fetcher=self.fetcher)
        self.assertEqual(watch.check(fetcher=self.fetcher)["new"], [])         # seeded: nothing on first check
        self.content[url] = ("application/rss+xml", rss(("3", "Fresh story"), ("1", "Old news"), ("2", "Older news")))
        r1 = watch.check(dry_run=True, fetcher=self.fetcher)
        r2 = watch.check(dry_run=True, fetcher=self.fetcher)
        self.assertEqual([i["title"] for i in r1["new"]], ["Fresh story"])
        self.assertEqual(r1["new"], r2["new"])                                  # dry run marks nothing
        self.assertEqual(len(watch.check(fetcher=self.fetcher)["new"]), 1)
        self.assertEqual(watch.check(fetcher=self.fetcher)["new"], [])
        self.assertEqual(watch.load()["watches"]["news"]["kind"], "rss")

    def test_match_filter_and_errors(self):
        url = "http://%s/feed2" % PUBLIC_IP
        self.content[url] = ("application/rss+xml", rss(("1", "a")))
        self.quiet(watch.cmd_add, "grants", url, "rss", "grant|منحة", None, None, fetcher=self.fetcher)
        self.content[url] = ("application/rss+xml", rss(("2", "New grant round"), ("3", "Sports"), ("4", "إعلان منحة جديدة"),
                                                         ("1", "a")))
        titles = [i["title"] for i in watch.check(fetcher=self.fetcher)["new"]]
        self.assertEqual(titles, ["New grant round", "إعلان منحة جديدة"])

        def broken(u):
            raise fetch.FetchError("HTTP 500")
        r = watch.check(fetcher=broken)
        self.assertEqual(r["errors"][0]["name"], "grants")

    def test_page_changes(self):
        url = "http://%s/prices" % PUBLIC_IP
        page = "<html><body><main><h2>Prices</h2><p>Plan A 10</p><p>Plan B 20</p><p>Updated 1 min ago</p></main></body></html>"
        self.content[url] = ("text/html", page.encode())
        self.quiet(watch.cmd_add, "prices", url, "page", None, "main", "updated", fetcher=self.fetcher)
        self.assertEqual(watch.check(fetcher=self.fetcher)["changed"], [])
        self.content[url] = ("text/html", page.replace("Plan B 20", "Plan B 25").replace("1 min", "9 min").encode())
        ch = watch.check(fetcher=self.fetcher)["changed"]
        self.assertEqual((ch[0]["added"], ch[0]["removed"]), (["Plan B 25"], ["Plan B 20"]))
        self.content[url] = ("text/html", page.replace("Plan B 20", "Plan B 25").encode())
        self.assertEqual(watch.check(fetcher=self.fetcher)["changed"], [])     # only the ignored line changed
        self.quiet(watch.cmd_remove, "prices")
        self.assertNotIn("prices", watch.load()["watches"])

    def test_names_and_urls_validated(self):
        with self.assertRaises(ValueError):
            watch.cmd_add("../evil", "http://%s/" % PUBLIC_IP, "auto", None, None, None, fetcher=self.fetcher)
        with self.assertRaises(fetch.Wall):
            watch.cmd_add("lan", "http://192.168.1.1/", "auto", None, None, None, fetcher=self.fetcher)


# ---------------------------------------------------------------------------------------------
# Documents


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with Helvetica text, built by hand (no libraries)."""
    stream = ("BT /F1 24 Tf 72 700 Td (%s) Tj ET" % text).encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def tiny_xlsx(path: str) -> None:
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s %s><sheets><sheet name="Prices" sheetId="1" r:id="rId1"/>'
                                      '</sheets></workbook>' % (ns, rns))
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", '<sst %s><si><t>Crop</t></si><si><t>Price</t></si><si><t>Wheat</t></si>'
                                           '</sst>' % ns)
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet %s><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
                   '<c r="B1" t="s"><v>1</v></c></row><row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>12.5</v>'
                   '</c></row></sheetData></worksheet>' % ns)


class DocsTests(Base):
    def setUp(self):
        super().setUp()
        self.pdf = os.path.join(WS, "hello.pdf")
        with open(self.pdf, "wb") as fh:
            fh.write(tiny_pdf("Hello Staffroom 2026"))

    def test_pdf_text(self):
        engines = (["pypdf"] if _has("pypdf") else []) + (["pdftotext"] if docs._bin("pdftotext") else [])
        if not engines:
            self.skipTest("no PDF text engine without swift")
        pages, eng = docs.pdf_text(self.pdf, [1], engines[0])
        self.assertIn("Hello Staffroom 2026", pages[1])
        self.assertEqual(docs.pdf_page_count(self.pdf), 1)

    def test_cli_saves_into_workspace(self):
        env = dict(os.environ, STAFFROOM_HOME=HOME, STAFF_WORKSPACE=WS)
        env.pop("STAFF_EMPLOYEE", None)
        r = subprocess.run([os.path.join(BIN, "staff-docs"), "text", self.pdf], capture_output=True, text=True,
                           env=env, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Hello Staffroom 2026", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(WS, "research", "docs", "hello-text.txt")))

    def test_xlsx_and_csv_tables(self):
        x = os.path.join(WS, "prices.xlsx")
        tiny_xlsx(x)
        self.assertEqual(docs._xlsx_rows(x), {"Prices": [["Crop", "Price"], ["Wheat", "", "12.5"]]})
        c = os.path.join(WS, "p.csv")
        with open(c, "w", encoding="utf-8") as fh:
            fh.write("crop;price\nقمح;12,5\n")
        self.assertEqual(docs._csv_rows(c), [["crop", "price"], ["قمح", "12,5"]])

    def test_forms_fixed_only(self):
        self.assertEqual(docs._fix_forms("\ufefb\u202b"), "لا")      # lam-alef ligature, bidi mark
        self.assertEqual(docs._fix_forms("m\u00b2 \u2460"), "m\u00b2 \u2460")  # other characters untouched

    @unittest.skipUnless(shutil.which("swiftc") and sys.platform == "darwin" and os.environ.get("STAFF_TEST_OCR") != "0",
                         "macOS swiftc needed (set STAFF_TEST_OCR=0 to skip)")
    def test_ocr_with_vision(self):
        pages = docs.ocr(self.pdf)            # renders the page with PDFKit, reads it with Vision
        self.assertIn("Hello", pages.get(1, ""))


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------------------------
# Shims and live smoke tests


class ShimTests(unittest.TestCase):
    def test_shims_exist_and_run(self):
        env = dict(os.environ, STAFFROOM_HOME=HOME, STAFF_WORKSPACE=WS)
        env.pop("STAFF_EMPLOYEE", None)
        for name in ("staff-fetch", "staff-browse", "staff-apify", "staff-watch", "staff-docs"):
            with self.subTest(name=name):
                path = os.path.join(BIN, name)
                self.assertTrue(os.access(path, os.X_OK), path)
                with open(path) as fh:
                    self.assertTrue(fh.readline().startswith("#!/bin/sh"))
                r = subprocess.run([path, "--help"], capture_output=True, text=True, env=env, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_shim_through_symlink(self):
        link_dir = os.path.join(TMP, "linked-bin")
        os.makedirs(link_dir, exist_ok=True)
        link = os.path.join(link_dir, "staff-watch")
        if not os.path.lexists(link):
            os.symlink(os.path.join(BIN, "staff-watch"), link)
        env = dict(os.environ, STAFFROOM_HOME=HOME, STAFF_WORKSPACE=WS)
        r = subprocess.run([link, "list"], capture_output=True, text=True, env=env, timeout=60, cwd="/")
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(online(), "offline")
class LiveSmokeTests(unittest.TestCase):
    def run_tool(self, *args, timeout=120):
        env = dict(os.environ, STAFFROOM_HOME=HOME, STAFF_WORKSPACE=WS)
        env.pop("STAFF_EMPLOYEE", None)
        return subprocess.run(list(args), capture_output=True, text=True, env=env, timeout=timeout)

    def test_fetch_example_com(self):
        r = self.run_tool(os.path.join(BIN, "staff-fetch"), "https://example.com/")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Example Domain", r.stdout)
        self.assertIn("requests", r.stdout)

    def test_fetch_blocks_local(self):
        r = self.run_tool(os.path.join(BIN, "staff-fetch"), "http://127.0.0.1:8765/")
        self.assertEqual(r.returncode, 3)
        self.assertIn("WALL", r.stderr)

    def test_browse_example_com(self):
        if not _has("playwright"):
            self.skipTest("playwright not installed")
        r = self.run_tool(os.path.join(BIN, "staff-browse"), "https://example.com/", "--screenshot", timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Example Domain", r.stdout)
        shot = [l for l in r.stdout.splitlines() if l.startswith("Screenshot: ")]
        self.assertTrue(shot and os.path.exists(shot[0].split(" ")[1]), r.stdout)


if __name__ == "__main__":
    unittest.main()
