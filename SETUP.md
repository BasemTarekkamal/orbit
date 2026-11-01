# Setting up Orbit (instructions for Claude)

Someone asked you to set up Orbit on their computer: a crew of AI employees that runs on this computer
and on their own Claude plan. It works on a Mac, on Windows (inside WSL, the Linux that ships with
Windows) and on Linux. They may not be technical. Do every step yourself. Before each step, say in one
plain sentence what it does and why; after it, say what happened. Keep it calm and short.

**Never ask for, read, copy or print a password, a token or a Claude login** in this chat. Bot tokens
and the Apify token are typed into the control panel, a page on this computer, never here. Don't use
`sudo` and don't run anything as administrator yourself, don't change system settings, and when a step
needs their password or an administrator window, tell them exactly what to type and where, then wait.
If a step fails twice, stop and tell them plainly what failed and what you'd try next.

## 1. Which computer
- `uname -s` says `Darwin`: a Mac. Follow **Mac** below.
- `uname -s` says `Linux`: follow **Linux** below.
- Otherwise (`MINGW…`/`MSYS…`, or PowerShell where `$env:OS` is `Windows_NT`): Windows. Follow **Windows**.

## Mac
1. `python3 --version` and `git --version`. If either is missing, macOS offers to install its developer
   tools in a dialog: tell them to click **Install**, wait for it to finish (a few minutes), then go on.
2. Get the kit. If `~/orbit` is already a checkout of this repository: `git -C ~/orbit pull --ff-only`.
   Otherwise: `git clone https://github.com/BasemTarekkamal/orbit ~/orbit`.
3. Claude Code for the employees. The employees run on the `claude` command-line tool, signed in with
   the person's own Claude account (the plan they already pay for). It is Anthropic's own program;
   Orbit never sees their login.
   - `claude --version` (also try `~/.local/bin/claude --version`). If it isn't there, install it with
     Anthropic's official installer: `curl -fsSL https://claude.ai/install.sh | bash`.
   - `claude auth status`. If it's signed in, go on. If not, tell them: "A page from Anthropic will open
     in your browser; sign in there with your Claude account." Run `claude auth login` with a long
     timeout. If it waits for something typed, ask them to open Terminal (⌘ Space, type Terminal,
     Enter), run `claude auth login` there, and tell you when it says they're signed in. Never sign them out.
4. Install: `~/orbit/install.sh --yes`. It installs a few Python packages for this user only, the
   headless browser the employees research with (about 150 MB), and the `orbit` command, then starts
   the team's background service and opens the control panel in their browser. Two to five minutes.
   If it reports a problem, run `~/orbit/orbit doctor` and fix what it lists, one item at a time.
5. Hand over (below).

## Windows
Orbit runs inside WSL 2 there: that is what lets it keep the crew in a sandbox. You run each Linux
command from here with `wsl -d <distro> -- bash -lc "<command>"` (the distro name comes from step 1;
usually `Ubuntu`). Quote the command so the Windows shell passes it through whole.
1. `wsl -l -v`. If it lists no distro, or says WSL isn't installed, tell them: "Windows needs its Linux
   part turned on, once. Click Start, type **PowerShell**, right-click it and choose **Run as
   administrator**, then type `wsl --install` and press Enter. Restart when it asks. After the restart
   an **Ubuntu** window opens: choose a username and a password (only for this Linux; you'll type it
   once more in a minute). Tell me when you see the Ubuntu prompt." Wait for them. If the VERSION
   column says 1: `wsl --set-version <distro> 2` (a few minutes).
2. Get the kit: `wsl -d <distro> -- bash -lc "git -C ~/orbit pull --ff-only 2>/dev/null || git clone
   https://github.com/BasemTarekkamal/orbit ~/orbit"`. If git is missing, step 3 installs it: do step 3
   first, then this.
