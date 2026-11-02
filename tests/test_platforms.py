"""Windows (WSL) and Linux: what differs from a Mac, tested on any computer by pretending.
Never records real audio or calls Claude.  python3 -m unittest tests.test_platforms
"""
from __future__ import annotations

import io
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
