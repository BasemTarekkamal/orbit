"""Core tests: abilities, hiring, orders, the engine's command line, the control panel's locks.
Runs against a throwaway team folder; never calls Claude.  python3 -m unittest tests.test_core
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

TMP = tempfile.mkdtemp(prefix="staffroom-test-")
os.environ["STAFFROOM_HOME"] = TMP
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "core"))
sys.path.insert(0, os.path.join(KIT, "core", "tools"))

import abilities  # noqa: E402
import engine  # noqa: E402
import hire  # noqa: E402
import orders  # noqa: E402
import team  # noqa: E402

RUNS = []                                  # employee runs the code asked for; tests never start Claude
team.run_async = lambda *a, **k: RUNS.append((a, k))


def fresh_team():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(os.path.join(TMP, "team"))
    engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex", "aliases": ["B"]}}, "employees": {},
                          "defaults": {"model": "sonnet"}, "panel": {"port": 7398}})


class Abilities(unittest.TestCase):
    def setUp(self):
        fresh_team()

    def test_presets(self):
        cat = abilities.by_id()
        default, sup = set(abilities.preset("default")), set(abilities.preset("super"))
        self.assertTrue(default < sup)
        self.assertNotIn("apify", default)                      # paid: never on by default
        self.assertEqual(sup, {k for k, a in cat.items() if not a.get("locked") and not a.get("consent")})   # consent: only its own switch
        self.assertTrue(all(cat[k].get("default") for k in default))

    def test_validate_drops_locked_and_unknown(self):
        self.assertEqual(abilities.validate(["memory", "web", "bogus", "apify"]), ["apify", "web"])

    def test_tools_and_gateways_follow_ticks(self):
        hire.hire("Tess", "Research", supervisor="Alex", picked=["web", "fetch"])
        allow, block = abilities.tools("tess")
        self.assertIn("WebSearch", allow)
        self.assertIn("Bash(staff-apify *)", block)
        self.assertIn("Bash(staff-browse *)", block)
        self.assertEqual(abilities.commands("tess"), ["staff-fetch", "staff-video"])   # web research includes videos
        self.assertIn("research-playbook", abilities.skills("tess"))
        self.assertNotIn("social-media", abilities.skills("tess"))
        self.assertTrue(abilities.has("tess", "safety"))        # locked: always on


class Hiring(unittest.TestCase):
    def setUp(self):
        fresh_team()

    def test_hire_creates_a_folder_from_templates(self):
        h = hire.hire("Sara Ali", "Market researcher", "Competitors", supervisor="b")
        self.assertEqual(h, "sara-ali")
        ws = os.path.join(TMP, "employees", h)
        for f in ("CLAUDE.md", "STATE.md", "TASKS.md", "LESSONS.md", "GOALS.md", "profile.json", "evals/cases.md"):
            self.assertTrue(os.path.exists(os.path.join(ws, f)), f)
        with open(os.path.join(ws, "CLAUDE.md")) as fh:
            text = fh.read()
        self.assertIn("Sara Ali", text)
        self.assertIn(engine.KIT + "/core/handbook.md", text)
        self.assertNotIn("{", text)
        e = engine.registry()["employees"][h]
        self.assertEqual(e["supervisor"], "Alex")                # alias resolved to the owner
        self.assertEqual(sorted(e["abilities"]), sorted(abilities.preset("default")))
        with open(os.path.join(TMP, "team", "DIRECTORY.md")) as fh:
            self.assertIn("sara-ali", fh.read())

    def test_hire_refuses_bad_input(self):
        with self.assertRaises(hire.HireError):
            hire.hire("Sara", "Role", supervisor="Stranger")
        with self.assertRaises(hire.HireError):
            hire.hire("سارة", "Role", supervisor="Alex")           # needs a Latin handle
        self.assertEqual(hire.hire("سارة", "Role", supervisor="Alex", emp_id="sara"), "sara")
        with self.assertRaises(hire.HireError):
            hire.hire("Sara", "Role", supervisor="Alex")           # already works here
        with self.assertRaises(hire.HireError):
            hire.hire("Team", "Role", supervisor="Alex")           # reserved handle

    def test_status_and_fields(self):
        hire.hire("Tess", "Research", supervisor="Alex")
        hire.set_status("tess", "paused")
        self.assertNotIn("tess", team.active())
        hire.set_status("tess", "active")
        hire.set_field("tess", "model", "haiku")
        self.assertEqual(engine.employee("tess")["model"], "haiku")
        with self.assertRaises(hire.HireError):
            hire.set_field("tess", "model", "gpt-5")
        with self.assertRaises(hire.HireError):
            hire.set_field("tess", "network_domains", ["*"])     # not owner-editable from orders


class Orders(unittest.TestCase):
    def setUp(self):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex")

    def test_super_agent_and_back(self):
        out = orders.execute("Alex", "set_abilities", {"employee_id": "tess", "preset": "super"})
        self.assertIn("(super agent)", out)
        self.assertIn("+Apify scrapers", out)
        self.assertEqual(abilities.effective("tess"), {k for k, a in abilities.by_id().items() if not a.get("consent")})
        out = orders.execute("Alex", "set_abilities", {"employee_id": "tess", "preset": "default"})
        self.assertIn("−Apify scrapers", out)
        rows = team.tail(team.ORDERS)
        self.assertEqual([r["status"] for r in rows], ["done", "done"])

    def test_bad_orders_are_logged_and_refused(self):
        with self.assertRaises(orders.OrderError):
            orders.execute("Alex", "pause", {"employee_id": "nobody"})
        with self.assertRaises(orders.OrderError):
            orders.execute("Alex", "run_job", {"employee_id": "tess", "job": "rm -rf"})
        with self.assertRaises(orders.OrderError):
            orders.execute("Alex", "delete_everything", {})
        self.assertEqual(team.tail(team.ORDERS)[-1]["status"], "failed")

    def test_hire_from_the_panel(self):
        out = orders.execute("Alex", "hire", {"name": "Omar", "role": "Social media", "scope": "x", "preset": "super"})
        self.assertIn("/omar", out)
        self.assertEqual(abilities.effective("omar"), {k for k, a in abilities.by_id().items() if not a.get("consent")})


class Engine(unittest.TestCase):
    def setUp(self):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex", picked=["web", "fetch", "browser"], domains=["api.example.com"])
        hire.hire("Omar", "Social", supervisor="Alex")

    def test_command_line(self):
        emp = engine.employee("tess")
        cmd = engine.command(emp, "sonnet")
        s = json.loads(cmd[cmd.index("--settings") + 1])
        sb = s["sandbox"]
        self.assertTrue(sb["enabled"] and not sb["allowUnsandboxedCommands"] and sb["failIfUnavailable"])
        self.assertTrue(sb["network"]["strictAllowlist"])
        self.assertIn("api.example.com", sb["network"]["allowedDomains"])
        self.assertEqual(sorted(sb["excludedCommands"]), ["staff-browse *", "staff-fetch *", "staff-video *"])
        self.assertIn(os.path.join(TMP, "employees", "omar"), sb["filesystem"]["denyRead"])   # colleagues' folders
        self.assertIn(engine.SECRETS, sb["filesystem"]["denyRead"])
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project")
        dirs = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--plugin-dir"]
        self.assertEqual(dirs[0], engine.GUARD)
        self.assertTrue(dirs[1].startswith(os.path.join(TMP, ".runtime", "tess")))
        denied = cmd[cmd.index("--disallowedTools") + 1:]
        self.assertIn("Bash(staff-apify *)", denied)
        self.assertIn("Bash(git push *)", denied)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")

    def test_clean_env_never_leaks_api_settings(self):
        os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:4000"
        os.environ["ANTHROPIC_API_KEY"] = "sk-not-for-employees"
        try:
            env = engine.clean_env(engine.employee("tess"))
        finally:
            del os.environ["ANTHROPIC_BASE_URL"], os.environ["ANTHROPIC_API_KEY"]
        self.assertFalse([k for k in env if k.startswith("ANTHROPIC_")])
        self.assertEqual(env["STAFF_EMPLOYEE"], "tess")
        self.assertIn("fetch", env["STAFF_ABILITIES"].split(","))
        self.assertTrue(env["PATH"].startswith(engine.BIN + ":"))

    def test_friendly_errors(self):
        self.assertIn("usage limit", engine.friendly_error("Claude AI usage limit reached"))
        self.assertIn("claude auth login", engine.friendly_error("OAuth token has expired; please log in"))


class Panel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex")
        ws = engine.employee("tess")["workspace"]
        os.makedirs(os.path.join(ws, "research"), exist_ok=True)
        with open(os.path.join(ws, "research", "notes.md"), "w") as fh:
            fh.write("# Notes\n\nhello")
        with open(os.path.join(ws, "state", "secret.txt"), "w") as fh:
            fh.write("nope")
        import panel
        cls.panel = panel
        cls.tok = panel.token()
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", panel.port()), panel.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % panel.port()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, path, data=None, headers=None, raw=False):
        body = None if data is None else (data if raw else json.dumps(data).encode())
        h = {"content-type": "application/json"} if data is not None and not raw else {}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=body, headers=h)
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def auth(self, extra=None):
        return {"Cookie": "sr%d=%s" % (self.panel.port(), self.tok), **(extra or {})}

    def test_needs_the_token(self):
        self.assertEqual(self.req("/")[0], 401)
        self.assertEqual(self.req("/api/state")[0], 401)
        self.assertEqual(self.req("/?t=wrong")[0], 403)
        code, h, _ = self.req("/?t=" + self.tok)
        self.assertEqual(code, 303)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Strict", h["Set-Cookie"])

    def test_app_and_api(self):
        for path in ("/", "/team", "/e/tess/memory", "/settings"):
            code, h, body = self.req(path, headers=self.auth())
            self.assertEqual(code, 200, path)
            self.assertIn('<script src="/app.js"', body)
            self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        code, _, body = self.req("/api/state", headers=self.auth())
        st = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual([e["id"] for e in st["employees"]], ["tess"])
        self.assertIn("memory", st["employees"][0]["abilities"])
        self.assertTrue(any(c["id"] == "hire" and c["done"] for c in st["checklist"]))
        code, _, body = self.req("/api/employee/tess", headers=self.auth())
        d = json.loads(body)
        self.assertEqual(code, 200)
        self.assertIn("Tess", d["memory"]["CLAUDE.md"])
        self.assertEqual([f["path"] for f in d["files"]][0], "research/notes.md")          # newest first
        self.assertTrue(all(f["path"].split("/")[0] in ("research", "notes", "tools", "growth", "evals") for f in d["files"]))
        self.assertEqual(self.req("/api/employee/nobody", headers=self.auth())[0], 404)

    def test_files_stay_inside_the_workspace(self):
        code, _, body = self.req("/api/file?emp=tess&path=research/notes.md", headers=self.auth())
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["text"], "# Notes\n\nhello")
        for bad in ("../../staff.json", "state/secret.txt", "/etc/passwd", "profile.json.png", ".git/config"):
            self.assertEqual(self.req("/api/file?emp=tess&path=" + urllib.parse.quote(bad), headers=self.auth())[0], 400, bad)

    def test_rejects_other_hosts_and_origins(self):
        self.assertEqual(self.req("/api/state", headers=self.auth({"Host": "evil.example:7398"}))[0], 403)
        order = {"kind": "pause", "employee_id": "tess"}
        self.assertEqual(self.req("/api/order", order, self.auth({"Origin": "https://evil.example"}))[0], 403)
        self.assertEqual(self.req("/api/order", order, self.auth())[0], 403)               # no Origin at all
        self.assertEqual(self.req("/api/order", order, {"Origin": self.base})[0], 403)      # no cookie
        self.assertEqual(engine.registry()["employees"]["tess"]["status"], "active")

    def test_orders_settings_and_rules(self):
        h = self.auth({"Origin": self.base})
        code, _, body = self.req("/api/order", {"kind": "pause", "employee_id": "tess"}, h)
        self.assertEqual(code, 200)
        self.assertIn("Paused Tess", json.loads(body)["message"])
        self.assertEqual(engine.registry()["employees"]["tess"]["status"], "paused")
        self.req("/api/order", {"kind": "resume", "employee_id": "tess"}, h)
        code, _, body = self.req("/api/order", {"kind": "run_job", "employee_id": "tess", "job": "rm -rf"}, h)
        self.assertEqual(code, 400)
        self.assertIn("Unknown routine", json.loads(body)["error"])
        code, _, body = self.req("/api/employee/tess/rules", {"text": "Reply in Arabic.\nAlways give three options."}, h)
        self.assertEqual(code, 200)
        with open(os.path.join(engine.employee("tess")["workspace"], "CLAUDE.md")) as fh:
            doc = fh.read()
        self.assertTrue(doc.rstrip().endswith("## Role-specific rules\nReply in Arabic.\nAlways give three options."))
        code, _, _ = self.req("/api/settings", {"team_name": "Acme", "workdays": ["Sun", "Mon"], "jobs": {"brief": "07:45", "eod": "99:99"},
                                               "apify": {"monthly_budget_usd": "12", "max_run_usd": "9"}, "network_domains": "api.example.com\nbad host"}, h)
        self.assertEqual(code, 200)
        reg = engine.registry()
        self.assertEqual((reg["team_name"], reg["workdays"], reg["jobs"]["brief"]["at"]), ("Acme", ["Sun", "Mon"], "07:45"))
        self.assertNotIn("eod", reg["jobs"])
        self.assertEqual((reg["apify"]["monthly_budget_usd"], reg["apify"]["max_run_usd"]), (12.0, 2.0))
        self.assertEqual(reg["network_domains"], ["api.example.com"])
        code, _, body = self.req("/api/order", b"not json", self.auth({"Origin": self.base, "content-type": "application/json"}), raw=True)
        self.assertEqual(code, 400)

    def test_access_approvals(self):
        h = self.auth({"Origin": self.base})
        team.jsave(self.panel.PENDING, {"slack:U7": {"name": "Sam", "channel": "slack", "at": "2026-10-29 10:00"},
                                        "discord:5": {"name": "Sam", "channel": "discord", "at": "2026-10-29 10:01"}})
        st = json.loads(self.req("/api/state", headers=self.auth())[2])
        self.assertIn("Sam messaged your Slack bot", [n["title"] for n in st["needs"]])
        code, _, body = self.req("/api/owner", {"id": "slack:U7", "do": "approve", "name": "Sam"}, h)
        self.assertEqual(code, 200, body)
        self.assertEqual(engine.registry()["owners"]["slack:U7"]["name"], "Sam")
        code, _, body = self.req("/api/owner", {"id": "discord:5", "do": "approve", "into": "slack:U7"}, h)
        self.assertEqual(code, 200, body)
        self.assertEqual(engine.owner_key("discord:5"), "slack:U7")
        s = json.loads(self.req("/api/settings", headers=self.auth())[2])
        self.assertEqual(sorted(s["channels"]), ["discord", "slack", "telegram"])
        st = json.loads(self.req("/api/state", headers=self.auth())[2])
        sam = next(o for o in st["owners"] if o["id"] == "slack:U7")
        self.assertEqual(sam["addresses"], ["Slack id U7", "Discord id 5"])
        self.assertEqual(self.req("/api/owner", {"id": "slack:U7", "do": "approve"}, h)[0], 400)   # gone

    def test_skills_api(self):
        h = self.auth({"Origin": self.base})
        code, _, body = self.req("/api/skill", {"emp": "tess", "do": "create", "name": "digest-format", "text": "Steps\n1. Three bullets.\n2. Sources inline.\n",
                                                "description": "How Alex wants the Monday digest. Use when asked for the digest."}, h)
        self.assertEqual(code, 200, body)
        d = json.loads(self.req("/api/employee/tess", headers=self.auth())[2])
        self.assertEqual([(s["name"], s["how"], s["by"]) for s in d["skills"]["own"]], [("digest-format", "panel", "Alex")])
        self.assertIn("research-playbook", [s["name"] for s in d["skills"]["kit"]])
        code, _, body = self.req("/api/skill?emp=tess&where=own&name=digest-format", headers=self.auth())
        self.assertEqual(code, 200)
        self.assertIn("Three bullets", json.loads(body)["text"])
        code, _, body = self.req("/api/skill?emp=tess&where=kit&name=monitoring", headers=self.auth())
        self.assertEqual((code, json.loads(body)["readonly"]), (200, True))
        code, _, body = self.req("/api/skill", {"emp": "tess", "do": "share", "name": "digest-format"}, h)
        self.assertEqual(code, 200, body)
        self.assertEqual([s["name"] for s in json.loads(self.req("/api/state", headers=self.auth())[2])["team_skills"]], ["digest-format"])
        code, _, body = self.req("/api/skill", {"emp": "tess", "do": "create", "name": "monitoring", "description": "shadowing a kit playbook", "text": "1. nope"}, h)
        self.assertEqual(code, 400)
        self.assertIn("kit", json.loads(body)["error"])
        code, _, _ = self.req("/api/skill", {"emp": "tess", "where": "team", "do": "remove", "name": "digest-format"}, h)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(self.req("/api/state", headers=self.auth())[2])["team_skills"], [])
        self.assertEqual(self.req("/api/skill?emp=nobody&where=own&name=x", headers=self.auth())[0], 404)


class Channels(unittest.TestCase):
    def setUp(self):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex")

    def test_addresses_and_owner_keys(self):
        import channels
        self.assertEqual(channels.parse("111"), ("telegram", "111"))
        self.assertEqual(channels.parse("-100123"), ("telegram", "-100123"))
        self.assertEqual(channels.parse("slack:U1"), ("slack", "U1"))
        self.assertEqual(channels.parse("local-alex"), ("", "local-alex"))
        self.assertEqual(channels.norm("111"), "telegram:111")
        self.assertEqual([channels.guess(x) for x in ("-100", "C0ABC123", "123456789012345678", "x")], ["telegram", "slack", "discord", ""])
        reg = engine.registry()
        reg["owners"]["111"]["addresses"] = ["slack:U1"]
        engine.save_registry(reg)
        self.assertEqual((engine.owner_key("telegram:111"), engine.owner_key("111"), engine.owner_key("slack:U1")), ("111", "111", "111"))
        self.assertIsNone(engine.owner_key("slack:U2"))
        self.assertEqual(engine.owner_id("alex"), "111")
        self.assertTrue(team.may_send_to("111"))
        self.assertFalse(team.may_send_to("slack:U2"))               # never a stranger
        self.assertFalse(team.may_send_to("telegram:-100999"))      # never an unregistered chat

    def test_handle_routes_owners_and_ignores_strangers(self):
        import channels
        import staffd
        sent, runs = [], []

        class Fake:
            NAME, LIMIT = "slack", 3900
            def token(self): return "xoxb-test"
            def send(self, cid, text): sent.append((cid, text)); return True
            def send_file(self, cid, path, caption=""): return True
            def typing(self, cid): pass
            def dm_chat(self, uid): return "D" + uid
            def download(self, att, d, n): return None
            def mention(self, h): return "@" + h
        fake = Fake()
        real_get, real_run = channels.get, staffd.run_async
        channels.get = lambda n: fake if n == "slack" else real_get(n)
        staffd.run_async = lambda *a, **k: runs.append((a, k))
        try:
            reg = engine.registry()
            reg["owners"] = {"slack:U1": {"name": "Alex", "aliases": []}}
            engine.save_registry(reg)
            dm = {"channel": "slack", "sender": "slack:U1", "sender_name": "Alex", "username": "alex", "chat": "slack:D1",
                  "is_group": False, "chat_title": None, "text": "help", "reply_to_text": "", "attachments": []}
            staffd.handle(dm)
            self.assertEqual(sent[-1][0], "D1")
            self.assertIn("@tess", sent[-1][1])
            staffd.handle({**dm, "text": "@tess what's new?"})
            a, k = runs[-1]
            self.assertEqual((a[0], k["session_key"], k["deliver_to"], k["channel"], k["said"]), ("tess", "slack:U1", ["slack:D1"], "slack", "what's new?"))
            self.assertEqual(team.to_people(engine.employee("tess"), "supervisor"), ["slack:D1"])   # replies go where they wrote
            staffd.handle({**dm, "sender": "slack:U9", "sender_name": "Stranger"})
            self.assertEqual(len(runs), 1)
            self.assertEqual(team.jload(staffd.PENDING, {})["slack:U9"]["channel"], "slack")
            self.assertEqual(len(sent), 1)                             # strangers never get an answer
            grp = {**dm, "chat": "slack:C1", "is_group": True, "text": "tess: summarize this"}
            staffd.handle(grp)
            self.assertEqual(len(runs), 1)                             # an unregistered chat is ignored
            reg = engine.registry()
            reg["team_chats"] = {"slack": "C1"}
            engine.save_registry(reg)
            staffd.handle(grp)
            a, k = runs[-1]
            self.assertEqual((a[0], k["session_key"], k["deliver_to"], k["channel"]), ("tess", "group", ["slack:C1"], "group"))
            staffd.handle({**grp, "text": "just us owners talking"})
            self.assertEqual(len(runs), 2)                             # no employee named: stay out
            team.send("slack:C1", "hello room")
            self.assertEqual(sent[-1], ("C1", "hello room"))
            team.send("slack:U9", "leak?")
            self.assertEqual(sent[-1], ("C1", "hello room"))
        finally:
            channels.get, staffd.run_async = real_get, real_run


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, sys, time
sys.stdin.read()
if "--sleep" in open(__file__).read() and False:
    pass
def out(d):
    print(json.dumps(d), flush=True)
out({"type": "system", "subtype": "init"})
out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "coffee prices"}}]}})
out({"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}})
out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "staff-fetch https://www.example.com/x"}}]}})
out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Glob", "input": {"pattern": "*"}}]}})
out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "WS/research/prices.md"}}]}})
SLEEP
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Done.", "num_turns": 4, "total_cost_usd": 0.0123})
'''


class LiveSteps(unittest.TestCase):
    def setUp(self):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex")
        self.emp = engine.employee("tess")
        self.real = engine.resolve_claude

    def tearDown(self):
        engine.resolve_claude = self.real

    def fake(self, sleep=0):
        p = os.path.join(TMP, "fake-claude")
        with open(p, "w") as fh:
            fh.write(FAKE_CLAUDE.replace("WS", self.emp["workspace"]).replace("SLEEP", "time.sleep(%d)" % sleep))
        os.chmod(p, 0o755)
        engine.resolve_claude = lambda: p

    def test_describe(self):
        import steps
        ws = "/w"
        self.assertEqual(steps.describe("WebSearch", {"query": "harbor   roast"}, ws), 'Searching the web: "harbor roast"')
        self.assertEqual(steps.describe("Bash", {"command": "staff-apify run tiktok '{\"profiles\": [\"x\"]}' --max-items 10"}, ws), "Running the TikTok scraper")
        self.assertEqual(steps.describe("Bash", {"command": "staff-browse https://www.tiktok.com/@x --scroll 5"}, ws), "Opening tiktok.com in the browser and scrolling through it")
        self.assertEqual(steps.describe("Bash", {"command": "staff-bus ask omar \"which page?\""}, ws), "Asking Omar")
        self.assertEqual(steps.describe("Read", {"file_path": "/w/STATE.md"}, ws), "Checking my notes")
        self.assertEqual(steps.describe("Edit", {"file_path": "/w/LESSONS.md"}, ws), "Updating my notes (LESSONS.md)")
        self.assertEqual(steps.describe("Write", {"file_path": "/w/research/a.md"}, ws), "Writing research/a.md")
        self.assertEqual(steps.describe("Read", {"file_path": "/w/state/inbox/x.pdf"}, ws), "Reading the file you sent")
        self.assertIsNone(steps.describe("Read", {"file_path": "/w/state/runs.jsonl"}, ws))
        self.assertIsNone(steps.describe("Bash", {"command": "ls -la"}, ws))
        self.assertIsNone(steps.describe("Bash", {"command": "git status"}, ws))
        self.assertEqual(steps.describe("Bash", {"command": "python3 /w/tools/price_check.py"}, ws), "Running my tool tools/price_check.py")
        self.assertIsNone(steps.describe("SomethingNew", {}, ws))

    def test_run_streams_steps_and_keeps_a_receipt(self):
        self.fake()
        seen = []
        res = engine.run(self.emp, "hi", job="chat", on_step=lambda s, all_: seen.append(s["text"]))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["text"], "Done.")
        want = ['Searching the web: "coffee prices"', "Reading example.com", "Looking through my files", "Writing research/prices.md"]
        self.assertEqual(seen, want)
        self.assertEqual([s["text"] for s in res["steps"]], want)
        with open(os.path.join(self.emp["workspace"], "state", "runs.jsonl")) as fh:
            rec = json.loads(fh.read().splitlines()[-1])
        self.assertEqual((rec["ok"], rec["cost_usd"], len(rec["steps"])), (True, 0.0123, 4))

    def test_timeout(self):
        self.fake(sleep=5)
        res = engine.run(self.emp, "hi", job="brief", timeout=1)
        self.assertFalse(res["ok"])
        self.assertIn("timed out", res["error"])


class Onboarding(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(os.path.join(TMP, "team"))
        engine.save_registry({"team_name": "My team", "owners": {}, "employees": {}, "panel": {"port": 7398}})
        import panel
        self.panel = panel

    def test_welcome_hire_connect_pair(self):
        import channels
        import staffd
        p = self.panel
        self.assertTrue(p.setup_state([])["welcome"])
        with self.assertRaises(orders.OrderError):
            p.welcome({"name": " "}, "Owner")
        p.welcome({"name": "Sam", "team_name": "Acme Coffee", "about": "We roast coffee."}, "Owner")
        reg = engine.registry()
        self.assertEqual(reg["owners"], {"local-sam": {"name": "Sam", "aliases": [], "local": True}})
        with open(os.path.join(TMP, "team", "ABOUT.md")) as fh:
            self.assertIn("We roast coffee.", fh.read())
        del RUNS[:]
        orders.execute("Sam", "hire", {"name": "Sara", "role": "Market researcher", "scope": "prices", "abilities": ["web", "fetch"]})
        (a, k), = RUNS
        self.assertEqual((a[0], a[2]), ("sara", "first_day"))                 # she starts with real work
        self.assertIn("First day", a[1])
        self.assertIn("Try next", a[1])
        with self.assertRaises(orders.OrderError):
            p.welcome({"name": "Sam"}, "Sam")                                    # once only
        self.assertFalse(p.setup_state([{"id": "sara"}])["welcome"])

        sent = []

        class Fake:
            NAME, LIMIT = "telegram", 3900
            ok = True
            def token(self): return engine.secret("telegram_bot_token")
            def check(self): return (True, "@acme_team_bot") if self.ok else (False, "Unauthorized")
            def send(self, cid, text): sent.append((cid, text)); return True
            def send_file(self, *a, **k): return True
            def typing(self, cid): pass
            def dm_chat(self, uid): return uid
            def download(self, *a): return None
            def mention(self, h): return "/" + h
        fake = Fake()
        real_get = channels.get
        channels.get = lambda n: fake if n == "telegram" else real_get(n)
        try:
            with self.assertRaises(orders.OrderError):
                p.connect({"kind": "telegram", "token": "not a token"}, "Sam")
            fake.ok = False
            with self.assertRaises(orders.OrderError):
                p.connect({"kind": "telegram", "token": "123456789:" + "A" * 35}, "Sam")
            self.assertIsNone(engine.secret("telegram_bot_token"))            # a refused token isn't kept
            fake.ok = True
            r = p.connect({"kind": "telegram", "token": "123456789:" + "B" * 35}, "Sam")
            code = r["code"]
            self.assertRegex(code, r"^\d{6}$")
            self.assertEqual(r["link"], "https://t.me/acme_team_bot?start=" + code)
            self.assertEqual(oct(os.stat(os.path.join(engine.SECRETS, "telegram_bot_token")).st_mode & 0o777), "0o600")
            msg = {"channel": "telegram", "sender": "telegram:555", "sender_name": "Mallory", "username": "m", "chat": "telegram:555",
                   "is_group": False, "chat_title": None, "text": "/start 000000", "reply_to_text": "", "attachments": []}
            self.assertFalse(staffd.try_pair(msg))                             # wrong code
            self.assertIsNone(engine.owner_key("telegram:555"))
            staffd.handle({**msg, "sender": "telegram:777", "chat": "telegram:777", "text": "/start " + code})
            reg = engine.registry()
            self.assertEqual(list(reg["owners"]), ["telegram:777"])            # the local owner is now reachable
            self.assertEqual(reg["owners"]["telegram:777"]["name"], "Sam")
            self.assertNotIn("local", reg["owners"]["telegram:777"])
            self.assertEqual(sent[-1][0], "777")
            self.assertIn("Connected. Hi Sam", sent[-1][1])
            self.assertTrue(p.pairing_view()["paired"])
            self.assertIsNone(p.pairing_view()["code"])
            self.assertEqual(team.to_people(engine.employee("sara"), "supervisor"), ["telegram:777"])
            v = p.new_pairing("telegram", "telegram:777")                       # a second device for the same owner
            for _ in range(5):
                staffd.try_pair({**msg, "text": "111111"})
            self.assertIsNone(p.pairing_view()["code"])                         # five wrong tries: void
            self.assertFalse(staffd.try_pair({**msg, "text": v["code"]}))
        finally:
            channels.get = real_get

    def test_apify_token(self):
        p = self.panel
        with self.assertRaises(orders.OrderError):
            p.connect({"kind": "apify", "token": "nope"}, "Sam")
        r = p.connect({"kind": "apify", "token": "apify_api_" + "x" * 30}, "Sam")
        self.assertTrue(r["ok"])
        self.assertEqual(engine.secret("apify_token"), "apify_api_" + "x" * 30)


class Skills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_team()
        hire.hire("Tess", "Research", supervisor="Alex")

    def test_learn_check_share_and_precedence(self):
        import skillbook
        with self.assertRaises(skillbook.SkillError):
            skillbook.create("tess", "Bad Name", "a description long enough")
        with self.assertRaises(skillbook.SkillError):
            skillbook.create("tess", "monitoring", "shadowing a kit playbook is refused")
        d = skillbook.create("tess", "price-check", "How to check a competitor's price page. Use when asked for prices.")
        self.assertTrue(os.path.isfile(os.path.join(d, "SKILL.md")))
        ws = engine.employee("tess")["workspace"]
        links, skipped = skillbook.bundle(ws, ["monitoring"])
        self.assertIn("monitoring", links)
        self.assertNotIn("price-check", links)                       # a skeleton doesn't load
        self.assertIn("price-check", [n for n, _ in skipped])
        with open(os.path.join(d, "SKILL.md")) as fh:
            text = fh.read().replace("1. …\n", "1. Open the page with staff-fetch.\n")
        skillbook.save("tess", "own", "price-check", text, "Alex")
        links, skipped = skillbook.bundle(ws, ["monitoring"])
        self.assertIn("price-check", links)
        with self.assertRaises(skillbook.SkillError):             # never a secret
            skillbook.save("tess", "own", "price-check", text + "\nuse sk-ant-abcdefghijklmnopqrstuv\n", "Alex")
        skillbook.share("tess", "price-check", "Alex")
        hire.hire("Omar", "Watcher", supervisor="Alex")
        emp = engine.employee("omar")
        root = engine.skills_plugin(emp, abilities.skills("omar"))
        self.assertTrue(os.path.islink(os.path.join(root, "skills", "price-check")))
        self.assertTrue(os.path.islink(os.path.join(root, "skills", "research-playbook")))
        skillbook.create("omar", "price-check", "Omar's own way to check prices, used when asked.", "Steps:\n1. Open the price page.\n2. Note every price with its date and link.\n")
        links, skipped = skillbook.bundle(emp["workspace"], [])
        self.assertEqual(os.path.realpath(links["price-check"]), os.path.realpath(os.path.join(emp["workspace"], "skills", "price-check")))
        self.assertEqual(skipped, [("price-check", "a own skill with that name already loads")])
        root = engine.skills_plugin(emp, [])
        self.assertEqual(os.path.realpath(os.path.join(root, "skills", "price-check")), os.path.realpath(links["price-check"]))
        self.assertFalse(os.path.lexists(os.path.join(root, "skills", "research-playbook")))
        skillbook.remove("tess", "team", "price-check", "Alex")
        self.assertFalse(os.path.isdir(os.path.join(skillbook.TEAM_DIR, "price-check")))
        self.assertEqual([r["what"] for r in team.tail(skillbook.LOG, 50)], ["learned", "updated", "shared", "learned", "unshared"])

    def test_tool_respects_the_ability(self):
        import subprocess
        tool = os.path.join(KIT, "bin", "staff-skill")
        env = {**os.environ, "STAFF_EMPLOYEE": "tess", "STAFF_WORKSPACE": engine.employee("tess")["workspace"], "STAFFROOM_HOME": TMP}
        r = subprocess.run([tool, "new", "feed-finder", "--description", "Finding a site's hidden JSON feed; use when a page is slow to scrape."],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Created skills/feed-finder/SKILL.md", r.stdout)
        r = subprocess.run([tool, "check", "feed-finder"], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("step 1 is empty", r.stderr)
        r = subprocess.run([tool, "list"], env=env, capture_output=True, text=True)
        self.assertIn("feed-finder", r.stdout)
        self.assertIn("not loading", r.stdout)
        hire.set_abilities("tess", [a for a in abilities.chosen("tess") if a != "learn"], "test")
        r = subprocess.run([tool, "new", "another-one", "--description", "Something else entirely, used whenever."], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("switched off", r.stderr)
        hire.set_abilities("tess", abilities.preset("default"), "test")
        self.assertIn("Bash(staff-skill *)", abilities.tools("tess")[1] if "learn" not in abilities.effective("tess") else ["Bash(staff-skill *)"])
        self.assertNotIn("staff-skill", abilities.commands("tess"))      # gated, but never outside the sandbox


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


import urllib.parse  # noqa: E402

if __name__ == "__main__":
    unittest.main()
