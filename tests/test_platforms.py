"""Windows (WSL) and Linux: what differs from a Mac, tested on any computer by pretending.
Never records real audio or calls Claude.  python3 -m unittest tests.test_platforms
"""
from __future__ import annotations

import io
import re
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

TMP = tempfile.mkdtemp(prefix="orbit-platforms-test-")
os.environ["STAFFROOM_HOME"] = TMP
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "core"))
sys.path.insert(0, os.path.join(KIT, "core", "tools"))

import calls  # noqa: E402
import engine  # noqa: E402
import osinfo  # noqa: E402

LISTEN = os.path.join(KIT, "core", "tools", "call_listen.py")

# A stand-in for the soundcard package: a speaker that plays a tone, a microphone, and (with FAKE_SILENT=1)
# a loopback that sends nothing, as a silent Windows loopback does.
FAKE_SOUNDCARD = '''
import os, time
import numpy as np
SILENT = os.environ.get("FAKE_SILENT") == "1"
class _Rec:
    def __init__(self, silent): self.silent = silent
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def record(self, numframes):
        time.sleep(numframes / 48000.0)
        if self.silent:
            return np.zeros((0, 2), dtype=np.float32)
        return np.full((numframes, 2), 0.25, dtype=np.float32)
class _Mic:
    def __init__(self, silent=False): self.silent = silent
    def recorder(self, samplerate, blocksize=None): return _Rec(self.silent)
class _Speaker:
    name = "Speakers"
def default_speaker(): return _Speaker()
def get_microphone(id, include_loopback=False): return _Mic(SILENT)
def default_microphone(): return _Mic()
'''


def fake_soundcard_dir():
    d = tempfile.mkdtemp(dir=TMP)
    with open(os.path.join(d, "soundcard.py"), "w") as fh:
        fh.write(FAKE_SOUNDCARD)
    return d


