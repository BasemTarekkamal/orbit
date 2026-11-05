#!/usr/bin/env python3
"""staff-compute: run a heavy job on your owner's own GitHub, when they connected it. The third option, never needed.

Your work runs on this computer first, then on your cloud desk. If a job needs more than those (a long render, a big
batch) and your owner connected a private GitHub repository for it (Settings → Extra computing), it can run there on
their free GitHub Actions minutes.

    staff-compute status
    staff-compute run "<shell command>" [--files a.py assets/] [--minutes 60]

Sends the files you name, from your folder, to a fresh branch of that repository; runs the command on a Linux machine
there; waits; downloads what the command wrote into `out/` to research/compute/<id>/ (with job.log); deletes the branch.
Not connected? `status` says so: tell your owner once what it would make possible, and carry on without it.

Runs outside the sandbox (a toolbelt gateway). Only your own files travel, only to a private repository the owner chose.
No secrets are available to the job. Exit codes: 0 ok, 1 failed, 2 bad usage or not connected.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from _kit import config, require, workspace  # noqa: E402

WORKFLOW = ".github/workflows/orbit-compute.yml"
WORKFLOW_YML = """# Orbit's extra computing (staff-compute): runs one command from a job branch and keeps what it wrote in out/.
name: orbit-compute
on:
  workflow_dispatch:
    inputs:
      command:
        description: The command
        required: true
        type: string
      minutes:
        description: Time limit in minutes
        required: false
        default: "60"
        type: string
permissions:
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: ${{ fromJSON(inputs.minutes) }}
    steps:
      - uses: actions/checkout@v5
      - name: Run
        env:
          COMMAND: ${{ inputs.command }}
        run: |
          mkdir -p out
          set -o pipefail
          bash -c "$COMMAND" 2>&1 | tee out/job.log
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: out
          path: out
          retention-days: 3
"""


class ComputeError(RuntimeError):
    pass


def repo() -> str:
    return (config().get("compute") or {}).get("repo", "")


def gh(*args, timeout=120, cwd=None) -> str:
    gh_bin = shutil.which("gh")
    if not gh_bin:
        raise ComputeError("The GitHub command-line tool (gh) isn't installed on this computer.")
    r = subprocess.run([gh_bin, *args], capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if r.returncode != 0:
        raise ComputeError((r.stderr or r.stdout).strip()[-300:] or "gh failed")
    return r.stdout


def connect(name: str) -> str:
    """The owner's choice (Settings → Extra computing): checks their repository is private, adds the workflow."""
    name = name.strip().replace("https://github.com/", "").strip("/")
    if name.count("/") != 1:
        raise ComputeError("Give it as owner/name, like alex/orbit-compute")
    info = json.loads(gh("repo", "view", name, "--json", "visibility,viewerPermission"))
    if info.get("visibility") != "PRIVATE":
        raise ComputeError("That repository isn't private. Your crew's files would be public there: make it private first.")
    if info.get("viewerPermission") not in ("ADMIN", "WRITE", "MAINTAIN"):
        raise ComputeError("Your GitHub sign-in can't write to that repository.")
    body = base64.b64encode(WORKFLOW_YML.encode("utf-8")).decode("ascii")
    try:
        sha = json.loads(gh("api", "repos/%s/contents/%s" % (name, WORKFLOW))).get("sha")
    except ComputeError:
        sha = None
    args = ["api", "-X", "PUT", "repos/%s/contents/%s" % (name, WORKFLOW), "-f", "message=Orbit: extra computing", "-f", "content=" + body]
    if sha:
        args += ["-f", "sha=" + sha]
    try:
        gh(*args)
    except ComputeError as ex:
        if "workflow" in str(ex).lower() or "not accessible" in str(ex).lower() or "404" in str(ex):
            raise ComputeError("GitHub needs one more permission. In a terminal, run: gh auth refresh -s workflow. Then try again.")
        raise
    return name


