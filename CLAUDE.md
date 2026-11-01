# Orbit (for Claude, in a session opened in this folder)

This folder is the Orbit kit: the person's crew of AI employees runs from it (their team's data is in
`~/Staff`). The person is usually not technical: plain words, short answers.

- **"Ask Sara: …" / "tell Omar …" / "what's Lina working on?"** Pass it to that crew member and bring back
  their answer: `./orbit list` shows who works here (handle, name, role), then
  `./orbit run <handle> "<their message, word for word>"`. Show the answer as it came, without rewording
  it. It is the same crew member as in the control panel and on their phone: same memory, same limits.
- **Setting Orbit up, or something isn't working:** follow `SETUP.md` (`./orbit doctor` lists what's missing).
- **The control panel:** `./orbit panel` prints its link and opens it.
- Never read, print or copy anything in `~/Staff/.secrets`, and never type a token or password in chat:
  tokens go into the control panel. Don't change the crew's abilities or files unless the person asks.
