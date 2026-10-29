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
        self.assertEqual(sup, {k for k, a in cat.items() if not a.get("locked")})
        self.assertTrue(all(cat[k].get("default") for k in default))

    def test_validate_drops_locked_and_unknown(self):
        self.assertEqual(abilities.validate(["memory", "web", "bogus", "apify"]), ["apify", "web"])

    def test_tools_and_gateways_follow_ticks(self):
        hire.hire("Tess", "Research", supervisor="Alex", picked=["web", "fetch"])
        allow, block = abilities.tools("tess")
        self.assertIn("WebSearch", allow)
        self.assertIn("Bash(staff-apify *)", block)
        self.assertIn("Bash(staff-browse *)", block)
        self.assertEqual(abilities.commands("tess"), ["staff-fetch"])
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
        self.assertEqual(abilities.effective("tess"), set(abilities.by_id()))
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
        self.assertEqual(abilities.effective("omar"), set(abilities.by_id()))


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
        self.assertEqual(sorted(sb["excludedCommands"]), ["staff-browse *", "staff-fetch *"])
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
        return {"Cookie": "sr=" + self.tok, **(extra or {})}

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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


import urllib.parse  # noqa: E402

if __name__ == "__main__":
    unittest.main()