3. System packages (the sandbox, voice, OCR, the browser's libraries) need their Ubuntu password. Ask
   them to type this in the Ubuntu window and wait until it prints Done:
   `sudo sh ~/orbit/setup-linux.sh`
   (if ~/orbit isn't there yet: `sudo apt-get update && sudo apt-get install -y git`, then step 2, then this).
4. Claude Code inside Ubuntu (the employees run on this copy; it signs in to the same Claude account):
   `wsl -d <distro> -- bash -lc "~/.local/bin/claude --version || curl -fsSL https://claude.ai/install.sh | bash"`.
   Then `wsl -d <distro> -- bash -lc "~/.local/bin/claude auth status"`. If it isn't signed in, ask them
   to type `~/.local/bin/claude auth login` in the Ubuntu window, open the link it shows, sign in with
   their Claude account, and tell you when it says they're signed in.
5. Install: `wsl -d <distro> -- bash -lc "~/orbit/install.sh --yes"`. It starts the team from the
   Windows side (it keeps running after the Ubuntu window closes, and starts again at every Windows
   login) and opens Mission Control in their Windows browser. If it reports a problem:
   `wsl -d <distro> -- bash -lc "~/orbit/orbit doctor"` and fix what it lists.
6. Hand over (below).

## Linux
1. `~/orbit/install.sh` needs a few system packages first. If `bwrap`, `socat`, `git` or pip is missing
   (`command -v bwrap socat git; python3 -m pip --version`), get the kit if you can
   (`git clone https://github.com/BasemTarekkamal/orbit ~/orbit`), then ask them to run in their own
   terminal, where it asks their password: `sudo sh ~/orbit/setup-linux.sh`. Wait until it prints Done.
2. Claude Code: as in **Mac** step 3 (`curl -fsSL https://claude.ai/install.sh | bash`, `claude auth status`,
   and if needed they run `claude auth login` themselves).
3. Install: `~/orbit/install.sh --yes`. If it reports a problem, run `~/orbit/orbit doctor`.
4. Hand over (below).

## Hand over
Tell them, in your own words, short:
- "Your control panel is open in your browser. It asks your name and what your business does, then you
  pick a job; your Claude asks a few questions about it and writes their card. When you launch them,
  Claude opens on them and they start right away with a real first task." If the page
  didn't open: `~/orbit/orbit panel` (on Windows through `wsl -d <distro> -- bash -lc`).
- How they'll talk to their crew, all three ways, since they won't think to ask:
  1. **In the control panel:** open the crew member and type; the answer appears right under it.
  2. **On their phone** (recommended): Telegram, Slack or Discord, through a bot of their own. The panel's
     "Connect your phone" walks them through it in about two minutes. Then they message the crew from
     anywhere, send voice notes and files, and get the routine reports there.
  3. **In Claude itself:** each crew member's page has **Open in Claude**, a Claude session in their own
     folder, with the same job, memory and safety locks (it opens on its own right after a hire; the first
     time, Claude asks them to confirm the folder). And in any Claude session in the `orbit` folder, "ask
     Sara: …" works too: you pass it on with `~/orbit/orbit run <handle> "<message>"` (handles:
     `~/orbit/orbit list`) and show the answer as it came.
- What to expect: an answer in a minute or two (deep research takes longer), each with "How I did it".
  On their own, crew members only send the routines ticked in Manage (like a morning brief) and things
  that need the owner. They never post, buy, or message anyone but the owners.
Then offer to stay while they connect their phone. That's the whole setup.

## Extras, only when they ask
- **Voice notes and live calls** (transcribed on this computer):
  - Mac: needs Homebrew. If `brew --version` fails, explain that installing Homebrew asks for their Mac
    password, which they type themselves; with their yes, follow the command on https://brew.sh. Then
    `brew install ffmpeg whisper-cpp` and `~/orbit/orbit doctor --get-voice-model` (a 550 MB download).
  - Windows and Linux: `~/orbit/orbit doctor --get-whisper --get-voice-model` (builds the speech engine,
    a few minutes, and downloads the 550 MB model). For live calls on Windows, Python for Windows is
    needed too: ask them to run in PowerShell `winget install Python.Python.3.12`, then
    `py -m pip install soundcard numpy`.
- **Sign Claude Code in again:** `claude auth login` (on Windows, in the Ubuntu window).
- **Update Orbit:** `git -C ~/orbit pull --ff-only && ~/orbit/orbit restart`.
- **Something's wrong:** `~/orbit/orbit doctor`, then `~/orbit/orbit logs`.
- **Stop it:** `~/orbit/orbit stop`. Their team's folder (`~/Staff`) stays unless they ask you to
  delete it; confirm before you do, it holds everything their employees learned.
