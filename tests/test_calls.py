"""Live-call tests: chat commands, the transcript loop (whisper and the listener faked), demo calls, orders.
Never records audio or calls Claude.  python3 -m unittest tests.test_calls
"""
from __future__ import annotations

import array
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

TMP = tempfile.mkdtemp(prefix="orbit-calls-test-")
os.environ["STAFFROOM_HOME"] = TMP
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "core"))
sys.path.insert(0, os.path.join(KIT, "core", "tools"))

import calls  # noqa: E402
import engine  # noqa: E402
import hire  # noqa: E402
import orders  # noqa: E402
import osinfo  # noqa: E402
import staffd  # noqa: E402
import team  # noqa: E402

RUNS = []
team.run_async = lambda *a, **k: RUNS.append((a, k))


def tone(seconds, amp=0.2):
    return array.array("f", [amp if (i // 20) % 2 else -amp for i in range(int(seconds * calls.SR))])


def silence(seconds):
    return array.array("f", bytes(4 * int(seconds * calls.SR)))


def state(d, on_end=None):
    a = os.path.join(d, ".audio")
    os.makedirs(a, exist_ok=True)
    tp = os.path.join(d, "transcript.md")
    with open(tp, "w") as fh:
        fh.write(osinfo.local("# Live call: t\n\nStarted now by Alex · heard on this Mac\n\n"))
    return {"emp_id": "lina", "name": "Lina", "by": "Alex", "title": "t", "started": "2026-10-30T10:00:00", "t0": time.time() - 90,
            "dir": d, "audio": a, "ws": d, "transcript_abs": tp, "transcript": "transcript.md", "offset": {"them": 0, "you": 0},
            "lines": 0, "last": "", "stop": threading.Event(), "on_end": on_end}


class Commands(unittest.TestCase):
    def test_start_and_stop_phrases(self):
        for t in ("start call", "Start the call: supplier pricing", "/call", "listen to my call", "ابدأ المكالمة"):
            self.assertEqual(staffd.call_intent(t), "start", t)
        for t in ("end call", "stop listening", "call is over", "/endcall", "انهي المكالمة"):
            self.assertEqual(staffd.call_intent(t), "stop", t)

    def test_look_alikes_are_ordinary_messages(self):
        for t in ("start researching call centres in Cairo", "remind me to end the call at 3",
                  "what did they say about price?", "can you start a call with the supplier tomorrow and also prepare notes on pricing"):
            self.assertIsNone(staffd.call_intent(t), t)

    def test_title(self):
        self.assertEqual(staffd.call_title("start call: supplier pricing"), "supplier pricing")
        self.assertEqual(staffd.call_title("start call"), "")


class Transcript(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        self.real = calls._whisper

    def tearDown(self):
        calls._whisper = self.real

    def write(self, st, key, a):
        with open(os.path.join(st["audio"], key + ".pcm"), "ab") as fh:
            fh.write(a.tobytes())

    def test_lines_are_labelled_timed_and_echo_dropped(self):
        st = state(self.d)
        self.write(st, "them", tone(10))
        self.write(st, "you", tone(10))
        said = {0: [(1, "Thirty one dollars a kilo from December.")]}
        calls._whisper = lambda a, prompt="": said[0] if len(a) else []
        calls._consume(st, final=True)
        body = open(st["transcript_abs"]).read()
        self.assertIn("[00:00:01] Them: Thirty one dollars a kilo from December.", body)
        self.assertNotIn("You:", body)                 # the mic heard the speakers: not counted twice
        self.assertEqual(st["lines"], 1)

    def test_silence_skips_whisper_and_live_chunks_wait_for_enough_audio(self):
        st = state(self.d)
        asked = []
        calls._whisper = lambda a, prompt="": asked.append(len(a)) or []
        self.write(st, "them", silence(40))
        calls._consume(st)
        self.assertEqual(asked, [])                     # silence: nothing sent to whisper
        self.assertGreater(st["offset"]["them"], 0)
        self.write(st, "you", tone(5))
        calls._consume(st)
        self.assertEqual(st["offset"]["you"], 0)        # 5 s isn't a chunk yet

    def test_quiet_cut_lands_in_the_last_five_seconds(self):
        a = tone(26) + silence(1) + tone(3)
        cut = calls._quiet_cut(a)
        self.assertTrue(26 * calls.SR <= cut <= 27 * calls.SR, cut)

    def test_finish_deletes_audio_and_hands_over_minutes(self):
        ended = []
        st = state(self.d, on_end=lambda eid, info: ended.append(info))
        self.write(st, "them", tone(3))
        calls._whisper = lambda a, prompt="": [(0, "Hello.")]
        calls.CALLS["lina"] = st
        info = calls._finish(st)
        self.assertFalse(os.path.exists(st["audio"]))
        self.assertEqual(ended[0]["transcript"], "transcript.md")
        self.assertIn(osinfo.local("min · heard on this Mac"), open(st["transcript_abs"]).read())
        self.assertNotIn("lina", calls.CALLS)
        self.assertEqual(info["lines"], 1)

    def test_nothing_heard_says_so_and_skips_minutes(self):
        ended = []
        st = state(self.d, on_end=lambda eid, info: ended.append(info))
        calls.CALLS["lina"] = st
        calls._finish(st)
        self.assertIn("Nothing was heard", open(st["transcript_abs"]).read())
        self.assertEqual(ended, [])


class DemoCall(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(os.path.join(TMP, "team"))
        engine.save_registry({"team_name": "Test", "owners": {"111": {"name": "Alex"}}, "employees": {},
                              "defaults": {"model": "sonnet"}, "panel": {"port": 7397}})
        self.eid = hire.hire("Lina", "Call notes", "Minutes from calls", supervisor="Alex", picked=["meetings", "telegram"])
        os.environ["STAFFROOM_DEMO"] = "1"
        RUNS.clear()

    def tearDown(self):
        os.environ.pop("STAFFROOM_DEMO", None)
        for eid in list(calls.CALLS):
            calls.stop(eid)
        time.sleep(0.2)

    def test_order_start_note_stop_minutes(self):
        res = orders.execute("Alex", "call_start", {"employee_id": self.eid, "title": "Supplier"})
        self.assertIn("Listening", res)
        with self.assertRaises(orders.OrderError):        # one call at a time on a Mac
            orders.execute("Alex", "call_start", {"employee_id": self.eid})
        self.assertIn(self.eid, calls.status())
        self.assertIn("listening to a live call", calls.live_note(self.eid))
        time.sleep(4.5)
        self.assertGreaterEqual(calls.status()[self.eid]["lines"], 1)
        orders.execute("Alex", "call_stop", {"employee_id": self.eid})
        for _ in range(40):
            if self.eid not in calls.CALLS:
                break
            time.sleep(0.1)
        self.assertNotIn(self.eid, calls.CALLS)
        self.assertEqual(calls.live_note(self.eid), "")
        jobs = [a[2] for a, k in RUNS]
        self.assertIn("minutes", jobs)

    def test_stop_without_a_call(self):
        with self.assertRaises(orders.OrderError):
            orders.execute("Alex", "call_stop", {"employee_id": self.eid})


if __name__ == "__main__":
    unittest.main()