def _within(ws: str, rel: str) -> str:
    p = os.path.realpath(os.path.join(ws, rel))
    if p != os.path.realpath(ws) and not p.startswith(os.path.realpath(ws) + os.sep):
        raise ComputeError("%s isn't in your folder" % rel)
    if not os.path.exists(p):
        raise ComputeError("%s doesn't exist" % rel)
    return p


def run(command: str, files: list, minutes: int) -> str:
    name, ws = repo(), workspace()
    if not name:
        raise ComputeError("Extra computing isn't connected.")
    job = time.strftime("%Y%m%d-%H%M%S")
    branch = "job/" + job
    tmp = tempfile.mkdtemp(prefix="orbit-compute-")
    try:
        gh("repo", "clone", name, tmp, "--", "--depth", "1", "-q", timeout=300)
        subprocess.run(["git", "checkout", "-qb", branch], cwd=tmp, check=True)
        for rel in files:
            src = _within(ws, rel)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst) or tmp, exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "state", ".claude"))
            else:
                shutil.copyfile(src, dst)
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
        subprocess.run(["git", "-c", "user.name=orbit", "-c", "user.email=orbit@staffroom.local", "commit", "-qm", "job " + job, "--allow-empty"],
                       cwd=tmp, check=True)
        subprocess.run(["git", "push", "-q", "origin", branch], cwd=tmp, check=True, timeout=600, capture_output=True)
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        gh("workflow", "run", "orbit-compute.yml", "-R", name, "--ref", branch, "-f", "command=" + command, "-f", "minutes=%d" % minutes)
        run_id = ""
        for _ in range(30):
            time.sleep(4)
            rows = json.loads(gh("run", "list", "-R", name, "--workflow", "orbit-compute.yml", "--branch", branch, "--limit", "1",
                                 "--json", "databaseId,createdAt"))
            if rows and rows[0]["createdAt"] >= started[:17]:
                run_id = str(rows[0]["databaseId"])
                break
        if not run_id:
            raise ComputeError("GitHub didn't start the job. It may be out of free minutes this month.")
        end = time.time() + (minutes + 15) * 60
        conclusion = ""
        while time.time() < end:
            info = json.loads(gh("run", "view", run_id, "-R", name, "--json", "status,conclusion"))
            if info.get("status") == "completed":
                conclusion = info.get("conclusion") or "unknown"
                break
            time.sleep(20)
        out = os.path.join(ws, "research", "compute", job)
        os.makedirs(out, exist_ok=True)
        try:
            gh("run", "download", run_id, "-R", name, "-n", "out", "-D", out, timeout=900)
        except ComputeError:
            pass
        return "GitHub job %s: %s. What it wrote is in research/compute/%s/ (job.log has its output)." % (job, conclusion or "still running, stopped waiting", job)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            gh("api", "-X", "DELETE", "repos/%s/git/refs/heads/%s" % (name, branch))
        except ComputeError:
            pass


def main() -> int:
    p = argparse.ArgumentParser(prog="staff-compute", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status")
    r = sub.add_parser("run")
    r.add_argument("command")
    r.add_argument("--files", nargs="*", default=[])
    r.add_argument("--minutes", type=int, default=60)
    a = p.parse_args()
    if not a.cmd:
        p.print_help()
        return 2
    require("compute")
    if a.cmd == "status":
        print("Connected: %s (private). Use it only when this computer and your cloud desk can't do the job." % repo() if repo() else
              "Not connected. If a job really needs it, tell your owner once: they make a private GitHub repository and paste "
              "its name in Settings → Extra computing. Carry on without it.")
        return 0
    if not repo():
        print("Extra computing isn't connected. Do what you can here; tell your owner once what it would make possible.")
        return 2
    try:
        print(run(a.command, a.files, max(1, min(a.minutes, 340))))
        return 0
    except (ComputeError, subprocess.SubprocessError, OSError) as ex:
        print("It didn't run: %s" % str(ex)[-300:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
