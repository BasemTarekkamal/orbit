# Setting up Orbit (instructions for Claude)

Someone asked you to set up Orbit on their Mac: a crew of AI employees that runs on this Mac and
on their own Claude plan. They may not be technical. Do every step yourself. Before each step, say in
one plain sentence what it does and why; after it, say what happened. Keep it calm and short.

**Never ask for, read, copy or print a password, a token or a Claude login** in this chat. Bot tokens
and the Apify token are typed into the control panel, a page on this Mac, never here. Don't use
`sudo`, don't change system settings, and stop to ask before anything that needs their Mac password.
If a step fails twice, stop and tell them plainly what failed and what you'd try next.

## 1. Check the Mac
- `sw_vers -productName` must say macOS. If not, stop: Orbit runs on macOS for now.
- `python3 --version` and `git --version`. If either is missing, macOS offers to install its developer
  tools in a dialog: tell them to click **Install**, wait for it to finish (a few minutes), then go on.

## 2. Get the kit
- If `~/orbit` is already a checkout of this repository: `git -C ~/orbit pull --ff-only`.
- Otherwise: `git clone https://github.com/BasemTarekkamal/orbit ~/orbit`.

## 3. Claude Code for the employees
The employees run on the `claude` command-line tool, signed in with the person's own Claude account
(the plan they already pay for). It is Anthropic's own program; Orbit never sees their login.
- `claude --version` (also try `~/.local/bin/claude --version`). If it isn't there, install it with
  Anthropic's official installer: `curl -fsSL https://claude.ai/install.sh | bash`.
- `claude auth status`. If it's signed in, go on. If not, tell them: "A page from Anthropic will open in
  your browser; sign in there with your Claude account." Run `claude auth login` with a long timeout.
  If it waits for something typed, ask them to open Terminal (⌘ Space, type Terminal, Enter), run
  `claude auth login` there, and tell you when it says they're signed in. Never sign them out.

## 4. Install
- `~/orbit/install.sh --yes`. It installs a few Python packages for this user only, the headless
  browser the employees research with (about 150 MB), and the `orbit` command, then starts the team's
  background service and opens the control panel in their browser. Takes two to five minutes.
- If it reports a problem, run `~/orbit/orbit doctor` and fix what it lists, one item at a time.

## 5. Hand over
Tell them, in your own words: "Your control panel is open in your browser. It asks your name and what
your business does, then you pick what your first employee should do. They start working right away,
and you can put them on your phone from there." If the page didn't open: `~/orbit/orbit panel`.
Stay available for questions; that's the whole setup.

## Extras, only when they ask
- **Voice notes** (transcribed on this Mac): needs Homebrew. If `brew --version` fails, explain that
  installing Homebrew asks for their Mac password, which they type themselves; with their yes, follow
  the command on https://brew.sh. Then `brew install ffmpeg whisper-cpp` and
  `~/orbit/orbit doctor --get-voice-model` (a 550 MB download from Hugging Face).
- **Sign Claude Code in again:** `claude auth login`.
- **Update Orbit:** `git -C ~/orbit pull --ff-only && ~/orbit/orbit restart`.
- **Something's wrong:** `~/orbit/orbit doctor`, then `~/orbit/orbit logs`.
- **Stop it:** `~/orbit/orbit stop`. Their team's folder (`~/Staff`) stays unless they ask you to
  delete it; confirm before you do, it holds everything their employees learned.
