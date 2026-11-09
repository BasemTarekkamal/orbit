"""Test hygiene: when a test module ends, its temporary folders go, and so do any Claude Code transcript folders
(~/.claude/projects/<path-slug>) that runs inside them created, so tests leave nothing behind in the owner's
Claude app or `claude --resume` list."""
from __future__ import annotations

import atexit
import os
import re
import shutil


def on_exit(*dirs):
    def clean():
        projects = os.path.expanduser("~/.claude/projects")
        for d in dirs:
            slugs = {re.sub(r"[^A-Za-z0-9]", "-", p) for p in (d, os.path.realpath(d))}
            shutil.rmtree(d, ignore_errors=True)
            try:
                names = os.listdir(projects)
            except OSError:
                names = []
            for n in names:
                if any(n.startswith(s) for s in slugs):
                    shutil.rmtree(os.path.join(projects, n), ignore_errors=True)
    atexit.register(clean)