def wait_for(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


class Words(unittest.TestCase):
    def test_mac_words_stay_on_a_mac(self):
        old = osinfo.KIND
        try:
            osinfo.KIND = "mac"
            self.assertEqual(osinfo.local("transcribed on this Mac"), "transcribed on this Mac")
        finally:
            osinfo.KIND = old

    def test_windows_says_pc_and_leaves_product_names_alone(self):
        r = subprocess.run([sys.executable, "-c", "import osinfo; print(osinfo.DEVICE); print(osinfo.local("
                            "'on this Mac, your Mac, the Mac; a MacBook and Macintosh stay'))"],
                           env=dict(os.environ, ORBIT_OS="wsl", PYTHONPATH=os.path.join(KIT, "core")),
                           capture_output=True, text=True)
        dev, text = r.stdout.strip().splitlines()
        self.assertEqual(dev, "PC")
        self.assertEqual(text, "on this PC, your PC, the PC; a MacBook and Macintosh stay")

    def test_panel_has_no_fixed_mac_words(self):
        with open(os.path.join(KIT, "core", "panel", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        for phrase in ("this Mac", "on the Mac"):
            self.assertNotIn(phrase, js.replace("'Match the Mac'", ""))


class Listener(unittest.TestCase):
    """core/tools/call_listen.py, the listener Windows and Linux use, with a fake sound card."""

    def run_listener(self, silent=False, secs=1.6):
        d = tempfile.mkdtemp(dir=TMP)
        env = dict(os.environ, PYTHONPATH=fake_soundcard_dir(), FAKE_SILENT="1" if silent else "0")
        p = subprocess.Popen([sys.executable, LISTEN, d, "--max-min", "5"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertTrue(wait_for(lambda: os.path.exists(os.path.join(d, "listener.pid"))), p.stderr.read() if p.poll() else "")
        self.assertTrue(wait_for(lambda: os.path.exists(os.path.join(d, "alive"))))
        time.sleep(secs)
        open(os.path.join(d, "stop"), "w").close()
        p.wait(10)
        return d, p

    def test_two_streams_at_16k_until_stop(self):
        d, p = self.run_listener()
        self.assertEqual(p.returncode, 0)
        for f in ("them.pcm", "you.pcm"):
            n = os.path.getsize(os.path.join(d, f)) // 4
            self.assertGreater(n, 16000 * 1.2, f)           # ~1.6 s+ at 16 kHz (48 kHz averaged 3:1)
            self.assertLess(n, 16000 * 4, f)
        self.assertFalse(os.path.exists(os.path.join(d, "listener.pid")))
        self.assertFalse(os.path.exists(os.path.join(d, "alive")))

    def test_silent_loopback_is_padded_so_times_line_up(self):
        d, p = self.run_listener(silent=True, secs=2.0)
        them = os.path.getsize(os.path.join(d, "them.pcm")) // 4
        you = os.path.getsize(os.path.join(d, "you.pcm")) // 4
        self.assertGreater(them, 16000 * 1.0)             # silence written, not nothing
        self.assertLess(abs(them - you), 16000)           # within a second of the microphone

    def test_missing_package_says_how_to_install(self):
        d = tempfile.mkdtemp(dir=TMP)
        empty = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(empty, "soundcard.py"), "w") as fh:
            fh.write("raise ImportError('No module named soundcard')\n")
        r = subprocess.run([sys.executable, LISTEN, d], env=dict(os.environ, PYTHONPATH=empty), capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        with open(os.path.join(d, "error.txt")) as fh:
            self.assertTrue(fh.read().startswith("NEEDS_SETUP"))


class LinuxCall(unittest.TestCase):
    """calls.py on Linux: starts the Python listener, transcribes, stops, hands over minutes."""

    def setUp(self):
        import hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        self.eid = hire.hire("Lina", "Call notes", "Minutes", supervisor="Alex", picked=["meetings"])
        self.saved = (osinfo.KIND, calls.ready, calls._whisper, calls.CHUNK_S, os.environ.get("PYTHONPATH"))
        osinfo.KIND = "linux"
        calls.ready = lambda: (True, "")
        calls._whisper = lambda a, prompt="": [(0, "Thirty one dollars a kilo.")] if len(a) else []
        calls.CHUNK_S = 1
        os.environ["PYTHONPATH"] = fake_soundcard_dir()

    def tearDown(self):
        osinfo.KIND, calls.ready, calls._whisper, calls.CHUNK_S, pp = self.saved
        if pp is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = pp
        for eid in list(calls.CALLS):
            calls.stop(eid)

    def test_start_listen_stop(self):
        ended = []
        st = calls.start(self.eid, "Alex", "Supplier", on_end=lambda eid, info: ended.append(info))
        self.assertEqual(st["employee"], self.eid)
        live = calls.CALLS[self.eid]
        self.assertIsNotNone(live.get("proc"))
        self.assertTrue(calls._listening(live))
        time.sleep(1.5)
        calls.stop(self.eid)
        self.assertTrue(wait_for(lambda: self.eid not in calls.CALLS, 15))
        self.assertEqual(live["proc"].poll(), 0)           # the listener ended cleanly
        self.assertTrue(ended)
        with open(live["transcript_abs"], encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("heard on this computer", body)
        self.assertIn("Them: Thirty one dollars a kilo.", body)
        self.assertFalse(os.path.exists(live["audio"]))      # raw audio deleted

    def test_listener_that_dies_ends_the_call(self):
        st = calls.start(self.eid, "Alex", "Short")
        live = calls.CALLS[self.eid]
        live["proc"].kill()
        self.assertTrue(wait_for(lambda: self.eid not in calls.CALLS, 15), st)


class Service(unittest.TestCase):
    def setUp(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("orbit_cli", os.path.join(KIT, "orbit"))
        spec = importlib.util.spec_from_loader("orbit_cli", loader)
        self.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(self.cli)
        self.kind = osinfo.KIND

    def tearDown(self):
        osinfo.KIND = self.kind

    def test_linux_checks_name_the_sandbox_and_the_fix(self):
        osinfo.KIND = "linux"
        real = osinfo.which
        osinfo.which = lambda n: None if n in ("bwrap", "socat", "tesseract") else real(n)
        try:
            rows = self.cli.platform_checks()
        finally:
            osinfo.which = real
        sandbox = next(r for r in rows if "sandbox" in r[1])
        self.assertFalse(sandbox[0])
        self.assertTrue(sandbox[2])                           # must be fixed before setup goes on
        self.assertIn("setup-linux.sh", sandbox[1])
        ocr = next(r for r in rows if "tesseract" in r[1])
        self.assertFalse(ocr[2])                              # optional

    def test_windows_start_script(self):
        osinfo.KIND = "wsl"
        os.environ["WSL_DISTRO_NAME"] = "Ubuntu-24.04"
        try:
            ps = self.cli.wsl_script()
        finally:
            os.environ.pop("WSL_DISTRO_NAME", None)
        import pwd
        me = pwd.getpwuid(os.getuid()).pw_name
        self.assertIn('-d "Ubuntu-24.04" -u "%s" -e "/usr/bin/env" "STAFFROOM_HOME=%s"' % (me, engine.HOME), ps)
        self.assertIn("service-run", ps)
        self.assertIn("Invoke-CimMethod -ClassName Win32_Process -MethodName Create", ps)   # outside WSL's job
        self.assertIn("GetFolderPath('Startup')", ps)
        self.assertIn("'--headless wsl.exe '", ps)
        self.assertEqual(ps.count("$a = '"), 1)

    def test_stop_ends_the_background_service(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        os.makedirs(os.path.dirname(self.cli.SERVICE_PID), exist_ok=True)
        with open(self.cli.SERVICE_PID, "w") as fh:
            fh.write(str(p.pid))
        self.assertEqual(self.cli.service_pid(), p.pid)
        self.cli.stop_service_run()
        p.wait(10)
        self.assertIsNone(self.cli.service_pid())


class Documents(unittest.TestCase):
    def setUp(self):
        import docs
        self.docs = docs
        self.mac = docs.MAC
        docs.MAC = False
        self.bin = tempfile.mkdtemp(dir=TMP)
        with open(os.path.join(self.bin, "tesseract"), "w") as fh:   # a stand-in that knows ara and eng
            fh.write('#!/bin/sh\nif [ "$1" = "--list-langs" ]; then printf "List of available languages (3):\\n'
                     'ara\\neng\\nosd\\n"; exit 0; fi\necho "read $1 with $4"\n')
        os.chmod(os.path.join(self.bin, "tesseract"), 0o755)
        self.path = os.environ["PATH"]
        os.environ["PATH"] = self.bin + os.pathsep + self.path

    def tearDown(self):
        self.docs.MAC = self.mac
        os.environ["PATH"] = self.path

    def test_ocr_uses_tesseract_with_arabic_and_english(self):
        img = os.path.join(TMP, "scan.png")
        with open(img, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        got = self.docs.ocr(img)
        self.assertEqual(got, {1: "read %s with ara+eng" % img})
        self.assertEqual(self.docs.ocr(img, langs="en")[1], "read %s with eng" % img)
        with self.assertRaises(self.docs.DocError):
            self.docs.ocr(img, langs="ja")                    # not installed: says which apt package

    def test_word_files_without_textutil(self):
        p = os.path.join(TMP, "memo.docx")
        body = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                '<w:p><w:r><w:t>First line</w:t></w:r></w:p><w:p><w:r><w:t>سطر عربي</w:t></w:r></w:p></w:body></w:document>')
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", body)
        self.assertEqual(self.docs._office_text(p), "First line\nسطر عربي")
        h = os.path.join(TMP, "page.html")
        with open(h, "w", encoding="utf-8") as fh:
            fh.write("<html><style>x{}</style><p>Hello</p><p>World</p></html>")
        self.assertEqual(self.docs._office_text(h), "Hello\nWorld")


class Sandbox(unittest.TestCase):
    def test_windows_programs_and_services_are_denied(self):
        for rule in ("Bash(powershell.exe *)", "Bash(cmd.exe *)", "Bash(wsl.exe *)", "Bash(systemctl *)"):
            self.assertIn(rule, engine.BASE_DENIED)

    def test_windows_drives_are_out_of_reach_in_wsl(self):
        r = subprocess.run([sys.executable, "-c", "import engine; print('/mnt' in engine.SECRET_PATHS)"],
                           env=dict(os.environ, ORBIT_OS="wsl", PYTHONPATH=os.path.join(KIT, "core")),
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "True", r.stderr)


if __name__ == "__main__":
    unittest.main()


class Onboarding(unittest.TestCase):
    """The hiring interview's card reaches the crew member: CLAUDE.md, the registry, the first task, the budget."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})

    def card(self):
        return {"responsibilities": ["Read the monthly statement", "Flag odd lines"], "first_task": "Propose a category list.",
                "plan": ["Day 1: categories", "Day 2: first ledger"], "weekly_tokens": 1000000,
                "access": [{"kind": "finance_read_only", "what": "Read CIB statements", "why": "for the books", "site": "CIB"}],
                "interview": [{"q": "How often?", "a": "Monthly"}]}

    def test_card_is_written_where_the_crew_member_reads(self):
        eid = self.hire.hire("Nora", "Bookkeeper", "Keep my books", supervisor="Alex", picked=["documents"], card=self.card())
        reg = engine.registry()["employees"][eid]
        self.assertEqual(reg["weekly_tokens"], 1000000)
        self.assertEqual(reg["card"]["first_task"], "Propose a category list.")
        with open(os.path.join(TMP, "employees", eid, "CLAUDE.md"), encoding="utf-8") as fh:
            md = fh.read()
        for bit in ("Read the monthly statement", "Day 1: categories", "Read CIB statements (CIB)", "How often? → Monthly",
                    "Money: read only"):
            self.assertIn(bit, md)
        import team
        prompt = team.job_prompt(eid, engine.employee(eid), "first_day")
        self.assertIn("Propose a category list.", prompt)
        self.assertNotIn("What I can't do", prompt)

    def test_budget_pauses_routines_not_chats(self):
        import team
        eid = self.hire.hire("Bea", "Researcher", "Research", supervisor="Alex", picked=["web"])
        self.hire.set_field(eid, "weekly_tokens", "1000")
        emp = engine.employee(eid)
        os.makedirs(os.path.join(emp["workspace"], "state"), exist_ok=True)
        with open(os.path.join(emp["workspace"], "state", "runs.jsonl"), "w") as fh:
            fh.write('{"ts": "%s", "employee": "%s", "job": "chat", "ok": true, "tokens": 5000}\n' % (time.strftime("%Y-%m-%dT%H:%M:%S"), eid))
        self.assertEqual(engine.stats(emp)["tokens_7d"], 5000)
        self.assertTrue(team.over_budget(emp))
        self.hire.set_field(eid, "weekly_tokens", "0")
        self.assertFalse(team.over_budget(engine.employee(eid)))

    def test_old_runs_without_tokens_are_estimated(self):
        self.assertEqual(engine.tokens_of({"cost_usd": 0.5}), 100000)
        self.assertEqual(engine.tokens_of({"tokens": 42, "cost_usd": 9}), 42)

    def test_demo_interview_is_scripted(self):
        import panel
        old = panel.DEMO
        panel.DEMO = True
        try:
            q = panel.interview("questions", {"name": "Sara", "role": "Researcher"})
            self.assertGreaterEqual(len(q["questions"]), 3)
            c = panel.interview("card", {"name": "Sara", "role": "Researcher", "answers": []})
            self.assertIn("responsibilities", c)
        finally:
            panel.DEMO = old


class ClaudeSession(unittest.TestCase):
    """The folder a Claude app session opens in carries the same locks as the crew member's runs."""

    def test_local_settings_mirror_the_run(self):
        import hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        eid = hire.hire("Cleo", "Researcher", "Research", supervisor="Alex", picked=["web"])
        ws = engine.employee(eid)["workspace"]
        os.makedirs(os.path.join(ws, ".claude"), exist_ok=True)
        with open(os.path.join(ws, ".claude", "settings.local.json"), "w") as fh:   # the guard already installed
            json.dump({"enabledPlugins": {"staff-guard@orbit": True}}, fh)
        with open(os.path.join(engine.GUARD, ".claude-plugin", "plugin.json")) as fh, \
                open(os.path.join(ws, ".claude", "orbit-guard.version"), "w") as out:   # ...at the kit's version
            out.write(json.load(fh)["version"])
        s = engine.claude_session(eid)
        with open(os.path.join(ws, ".claude", "settings.local.json")) as fh:
            d = json.load(fh)
        self.assertTrue(d["sandbox"]["enabled"])
        self.assertTrue(d["sandbox"]["failIfUnavailable"])
        self.assertIn("Bash(git push *)", d["permissions"]["deny"])
        self.assertFalse(any(r.startswith("Write(") for r in d["permissions"]["deny"]))
        self.assertEqual(d["env"]["STAFF_EMPLOYEE"], eid)
        self.assertTrue(d["enabledPlugins"]["staff-guard@orbit"])                 # kept
        self.assertTrue(s["link"].startswith("claude://code/new?folder="))
        self.assertIn("Cleo", s["hello"])


class BrowserGrant(unittest.TestCase):
    """'Acts in your browser': only the panel switch grants it; the registry, CLAUDE.md and sessions follow."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        self.eid = hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex", picked=["web", "act_in_browser"])

    def test_hiring_or_presets_never_grant_it(self):
        import abilities
        self.assertNotIn("act_in_browser", abilities.effective(self.eid))
        self.assertNotIn("act_in_browser", abilities.preset("super"))
        self.hire.set_abilities(self.eid, ["web", "act_in_browser"])
        self.assertNotIn("act_in_browser", abilities.effective(self.eid))

    def test_switch_on_and_off(self):
        import abilities
        b = self.hire.set_browser(self.eid, ["https://www.YouTube.com/upload", "etsy.com"], "batch", "Alex")
        self.assertEqual(b["sites"], ["youtube.com", "etsy.com"])
        self.assertIn("act_in_browser", abilities.effective(self.eid))
        self.hire.set_abilities(self.eid, ["web"])                       # the ticks grid keeps the consent as it is
        self.assertIn("act_in_browser", abilities.effective(self.eid))
        env = engine.clean_env(engine.employee(self.eid))
        self.assertEqual(env["STAFF_BROWSER_SITES"], "youtube.com,etsy.com")
        self.assertIn("--chrome", engine.command(engine.employee(self.eid), "sonnet"))
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("Granted by your owner"), 1)
        self.hire.set_browser(self.eid, ["youtube.com"], "each", "Alex")   # again: replaced, not repeated
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertEqual(md.count("Granted by your owner"), 1)
        self.assertIn("Approve each item separately", md)
        self.hire.set_browser(self.eid, [], "each", "Alex")
        self.assertNotIn("act_in_browser", abilities.effective(self.eid))
        self.assertNotIn("--chrome", engine.command(engine.employee(self.eid), "sonnet"))
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertNotIn("Granted by your owner", fh.read())

    def test_money_sites_cannot_be_granted(self):
        with self.assertRaises(self.hire.HireError):
            self.hire.set_browser(self.eid, ["paypal.com"], "each", "Alex")


class FullAutonomy(unittest.TestCase):
    """The owner's switch: no permission stops and an open network for the run; the sandbox stays."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        self.eid = hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex", picked=["web", "full_autonomy"])

    def run_settings(self):
        emp = engine.employee(self.eid)
        cmd = engine.command(emp, "sonnet")
        return cmd, json.loads(cmd[cmd.index("--settings") + 1])

    def test_off_by_default_and_never_by_ticks(self):
        cmd, st = self.run_settings()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertTrue(st["sandbox"]["network"]["strictAllowlist"])

    def test_on_then_off(self):
        self.hire.set_autonomy(self.eid, True, "Alex")
        cmd, st = self.run_settings()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "bypassPermissions")
        self.assertFalse(st["sandbox"]["network"]["strictAllowlist"])
        self.assertTrue(st["sandbox"]["enabled"])                       # the boundary stays
        self.assertIn(engine.SECRETS, st["sandbox"]["filesystem"]["denyRead"])
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("Granted by your owner: full autonomy"), 1)
        self.hire.set_autonomy(self.eid, False, "Alex")
        cmd, st = self.run_settings()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertNotIn("full autonomy", fh.read())

    def test_dont_ask_browser_grant(self):
        self.hire.set_browser(self.eid, ["youtube.com"], "none", "Alex")
        with open(os.path.join(TMP, "employees", self.eid, "CLAUDE.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("Don't ask me", md)
        self.assertNotIn("wait for their", md)


class Switches(unittest.TestCase):
    """The owner's switches from chat, from a Yes in Claude (orbit grant), and crew connections."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex", picked=["web"])
        hire.hire("Nora", "Bookkeeper", "Books", supervisor="Alex", picked=["documents"])

    def ab(self, eid):
        import abilities
        return abilities.effective(eid)

    def test_chat_commands(self):
        import grants
        self.assertIn("full autonomy", grants.from_text("Alex", "Suoo full autonomy on"))
        self.assertIn("full_autonomy", self.ab("suoo"))
        self.assertIn("off", grants.from_text("Alex", "turn off full autonomy for suoo"))
        self.assertNotIn("full_autonomy", self.ab("suoo"))
        self.assertIn("without asking", grants.from_text("Alex", "Suoo can post on YouTube and TikTok without asking"))
        b = engine.registry()["employees"]["suoo"]["browser"]
        self.assertEqual((b["sites"], b["approval"]), (["youtube.com", "tiktok.com"], "none"))
        self.assertIn("no longer", grants.from_text("Alex", "suoo stop posting"))
        self.assertIn("work together", grants.from_text("Alex", "connect Suoo with Nora: send Nora every sponsor deal"))
        with open(os.path.join(TMP, "employees", "nora", "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertIn("staff-bus ask suoo", fh.read())
        for ordinary in ("what's the autonomy of a drone?", "post the video on youtube tomorrow", "Suoo, how are you?"):
            self.assertIsNone(grants.from_text("Alex", ordinary), ordinary)

    def test_orbit_grant_needs_the_key(self):
        import grants
        kit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orbit")
        env = dict(os.environ, STAFFROOM_HOME=TMP)
        r = subprocess.run([sys.executable, kit, "grant", "suoo", "autonomy", "on"], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)                            # an employee running it gets nothing
        self.assertNotIn("full_autonomy", self.ab("suoo"))
        env["ORBIT_GRANT_KEY"] = grants.key()
        r = subprocess.run([sys.executable, kit, "grant", "suoo", "autonomy", "on"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("full_autonomy", self.ab("suoo"))


class Updates(unittest.TestCase):
    def test_newer_release_is_offered_never_applied_on_its_own(self):
        import update
        update._save({"latest": "99.0.0", "notes": "- New things", "checked": time.time()})
        s = update.status()
        self.assertTrue(s["newer"])
        self.assertEqual(s["current"], update.current())
        update.dismiss()
        self.assertTrue(update.status()["dismissed"])
        self.assertTrue(update.announce_once("99.0.0"))
        self.assertFalse(update.announce_once("99.0.0"))
        update._save({"latest": "0.0.1", "checked": time.time()})
        self.assertFalse(update.status()["newer"])


class ContentKit(unittest.TestCase):
    """The content creator comes trained: the skill loads with the ability, and the kit is whole."""

    def test_skill_and_kit(self):
        import abilities
        kit = os.path.join(engine.KIT, "core", "skills", "content-creator")
        with open(os.path.join(kit, "SKILL.md"), encoding="utf-8") as fh:
            self.assertIn("abilities: content", fh.read())
        for f in ("setup.sh", "make.sh", "vo.py", "mix.py", "render.js", "short.html", "script.json", "short.json",
                  "fonts/Poppins-Bold.ttf", "fonts/Poppins-BoldItalic.ttf"):
            self.assertTrue(os.path.exists(os.path.join(kit, "kit", f)), f)
        for f in ("vo.py", "mix.py"):
            subprocess.run([sys.executable, "-m", "py_compile", os.path.join(kit, "kit", f)], check=True)
        for f in ("setup.sh", "make.sh"):
            subprocess.run(["sh", "-n", os.path.join(kit, "kit", f)], check=True)
        self.assertIn("content-creator", [s for a in abilities.catalog() if a["id"] == "content" for s in a["skills"]])
        with open(os.path.join(engine.KIT, "core", "roles.json"), encoding="utf-8") as fh:
            role = next(r for r in json.load(fh)["roles"] if r["id"] == "creator")
        self.assertIn("content", role["abilities"])


class ConnectorsAndRoles(unittest.TestCase):
    """The connector library, granting one, and roles saved from a trained crew member."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        hire.hire("Suoo", "Content creator", "Videos for YouTube and TikTok", supervisor="Alex", picked=["web", "content"])

    def test_library_is_whole_and_matches_every_role(self):
        import connectors
        lib = connectors.library()
        self.assertGreater(len(lib), 50)
        self.assertTrue(all(c["url"].startswith("https://") for c in lib))
        with open(os.path.join(engine.KIT, "core", "roles.json"), encoding="utf-8") as fh:
            roles = [r["id"] for r in json.load(fh)["roles"] if r["id"] != "blank"]
        for rid in roles:
            self.assertTrue(connectors.for_job(rid, ""), rid)            # every defined role has suggestions
        self.assertTrue(connectors.for_job(None, "manage our restaurant bookings calendar and email"))   # and undefined ones

    def test_grant_reaches_runs_and_revokes(self):
        import connectors
        connectors.grant("suoo", "notion", "Alex")
        cmd = engine.command(engine.employee("suoo"), "sonnet")
        cfg = cmd[cmd.index("--mcp-config") + 1]
        with open(cfg) as fh:
            self.assertEqual(json.load(fh)["mcpServers"]["notion"]["url"], "https://mcp.notion.com/mcp")
        self.assertIn("mcp__notion", cmd)
        connectors.grant("suoo", "https://mcp.example-app.com/mcp", "Alex", "Example")
        self.assertIn("example", engine.registry()["employees"]["suoo"]["connectors"])
        self.assertIn("no longer", connectors.revoke("suoo", "notion", "Alex"))
        self.assertNotIn("notion", engine.registry()["employees"]["suoo"]["connectors"])
        with self.assertRaises(ValueError):
            connectors.grant("suoo", "not-a-connector", "Alex")

    def test_chat_command_for_a_connector(self):
        import grants
        self.assertIn("Canva", grants.from_text("Alex", "connect Suoo to Canva"))
        self.assertIn("canva", engine.registry()["employees"]["suoo"]["connectors"])
        self.assertIn("no longer", grants.from_text("Alex", "disconnect Suoo from canva"))

    def test_save_a_role_and_hire_from_it(self):
        import rolebook
        ws = engine.employee("suoo")["workspace"]
        os.makedirs(os.path.join(ws, "skills", "hooks"), exist_ok=True)
        with open(os.path.join(ws, "skills", "hooks", "SKILL.md"), "w") as fh:
            fh.write("---\\nname: hooks\\ndescription: Write hooks.\\n---\\nOpen with a question.\\n")
        with open(os.path.join(ws, "CLAUDE.md"), encoding="utf-8") as fh:
            md = fh.read()
        with open(os.path.join(ws, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write(re.sub(r"_Your supervisor adds rules here[^\\n]*", "- Shorts are about 20 seconds.", md))
        self.assertIn("1 skill", rolebook.save_role("suoo", "Channel manager", "Alex"))
        roles = rolebook.all_roles()
        self.assertEqual(roles["situations"][0]["id"], "yours")
        mine = next(r for r in roles["roles"] if r["id"] == "channel-manager")
        self.assertEqual(mine["source"], "yours")
        self.assertNotIn("full_autonomy", mine["abilities"])
        new = self.hire.hire("Zain", "Content creator", mine["scope"], supervisor="Alex", picked=mine["abilities"])
        rolebook.apply_template(new, "channel-manager")
        zws = engine.employee(new)["workspace"]
        self.assertTrue(os.path.exists(os.path.join(zws, "skills", "hooks", "SKILL.md")))
        with open(os.path.join(zws, "CLAUDE.md"), encoding="utf-8") as fh:
            self.assertIn("Shorts are about 20 seconds.", fh.read())
        out = rolebook.export_role("channel-manager", tempfile.mkdtemp(dir=TMP))
        self.assertTrue(os.path.exists(os.path.join(out, "role.json")))


class Proactive(unittest.TestCase):
    """Every crew member works like an ambitious employee: a plan, a standup, an initiative, and they're heard."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"local-alex": {"name": "Alex", "local": True}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})

    def test_new_hires_have_a_plan_and_the_routines(self):
        import abilities
        eid = self.hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex")
        self.assertTrue(os.path.exists(os.path.join(TMP, "employees", eid, "PLAN.md")))
        self.assertTrue({"standup", "initiative"} <= abilities.effective(eid))
        self.assertIn("initiative", abilities.jobs(eid))

    def test_existing_crew_is_upgraded_once(self):
        import abilities
        eid = self.hire.hire("Old", "Researcher", "Research", supervisor="Alex", picked=["web", "brief"])
        os.remove(os.path.join(TMP, "employees", eid, "PLAN.md"))
        self.hire.upgrade_workspace(eid)
        self.assertTrue(os.path.exists(os.path.join(TMP, "employees", eid, "PLAN.md")))
        self.assertTrue({"standup", "initiative"} <= abilities.effective(eid))
        self.hire.set_abilities(eid, ["web", "brief"])          # the owner turns them off: an upgrade doesn't undo it
        self.hire.upgrade_workspace(eid)
        self.assertNotIn("initiative", abilities.effective(eid))

    def test_a_routine_pops_up_when_there_is_no_phone_channel(self):
        import osinfo
        import team
        shown = []
        real = osinfo.notify
        osinfo.notify = lambda title, text: shown.append((title, text)) or True
        try:
            team.to_room("suoo", "Suoo", "Alex", "job")("Plan for approval: 2 Shorts a day.")
            team.to_room("suoo", "Suoo", "Alex", "panel")("A chat reply.")
            team.to_room("suoo", "Suoo", "Alex", "job")("SILENT")
        finally:
            osinfo.notify = real
        self.assertEqual(shown, [("Suoo · Orbit", "Plan for approval: 2 Shorts a day.")])


class ApifyStore(unittest.TestCase):
    """Live prices, fresh-only crawls, and Apify Store actors for crew with Full autonomy (no network, no spend)."""

    def setUp(self):
        import apify
        self.apify = apify
        self.env = {k: os.environ.get(k) for k in ("STAFF_EMPLOYEE", "STAFF_ABILITIES")}
        self.http = apify._http

    def tearDown(self):
        self.apify._http = self.http
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        for k in [k for k in self.apify.CATALOG if k.startswith("store-")]:
            self.apify.CATALOG.pop(k)

    def fake_actor(self, users, ok, cats=("SOCIAL_MEDIA",)):
        total = 1000
        self.apify._http = lambda *a, **k: {"data": {"title": "Some tool", "categories": list(cats), "pricingInfos": [{"pricingModel": "PAY_PER_EVENT", "minimalMaxTotalChargeUsd": 0.5}],
                                                      "stats": {"totalUsers30Days": users, "publicActorRunStats30Days": {"TOTAL": total, "SUCCEEDED": int(total * ok)}}}}

    def test_prices_alias(self):
        inp, dropped, notes = self.apify.build_input("prices", {"keyword": "kettle", "marketplaces": ["www.amazon.eg"],
                                                                "maxProductResults": 50, "customPrompt": "x"}, 10)
        self.assertEqual(inp["maxProductResults"], 10)
        self.assertIn("customPrompt", dropped)
        self.assertEqual(self.apify.resolve("price"), "prices")
        self.assertEqual(self.apify.resolve("store:apify/e-commerce-scraping-tool"), "prices")   # vetted: for anyone

    def test_store_actors_need_full_autonomy_and_the_bar(self):
        os.environ["STAFF_EMPLOYEE"] = "suoo"
        os.environ["STAFF_ABILITIES"] = "web,apify"
        self.fake_actor(5000, 0.99)
        with self.assertRaises(PermissionError):
            self.apify.resolve("store:someone/good-tool")
        os.environ["STAFF_ABILITIES"] = "web,apify,full_autonomy"
        self.assertTrue(self.apify.resolve("store:someone/good-tool").startswith("store-"))
        self.fake_actor(40, 0.99)
        with self.assertRaises(PermissionError):
            self.apify.resolve("store:someone/tiny-tool")
        self.fake_actor(5000, 0.80)
        with self.assertRaises(PermissionError):
            self.apify.resolve("store:someone/flaky-tool")
        self.fake_actor(5000, 0.99, ("FINANCE",))
        with self.assertRaises(PermissionError):
            self.apify.resolve("store:someone/money-tool")


class Strategy(unittest.TestCase):
    """The plan is visible and agreed in one click; days are scored, tomorrow is prepared, the strategy reviewed
    weekly; a Mac that was offline or asleep doesn't cost a day's routines."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"local-alex": {"name": "Alex", "local": True}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7396}, "workdays": ["Mon", "Tue", "Wed", "Thu", "Fri"]})

    PLAN = """# PLAN — Suoo, Content creator

Status: **proposed** 2026-11-02

## The goal
Drift..Master earns money. In 90 days (by 2027-01-31):
- 1,000 subs and 4,000 long-form watch hours.

## Milestones
| By | What | Status |
|---|---|---|
| 2026-11-02 | Short #1 scheduled | done |
| 2026-11-16 | 28 Shorts out | open |

## Numbers (updated every standup)
| Date | Metric | Value | Target |
|---|---|---|---|
| 2026-11-01 | Subs | 250 | 500 by 2026-12-02 |

## Decisions I need
1. Cadence: 2 Shorts a day (recommended), or 3.
2. Cross-post to TikTok.
"""

    def test_the_plan_is_read_and_agreed_in_one_click(self):
        import orders
        import plan
        eid = self.hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex")
        self.assertEqual(plan.summary(eid)["status"], "none")            # the template's placeholders aren't a plan
        with open(os.path.join(TMP, "employees", eid, "PLAN.md"), "w", encoding="utf-8") as fh:
            fh.write(self.PLAN)
        s = plan.summary(eid)
        self.assertEqual(s["status"], "proposed")
        self.assertEqual(s["goal"], "Drift..Master earns money. In 90 days (by 2027-01-31): 1,000 subs and 4,000 long-form watch hours.")
        self.assertEqual(s["next"], {"by": "2026-11-16", "what": "28 Shorts out", "status": "open"})
        self.assertEqual(s["numbers"][0]["value"], "250")
        self.assertEqual(len(s["decisions"]), 2)
        import panel
        needs = panel.needs_you(panel.members(), [], {}, {})
        self.assertTrue(any(n["kind"] == "plan" and n["href"] == "/e/%s/plan" % eid for n in needs))
        orders.execute("Alex", "agree_plan", {"employee_id": eid})
        s = plan.summary(eid)
        self.assertEqual(s["status"], "agreed")
        self.assertIn("by Alex", s["agreed"])

    def test_review_runs_on_the_owners_last_workday(self):
        import team
        self.assertTrue(team.due_today("last_workday", 4))              # Mon–Fri: Friday
        self.assertFalse(team.due_today("last_workday", 3))
        reg = engine.registry()
        reg["workdays"] = ["Sun", "Mon", "Tue", "Wed", "Thu"]            # an Egyptian week: Thursday
        engine.save_registry(reg)
        self.assertTrue(team.due_today("last_workday", 3))
        self.assertFalse(team.due_today("last_workday", 4))

    def test_new_and_existing_crew_score_the_day_and_review_the_week(self):
        import abilities
        new = self.hire.hire("Nora", "Researcher", "Research", supervisor="Alex")
        self.assertTrue({"eod", "review"} <= set(abilities.jobs(new)))
        old = self.hire.hire("Old", "Researcher", "Research", supervisor="Alex", picked=["web", "standup"])
        reg = engine.registry()
        reg["employees"][old]["proactive_v1"] = True
        engine.save_registry(reg)
        with open(os.path.join(TMP, "employees", old, "PLAN.md"), "w", encoding="utf-8") as fh:
            fh.write(self.PLAN)
        self.hire.upgrade_workspace(old)
        self.assertTrue({"eod", "review"} <= set(abilities.jobs(old)))
        with open(os.path.join(TMP, "employees", old, "PLAN.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertLess(text.index("## Reviews"), text.index("## Decisions I need"))
        self.hire.set_abilities(old, ["web", "standup"])                 # the owner turns them off: it stays off
        self.hire.upgrade_workspace(old)
        self.assertNotIn("review", abilities.jobs(old))

    def test_offline_routines_wait_and_retry(self):
        import datetime as dt
        import staffd
        now = dt.datetime.now()
        if now.hour == 0 and now.minute < 2:
            self.skipTest("too close to midnight")
        eid = self.hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex", picked=["standup"])
        reg = engine.registry()
        reg["jobs"] = {"standup": {"at": (now - dt.timedelta(minutes=1)).strftime("%H:%M"), "days": "daily"}}
        engine.save_registry(reg)
        started = []
        real_run, real_online = staffd.run_async, engine.online
        staffd.run_async = lambda *a, **k: started.append(k)
        try:
            engine.online = lambda *a, **k: False
            staffd.tick_jobs()
            self.assertEqual(started, [])                                  # offline: stays due
            st_f = os.path.join(TMP, "employees", eid, "state", "schedule.json")
            st = {}
            if os.path.exists(st_f):
                with open(st_f) as fh:
                    st = json.load(fh)
            self.assertNotIn("standup", st)
            engine.online = lambda *a, **k: True
            staffd.tick_jobs()
            self.assertEqual(len(started), 1)                              # back online: it starts
            started[0]["retry"]()                                          # …and fails on the network: again in 10 min
            with open(st_f) as fh:
                st = json.load(fh)
            self.assertNotIn("standup", st)
            self.assertGreater(st["wait:standup"], now.strftime("%F %H:%M"))
            staffd.tick_jobs()
            self.assertEqual(len(started), 1)                              # not before then
        finally:
            staffd.run_async, engine.online = real_run, real_online

    def test_a_routine_that_works_is_posted(self):
        import threading
        import team
        eid = self.hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex")
        real = engine.run
        done, posted = threading.Event(), []
        try:
            engine.run = lambda *a, **k: {"ok": True, "text": "This week: 1.4K median views.", "error": "", "steps": []}
            team.run_async(eid, "p", "review", None, [], on_done=lambda out: posted.append(out) or done.set())
            self.assertTrue(done.wait(10))
            self.assertEqual(posted, ["This week: 1.4K median views."])
        finally:
            engine.run = real

    def test_a_failed_routine_never_says_please_resend(self):
        import threading
        import team
        eid = self.hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex")
        real = engine.run
        done, posted, retried = threading.Event(), [], []
        try:
            engine.run = lambda *a, **k: {"ok": False, "transient": True, "text": "x", "error": "ENOTFOUND", "steps": []}
            team.run_async(eid, "p", "standup", None, [], on_done=posted.append, retry=lambda: retried.append(1) or done.set())
            self.assertTrue(done.wait(10))
            self.assertEqual((retried, posted), ([1], []))
            done.clear()
            engine.run = lambda *a, **k: {"ok": False, "transient": False, "text": "Something went wrong. Please resend.",
                                          "error": "API Error 500", "steps": []}
            team.run_async(eid, "p", "eod", None, [], on_done=lambda out: posted.append(out) or done.set())
            for _ in range(100):
                if any("didn't run" in r.get("body", "") for r in team.tail(team.FEED, 20)):
                    break
                time.sleep(0.1)
            self.assertEqual(posted, [])
            lines = [r["body"] for r in team.tail(team.FEED, 20) if r.get("from_id") == eid]
            self.assertTrue(any(x.startswith("My end of day didn't run: an error on my side") for x in lines), lines)
            self.assertFalse(any("resend" in x for x in lines))
        finally:
            engine.run = real


class Sharing(unittest.TestCase):
    """A crew member someone trained is offered for sharing, with everything private taken out; it travels as
    one file or to the community; whoever hires from it starts with the experience."""

    DRAFT = {"title": "Shorts channel manager", "summary": "Runs a YouTube Shorts channel to monetisation.",
             "experience": "## Quality\n- Every Short ships with a voiceover; silent ones were rejected.",
             "rules": "- Ask before publishing.", "removed": ["the owner's name", "the channel's name"],
             "skills": [{"name": "daily-standup", "text": "---\nname: daily-standup\ndescription: The standup.\n---\nNumbers first."},
                        {"name": "invented", "text": "not a real skill"}]}

    def setUp(self):
        import hire
        import shutil
        self.hire = hire
        shutil.rmtree(os.path.join(TMP, "team", "roles"), ignore_errors=True)
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"local-alex": {"name": "Alex", "local": True}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7395}})
        self.eid = hire.hire("Suoo", "Content creator", "Drift..Master videos", supervisor="Alex")
        ws = os.path.join(TMP, "employees", self.eid)
        os.makedirs(os.path.join(ws, "skills", "daily-standup"), exist_ok=True)
        with open(os.path.join(ws, "skills", "daily-standup", "SKILL.md"), "w") as fh:
            fh.write("---\nname: daily-standup\ndescription: Alex's Drift..Master standup.\n---\nNumbers first.")
        with open(os.path.join(ws, "LESSONS.md"), "w") as fh:
            fh.write("# LESSONS\n" + "".join("- 2026-11-0%d · Alex: lesson %d\n" % (i % 9 + 1, i) for i in range(9)))

    def test_distill_save_send_import_hire(self):
        import onboard
        import orders
        import rolebook
        seen = []
        real = onboard._ask
        onboard._ask = lambda system, prompt, schema, timeout=150: seen.append(prompt) or dict(self.DRAFT, _tokens=9)
        try:
            d = rolebook.distill(self.eid)
        finally:
            onboard._ask = real
        self.assertIn("Alex's Drift..Master standup", seen[0])                # Claude sees the private text…
        self.assertEqual([s["name"] for s in d["skills"]], ["daily-standup"])   # …and can't add skills it didn't have
        self.assertEqual(d["stats"]["lessons"], 9)
        orders.execute("Alex", "save_role", {"employee_id": self.eid, "title": d["title"], "draft": d})
        rid = "shorts-channel-manager"
        folder = os.path.join(TMP, "team", "roles", rid)
        with open(os.path.join(folder, "skills", "daily-standup", "SKILL.md")) as fh:
            self.assertNotIn("Drift..Master", fh.read())                       # what's saved is the rewritten copy
        with open(os.path.join(folder, "role.json")) as fh:
            role = json.load(fh)
        self.assertEqual((role["trained_by"], role["stats"]["lessons"]), ("Alex", 9))
        self.assertNotIn("Drift", role["scope"])
        z = rolebook.package(rid)
        with open(z, "rb") as fh:
            data = fh.read()
        import shutil
        shutil.rmtree(folder)
        import base64
        msg = orders.execute("Alex", "import_role", {"data": "data:application/zip;base64," + base64.b64encode(data).decode()})
        self.assertIn("trained by Alex", msg)
        listed = next(r for r in rolebook.all_roles()["roles"] if r["id"] == rid)
        self.assertEqual((listed["source"], listed["trained_by"], listed["skills_in"]), ("yours", "Alex", ["daily-standup"]))
        self.assertIn("voiceover", listed["experience"])
        orders.execute("Alex", "hire", {"name": "Zain", "role": "Channel manager", "template": rid, "first_day": False})
        with open(os.path.join(TMP, "employees", "zain", "EXPERIENCE.md")) as fh:
            xp = fh.read()
        self.assertIn("trained by Alex", xp)
        self.assertIn("silent ones were rejected", xp)
        self.assertTrue(os.path.isfile(os.path.join(TMP, "employees", "zain", "skills", "daily-standup", "SKILL.md")))

    def test_unsafe_or_wrong_files_are_refused(self):
        import rolebook
        for files in ({"../evil/role.json": "{}"}, {"notes.txt": "hi"}):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, t in files.items():
                    z.writestr(n, t)
            with self.assertRaises(rolebook.RoleError):
                rolebook.import_role(data=buf.getvalue())
        with self.assertRaises(rolebook.RoleError):
            rolebook.import_role(data=b"not a zip")
        with self.assertRaises(rolebook.RoleError):
            rolebook.import_role("http://example.com/role.zip")

    def test_the_trainer_is_offered_to_share_once(self):
        import rolebook
        self.assertEqual(rolebook.share_nudge(), [])                         # one day in: not yet
        reg = engine.registry()
        reg["employees"][self.eid]["hired"] = "2026-01-01"
        engine.save_registry(reg)
        got = rolebook.share_nudge()
        self.assertEqual([k for k, _ in got], [self.eid])
        self.assertEqual(rolebook.share_nudge(), [])                         # once

    def test_community_sharing_without_github_tools(self):
        import shutil
        import rolebook
        rolebook.save_role(self.eid, "Shorts channel manager", "Alex", draft=dict(self.DRAFT, trained_by="Alex"))
        real = shutil.which
        shutil.which = lambda name, *a, **k: None if name == "gh" else real(name, *a, **k)
        try:
            out = rolebook.publish("shorts-channel-manager", "Alex")
        finally:
            shutil.which = real
        self.assertFalse(out["pr"])
        self.assertTrue(out["url"].startswith("https://github.com/BasemTarekkamal/orbit/issues/new?"))
        self.assertTrue(os.path.isfile(out["file"]))
        self.assertIn("drag", out["how"])


class Asleep(unittest.TestCase):
    """A sleeping laptop: no run starts in its few-second wakes, a missed day is made up for in one run, a due
    follow-up isn't lost, its report reaches the owner, and the computer stays up while a run is going."""

    def setUp(self):
        import hire
        self.hire = hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"local-alex": {"name": "Alex", "local": True}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7394}, "workdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]})
        import awake
        import staffd
        self.awake, self.staffd = awake, staffd
        self.real = (staffd.run_async, engine.online, awake._since)
        self.started = []
        staffd.run_async = lambda *a, **k: self.started.append((a, k))
        engine.online = lambda *a, **k: True
        self.eid = hire.hire("Suoo", "Content creator", "Videos", supervisor="Alex", picked=["standup", "eod", "reminders"])
        self.st_f = os.path.join(TMP, "employees", self.eid, "state", "schedule.json")
        if os.path.exists(self.st_f):                                     # an earlier test's Suoo, same folder
            os.remove(self.st_f)

    def tearDown(self):
        self.staffd.run_async, engine.online, self.awake._since = self.real

    def write_schedule(self, st):
        os.makedirs(os.path.dirname(self.st_f), exist_ok=True)
        with open(self.st_f, "w") as fh:
            json.dump(st, fh)

    def test_no_run_starts_in_a_few_second_wake(self):
        import datetime as dt
        now = dt.datetime.now()
        reg = engine.registry()
        reg["jobs"] = {"standup": {"at": (now - dt.timedelta(minutes=1)).strftime("%H:%M"), "days": "daily"}}
        engine.save_registry(reg)
        self.awake._since = time.time() - 5                               # awake for 5 seconds
        self.assertFalse(self.awake.settled())
        self.staffd.tick_jobs()
        self.staffd.tick_reminders()
        self.assertEqual(self.started, [])
        self.awake._since = time.time() - 120                             # really awake now
        self.staffd.tick_jobs()
        self.assertEqual(len(self.started), 1)

    def test_a_missed_day_is_made_up_for_in_one_run(self):
        import datetime as dt
        import team
        now = dt.datetime.now()
        reg = engine.registry()
        at = (now - dt.timedelta(hours=6)).strftime("%H:%M") if now.hour >= 6 else "00:00"
        if now.hour < 6:
            self.skipTest("too close to midnight")
        reg["jobs"] = {"standup": {"at": at, "days": "daily"}, "eod": {"at": at, "days": "daily"}}
        engine.save_registry(reg)
        old = (now - dt.timedelta(days=2)).strftime("%F")
        self.write_schedule({"standup": old, "eod": old})
        self.staffd.tick_jobs()
        self.assertEqual(len(self.started), 1)
        a, k = self.started[0]
        self.assertEqual(a[2], "catchup")
        self.assertIn("Standup", a[1])
        self.assertIn("End of day", a[1])
        self.assertFalse(any("offline" in r.get("body", "") for r in team.tail(team.FEED, 5)))
        self.staffd.tick_jobs()
        self.assertEqual(len(self.started), 1)                            # once
        k["retry"]()                                                      # the network failed again: it comes back
        with open(self.st_f) as fh:
            st = json.load(fh)
        self.assertEqual(st["catchup"], ["eod", "standup"])

    def test_a_new_routine_is_not_a_missed_one(self):
        import datetime as dt
        now = dt.datetime.now()
        if now.hour < 6:
            self.skipTest("too close to midnight")
        reg = engine.registry()
        reg["jobs"] = {"standup": {"at": (now - dt.timedelta(hours=6)).strftime("%H:%M"), "days": "daily"},
                       "eod": {"at": (now - dt.timedelta(hours=6)).strftime("%H:%M"), "days": "daily"}}
        engine.save_registry(reg)
        self.staffd.tick_jobs()
        self.assertEqual(self.started, [])

    def test_a_followup_waits_runs_reports_and_retries(self):
        import datetime as dt
        import osinfo
        sys.path.insert(0, os.path.join(KIT, "core", "tools"))
        import remind
        import team
        ws = os.path.join(TMP, "employees", self.eid)
        past = (dt.datetime.now() - dt.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        remind.save(ws, [{"id": "R-0001", "at": past, "to": "me", "text": "Make the batch", "repeat": "daily", "agent": True}])
        engine.online = lambda *a, **k: False
        self.staffd.tick_reminders()
        self.assertEqual(self.started, [])                                # offline: not consumed
        self.assertEqual(remind.load(ws)[0]["at"], past)
        engine.online = lambda *a, **k: True
        self.staffd.tick_reminders()
        a, k = self.started[0]
        self.assertEqual(a[2], "followup")
        shown, real = [], osinfo.notify
        osinfo.notify = lambda t, b: shown.append(b) or True
        try:
            k["on_done"]("Standup: 3 Shorts ready.")                      # no phone channel: it still reaches the owner
        finally:
            osinfo.notify = real
        self.assertTrue(any(r.get("body") == "Standup: 3 Shorts ready." for r in team.tail(team.FEED, 5)))
        self.assertEqual(shown, ["Standup: 3 Shorts ready."])
        k["retry"]()
        ids = [r["id"] for r in remind.load(ws)]
        self.assertIn("R-0001r", ids)                                     # the failed one comes back in 10 minutes
        self.assertIn("R-0001", ids)                                      # the daily one still stands

    def test_sleep_is_seen_and_told(self):
        import panel
        now = time.time()
        with open(self.awake.FILE, "w") as fh:
            json.dump([], fh)
        self.awake.record(now - 8 * 3600, now - 7 * 3600)
        self.awake.record(now - 7 * 3600 + 30, now - 3600)                 # a dark wake between: one sleep
        s = self.awake.slept(24)
        self.assertEqual(s["longest"], 7.0)
        needs = panel.needs_you(panel.members(), [], {}, {})
        self.assertEqual(needs[0]["kind"], "asleep")
        self.assertIn("slept 7.0 hours", needs[0]["title"])
        os.remove(self.awake.FILE)

    def test_the_computer_stays_up_during_a_run(self):
        real = osinfo.KIND
        try:
            osinfo.KIND = "mac"
            self.assertEqual(osinfo.keep_awake_cmd(42, battery=True), ["caffeinate", "-s", "-i", "-w", "42"])
            self.assertEqual(osinfo.keep_awake_cmd(42), ["caffeinate", "-s", "-w", "42"])
            self.assertEqual(osinfo.keep_awake_cmd(42, battery=True, seconds=120), ["caffeinate", "-s", "-i", "-t", "120"])
            osinfo.KIND = "wsl"
            cmd = osinfo.keep_awake_cmd(42, battery=True)
            self.assertEqual(cmd[:2], ["bash", "-c"])
            self.assertIn("kill -0 42", cmd[2])
            self.assertIn("SetThreadExecutionState(1)", cmd[2])
        finally:
            osinfo.KIND = real
        spawned, real_spawn = [], self.awake._spawn
        self.awake._spawn = lambda c: spawned.append(c)
        try:
            self.awake.hold(42)
            reg = engine.registry()
            reg["keep_awake"] = "off"
            engine.save_registry(reg)
            self.awake.hold(42)
        finally:
            self.awake._spawn = real_spawn
        self.assertLessEqual(len(spawned), 1)                             # "off" means off


class CloudShift(unittest.TestCase):
    """Laptop first; closed or offline, the crew carries on in the cloud; back, the work comes home. No real cloud here."""

    def setUp(self):
        import cloud
        import hire
        self.cloud, self.hire = cloud, hire
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {"local-alex": {"name": "Alex", "local": True}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7392}, "workdays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                              "cloud_environment": "env_test"})
        self.eid = hire.hire("Cleo", "Researcher", "Coffee", supervisor="Alex")
        self.ws = os.path.join(TMP, "employees", self.eid)
        if os.path.exists(cloud._path(self.eid)):
            os.remove(cloud._path(self.eid))
        self.calls, self.sent = [], []
        self.real = (cloud.trigger, cloud.send, cloud.new_session, cloud.pull)
        cloud.trigger = lambda action, tid="", body=None: self.calls.append((action, tid, body)) or {"trigger": {"id": "trig_%d" % len(self.calls)}}
        cloud.send = lambda sid, text: self.sent.append(text)
        cloud.new_session = lambda emp, desk, first: "session_new"

    def tearDown(self):
        self.cloud.trigger, self.cloud.send, self.cloud.new_session, self.cloud.pull = self.real

    def test_the_schedule_skips_only_today(self):
        import datetime as dt
        thu = dt.date(2026, 11, 5)
        days = self.cloud.cron_for("10:00", thu, today=thu).split()[3].split(",")
        self.assertNotIn("5", days)
        self.assertIn("6", days)                                         # Friday: on
        self.assertNotIn("7", days)                                      # Saturday: not a workday here
        self.assertIn("9", days)
        everyday = self.cloud.cron_for("14:30", None, today=thu)
        self.assertEqual(everyday.split()[1:3], ["30", "14"])
        self.assertIn("5", everyday.split()[3].split(","))
        self.assertTrue(everyday.startswith("CRON_TZ="))

    def test_setup_makes_one_routine_per_check_time_with_no_connected_apps(self):
        st = self.cloud.setup(self.eid)
        self.assertEqual(sorted(st["slots"]), ["10:00", "14:00", "18:00"])     # an hour after standup, initiative, end of day
        made = [c for c in self.calls if c[0] == "create"]
        self.assertEqual(len(made), 3)
        self.assertTrue(all(c[2]["persistent_session_id"] == "session_new" for c in made))
        self.assertTrue(all(c[2]["notifications"]["channel"]["push"] for c in made))
        self.assertEqual(sum(1 for c in self.calls if c[2] == {"clear_mcp_connections": True}), 3)
        self.assertIn("Standing instructions from Alex", self.sent[0])     # the owner's instruction, not a stray prompt

    def test_here_says_skip_gone_it_fires_back_it_pulls(self):
        import datetime as dt
        now = dt.datetime.now()
        if not 1 <= now.hour <= 22:
            self.skipTest("too close to midnight")
        reg = engine.registry()
        reg["workdays"] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        at = (now + dt.timedelta(minutes=30)).strftime("%H:%M")
        reg["jobs"] = {"standup": {"at": (now + dt.timedelta(minutes=30) - dt.timedelta(hours=1)).strftime("%H:%M")}}
        engine.save_registry(reg)
        yesterday = (now - dt.timedelta(days=1)).strftime("%F")
        self.cloud._save(self.eid, {"session": "session_old", "seeded_at": time.strftime("%F"), "slots": {at: {"trigger": "t1", "skipped": yesterday}}})
        self.calls.clear()
        self.cloud._tick_one(self.eid)                                    # 30 minutes ahead, and here: skip today
        self.assertEqual(self.calls[0][:2], ("update", "t1"))
        self.assertIn("cron_expression", self.calls[0][2])
        self.assertEqual(self.cloud.state(self.eid)["slots"][at]["skipped"], now.strftime("%F"))
        self.calls.clear()
        self.cloud._tick_one(self.eid)
        self.assertEqual(self.calls, [])                                  # once a day
        self.assertFalse(self.cloud.missed(self.cloud.state(self.eid)))
        # a check time passed with no skip: the cloud took that shift
        past = (now - dt.timedelta(minutes=30)).strftime("%H:%M")
        self.cloud._save(self.eid, {"session": "session_old", "seeded_at": time.strftime("%F"), "slots": {past: {"trigger": "t2", "skipped": yesterday}}})
        self.assertTrue(self.cloud.missed(self.cloud.state(self.eid)))
        pulled = []
        self.cloud.pull = lambda e: pulled.append(e) or {"files": 2, "reports": 1}
        self.cloud._tick_one(self.eid)
        self.assertEqual(pulled, [self.eid])
        self.assertEqual(self.cloud.state(self.eid)["session"], "session_old")   # one desk, for good
        self.assertFalse(self.cloud.missed(self.cloud.state(self.eid)))
        with open(os.path.join(self.ws, "state", "schedule.json")) as fh:
            self.assertIn("cloud", json.load(fh)["catchup"])              # and the crew member merges the work

    def test_the_desk_hears_what_changed_here(self):
        self.cloud.build_desk(self.eid)
        self.cloud._commit(self.cloud._desk_dir(self.eid))
        self.assertEqual(self.cloud.delta(self.eid), "")
        with open(os.path.join(self.ws, "LESSONS.md"), "a") as fh:
            fh.write("- A new lesson.\n")
        with open(os.path.join(self.ws, "TASKS.md"), "a") as fh:
            fh.write("- A new task.\n")
        change = self.cloud.delta(self.eid)
        self.assertIn("+- A new lesson.", change)
        self.assertNotIn("A new task", change)                            # the board travels in the note itself
        self.assertEqual(self.cloud.delta(self.eid), "")

    def test_the_desk_carries_know_how_not_secrets_or_media(self):
        for rel, body in (("research/a.md", "notes"), ("content/x.mp4", "video"), ("api_token.txt", "s3cret"), (".env", "KEY=1"),
                          ("state/cloud.json", "{}"), (".mcp.json", "{}"), ("kit/Poppins.ttf", "font")):
            p = os.path.join(self.ws, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(body)
        desk = self.cloud.build_desk(self.eid)
        have = {os.path.relpath(os.path.join(b, n), desk) for b, _, ns in os.walk(desk) for n in ns if ".git" + os.sep not in b + os.sep}
        self.assertTrue({"research/a.md", "kit/Poppins.ttf", "ROLE.md", "CLAUDE.md", "handbook.md", "handoff.py", "PLAN.md"} <= have)
        self.assertFalse({"content/x.mp4", "api_token.txt", ".env", "state/cloud.json", ".mcp.json"} & have)
        with open(os.path.join(desk, "CLAUDE.md")) as fh:
            md = fh.read()
        self.assertIn("Cleo", md)
        self.assertIn("Never post, publish, upload, log in", md)
        with open(os.path.join(desk, "jobs", "standup.md")) as fh:
            self.assertNotIn("{name}", fh.read())
        self.assertEqual(subprocess.run(["git", "remote"], cwd=desk, capture_output=True, text=True).stdout, "")   # uploaded as it is

    def test_handoff_prints_what_changed_and_only_once(self):
        desk = self.cloud.build_desk(self.eid)
        with open(os.path.join(desk, "research.md"), "w") as fh:
            fh.write("found it")
        with open(os.path.join(desk, "render.mp4"), "wb") as fh:
            fh.write(b"x" * 100)
        run = lambda: subprocess.run([sys.executable, "handoff.py"], cwd=desk, capture_output=True, text=True).stdout
        out = run()
        self.assertIn("<<<ORBIT-FILE research.md\nfound it\n>>>ORBIT-FILE", out)
        self.assertIn("ORBIT-LEFT-ON-DESK render.mp4 (100 bytes)", out)
        self.assertTrue(out.strip().endswith("ORBIT-DONE"))
        self.assertNotIn("research.md", run())

    def test_the_work_comes_home_without_touching_memory(self):
        import team
        lines = [{"type": "user", "timestamp": "2026-11-05T07:00:00Z", "message": {"content": [{"type": "tool_result", "content":
                  "<<<ORBIT-FILE research/new.md\nfresh\n>>>ORBIT-FILE\n<<<ORBIT-FILE PLAN.md\ncloud plan\n>>>ORBIT-FILE\n"
                  "<<<ORBIT-FILE ../../evil.md\nno\n>>>ORBIT-FILE\n<<<ORBIT-FILE .git/config\nno\n>>>ORBIT-FILE\nORBIT-LEFT-ON-DESK a.mp4 (5 bytes)\nORBIT-DONE"}]}},
                 {"type": "assistant", "timestamp": "2026-11-05T07:01:00Z", "message": {"content": [{"type": "text", "text": "Cloud shift: wrote research/new.md."}]}},
                 {"type": "assistant", "timestamp": "2026-11-04T07:01:00Z", "message": {"content": [{"type": "text", "text": "Cloud shift: an older one."}]}}]
        path = os.path.join(TMP, "transcript.jsonl")
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(x) for x in lines))
        self.cloud._transcript = lambda emp, sid: path
        with open(os.path.join(self.ws, "PLAN.md"), encoding="utf-8") as fh:
            before = fh.read()
        self.cloud._save(self.eid, {"session": "session_x", "pulled_upto": "2026-11-04T12:00:00Z"})
        got = self.real[3](self.eid)
        self.assertEqual(got["reports"], 1)
        day = time.strftime("%F")
        root = os.path.join(self.ws, "notes", "cloud", day)
        with open(os.path.join(root, "research", "new.md")) as fh:
            self.assertEqual(fh.read(), "fresh")
        with open(os.path.join(self.ws, "PLAN.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)                           # its memory is merged by the crew member, never overwritten
        self.assertFalse(os.path.exists(os.path.join(self.ws, "notes", "evil.md")))
        self.assertFalse(os.path.exists(os.path.join(root, ".git")))
        with open(os.path.join(root, "REPORTS.md")) as fh:
            self.assertIn("ORBIT-LEFT-ON-DESK a.mp4", fh.read())
        self.assertTrue(any(r.get("body") == "Cloud shift: wrote research/new.md." for r in team.tail(team.FEED, 5)))
        self.assertIn("notes/cloud/%s/" % day, self.cloud.merge_note(self.eid))
        self.assertEqual(self.cloud.merge_note(self.eid), "")             # once

    def test_switching_it_on_and_off(self):
        import grants
        self.assertIsNone(grants.from_text("Alex", "Nobody cloud on"))
        reply = grants.from_text("Alex", "Cleo cloud on")
        self.assertIn("cloud desk", reply)
        self.assertTrue(self.cloud.is_on(self.eid))
        self.calls.clear()
        reply = grants.from_text("Alex", "Cleo cloud off")
        self.assertIn("off", reply)
        self.assertFalse(self.cloud.is_on(self.eid))
        self.assertTrue(all(c[2] == {"enabled": False} for c in self.calls) and self.calls)

    def test_paused_or_retired_means_no_cloud_shifts(self):
        import orders
        self.cloud.enable(self.eid)
        self.calls.clear()
        orders.execute("Alex", "pause", {"employee_id": self.eid})
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(c[2] == {"enabled": False} for c in self.calls))
        self.calls.clear()
        orders.execute("Alex", "resume", {"employee_id": self.eid})
        self.assertTrue(all(c[2].get("enabled") is True for c in self.calls) and self.calls)
        self.calls.clear()
        orders.execute("Alex", "retire", {"employee_id": self.eid})
        self.assertTrue(all(c[2] == {"enabled": False} for c in self.calls) and self.calls)

    def test_new_hires_get_it_and_an_api_key_cant(self):
        import orders
        orders.execute("Alex", "hire", {"name": "Nia", "role": "Writer", "first_day": False})
        self.assertTrue(self.cloud.is_on("nia"))
        reg = engine.registry()
        reg["auth"] = "api_key"
        engine.save_registry(reg)
        self.assertIn("API key", self.cloud.available())
        with self.assertRaises(self.cloud.CloudError):
            self.cloud.enable(self.eid)


class ExtraComputing(unittest.TestCase):
    """The third option: the owner's own private GitHub repository. Never needed; nothing happens until it's connected."""

    def setUp(self):
        os.makedirs(os.path.join(TMP, "team"), exist_ok=True)
        engine.save_registry({"team_name": "Test", "owners": {}, "employees": {}, "panel": {"port": 7391}})
        import compute
        self.c = compute
        self.bin = tempfile.mkdtemp(dir=TMP)
        self.path = os.environ["PATH"]

    def tearDown(self):
        os.environ["PATH"] = self.path

    def fake_gh(self, visibility="PRIVATE", permission="ADMIN"):
        log = os.path.join(self.bin, "gh.log")
        with open(os.path.join(self.bin, "gh"), "w") as fh:
            fh.write("#!/bin/sh\necho \"$@\" >> %s\ncase \"$1 $2\" in\n"
                     "\"repo view\") echo '{\"visibility\":\"%s\",\"viewerPermission\":\"%s\"}';;\n"
                     "\"api repos/a/b/contents/.github/workflows/orbit-compute.yml\") exit 1;;\n"
                     "*) echo '{}';;\nesac\n" % (log, visibility, permission))
        os.chmod(os.path.join(self.bin, "gh"), 0o755)
        os.environ["PATH"] = self.bin + os.pathsep + self.path
        return log

    def test_connect_needs_a_private_repo_you_can_write_to(self):
        self.fake_gh("PUBLIC")
        with self.assertRaisesRegex(self.c.ComputeError, "isn't private"):
            self.c.connect("a/b")
        self.fake_gh("PRIVATE", "READ")
        with self.assertRaisesRegex(self.c.ComputeError, "can't write"):
            self.c.connect("a/b")
        log = self.fake_gh()
        self.assertEqual(self.c.connect("https://github.com/a/b"), "a/b")
        with open(log) as fh:
            self.assertIn("-X PUT repos/a/b/contents/.github/workflows/orbit-compute.yml", fh.read())
        with self.assertRaisesRegex(self.c.ComputeError, "owner/name"):
            self.c.connect("justaname")

    def test_not_connected_is_fine(self):
        self.assertEqual(self.c.repo(), "")
        with self.assertRaisesRegex(self.c.ComputeError, "isn't connected"):
            self.c.run("echo hi", [], 5)

    def test_only_your_own_files_travel(self):
        ws = tempfile.mkdtemp(dir=TMP)
        with self.assertRaisesRegex(self.c.ComputeError, "isn't in your folder"):
            self.c._within(ws, "../../etc/passwd")
        with self.assertRaisesRegex(self.c.ComputeError, "doesn't exist"):
            self.c._within(ws, "nope.txt")

    def test_the_workflow_is_valid_and_has_no_secrets(self):
        self.assertIn("workflow_dispatch", self.c.WORKFLOW_YML)
        self.assertIn("contents: read", self.c.WORKFLOW_YML)
        self.assertNotIn("secrets.", self.c.WORKFLOW_YML)
        self.assertIn("COMMAND: ${{ inputs.command }}", self.c.WORKFLOW_YML)   # passed by env, never pasted into the script

