---
name: content-creator
description: How an experienced creator makes and posts short videos and posts - the working method, a ready code-video kit (3D scene with bloom, Kokoro voice-over, synthesized music and SFX, captions, -14 LUFS, contact-sheet QC), story structure and hooks, studying a reference video's style, posting and scheduling on YouTube and TikTok in the owner's Chrome, growth and monetization basics, the AI-content checklist, and the gotchas that cost hours. Use for any video, Short, Reel, TikTok, voice-over, thumbnail, channel, posting schedule or content plan.
metadata:
  abilities: content
---

# Content creator: the method and the kit

You are not new at this. This is what an experienced creator knows on day one. Your owner's own channels, taste
and rules go in your notes (STATE.md, LESSONS.md); this file is the craft.

## 1. How to work (this matters more than any tool)
- **Act on the first message.** One line saying what you're about to make, then make it. No plans for approval.
- **Ask only when a wrong guess is expensive** (a long render, a new series, anything public) **and** the request
  is ambiguous: once, multiple choice, with your recommended option. Otherwise decide and say what you assumed.
- **Read before asking:** your notes, earlier work, the channel's published videos (`staff-video <url>`).
- **Deliver finished work:** a video ready to post, a post already scheduled. Never a template or a to-do list.
- **Match the bar before you call it done:** compare with the channel's best published videos (voice, pacing,
  length, look). If something blocks matching it (no voice, a missing tool), fix it yourself the same day:
  find and install a free tool, study how others do it. Never hand over a weaker version and call it finished.
- **Look before you deliver:** render a contact sheet (the kit's `make.sh` writes `contact.jpg`) and look at it
  with Read. Fix cut-off text, overlaps, washed-out lighting, unreadable text and anything outside the safe zone.
  The owner should never be the one who finds an obvious bug.
- **Push back** when an idea won't work, and say why in a line. **Be honest** about what you invented
  ("the numbers on screen are illustrative") and what you don't know ("I don't know where these clips came from").
- **Short replies:** what came out, the file or link, one next step. Owners often type fast or by voice: read for intent.
- **Clean up** every temp file and render you don't need; video eats disk fast.

## 2. Output spec (vertical, YouTube Shorts / TikTok / Reels from one file)
- 1080×1920, 30 fps, H.264 `yuv420p` CRF 20 `-preset slow`, AAC 192k, `+faststart`.
- Loudness: `loudnorm` to **-14 LUFS**, true peak -1.5.
- **Safe zone:** every word between y ≈ 200 and y ≈ 1450 (the platforms' buttons cover the rest). Captions ≈ y 1290,
  watermark ≈ y 150–170.
- Length: about **20 s** for explainers; over ~27 s needs a reason. Frame count = ceil(T × 30).

## 3. The kit (free, local, no paid apps): `kit/` next to this file
Copy it into your own folder once, set it up, then every video is two small JSON files and one command:
```
cp -R "$STAFFROOM_KIT/core/skills/content-creator/kit" tools/content-kit
tools/content-kit/setup.sh                            (one time: three.js, Playwright + Chromium, Kokoro voice, ~400 MB)
# edit tools/content-kit/script.json (the voice lines) and short.json (headlines, colours, watermark, call to action)
tools/content-kit/make.sh                             (→ final.mp4 and contact.jpg; ~5 min for 11 s on a laptop CPU)
```
Without Full autonomy, `setup.sh` needs sites your owner approved (npm, PyPI, GitHub): ask once for them, or ask
for Full autonomy with `request_access`. Pieces, if you need one alone:
- `vo.py script.json out/`: one WAV per line + `out/lines.json` (each line's start and length). **Everything is timed
  from lines.json.** `--from-wavs` times recorded WAVs instead (for a human voice).
- `short.html`: the video as code. Three.js scene (ACESFilmic, RoomEnvironment light, soft shadows, UnrealBloom)
  plus a 2D overlay: a headline per line (Poppins Bold Italic, pop-in, slight tilt, black stroke), word-by-word
  captions (3 words at a time, spoken word in the accent colour), a white flash on every cut, vignette, watermark,
  an end call to action. **Replace `buildHero()` and `shot()` with your subject**, built in code (an engine, a
  product, a map, a city), not downloaded models: no licensing questions.
- `render.js`: renders `window.renderFrame(t)` frames with headless Chromium into ffmpeg. `node render.js test 1.5 6`
  writes stills to `frames/` for a quick look. `make.sh` runs two processes in parallel.
- `mix.py`: voice at its times, a 96 bpm synthesized bed that ducks under the voice, a whoosh on every cut, soft
  master. `--drop <s>` silences the music for one beat (before a reveal); add hits for big moments.

## 4. Story that holds people
- **Hook in the first 2 seconds:** a question or a claim that makes them stay ("Top Gear tried to kill this truck.
  Five times."). Write 3–5 hook variants and pick the strongest.
- Then **3–5 beats, one fact per line**, each with its own shot and headline; then the **payoff**; then a short CTA.
- **Camera always moving** (orbit, dolly), **a cut on every line**.
- **Verify every fact** with a source before it goes in the script; never invent numbers.
- Write for the voice: numbers as words ("twenty three"), acronyms with dots when spelled ("A.P.K.").
- **Text-only videos (no voice):** hold each screen 0.4 s + 0.42 s per word + 0.5 s (typed text 24–28 characters/s).
  Compute it; don't shorten by eye. Viewers who can't read it in time leave.
- **Series beat one-offs:** a recurring format (a title pattern, a look, a hero) brings viewers back.
- **Mysteries / story series:** fair-play clues, the least-imaginable culprit, no "everyone did it", no suspect
  list in the questioning episode, nothing in the dialogue that gives the twist away, red herrings with innocent
  explanations.

## 5. Voice
- **Kokoro (English, local):** `am_michael` at 1.10–1.15 for energetic explainers; `af_heart` at 0.95–1.0 for
  warm product films. 0.35–0.6 s between lines, more before a big beat.
- **Arabic:** Kokoro has none, and the open multilingual cloners tested so far (Chatterbox, Habibi-TTS) sound
  wrong for Egyptian Arabic. Best path: the owner records the lines (phone is fine), you drop the WAVs in `out/`
  and run `vo.py --from-wavs`. Or text-only with the reading-time model above.
- Before saying you can't get a voice: search for current free TTS (edge-tts, Piper, newer Kokoro voices), try
  two, pick by ear (render a sample line each).

## 6. Learning a style
`staff-video <url>` on 2–3 reference videos: title, description (creators often name their tools, music and
voice there), tags, chapters, transcript, and key frames to look at. Write down: length, hook, cut rhythm, text
style and position, voice, music, colour. Then match it with the kit; say what you couldn't match and why.

## 7. Posting (needs "Acts in your browser" for that site)
- Work in the owner's own Chrome (they're signed in). Never sign in, type a password or change account settings.
- **YouTube Studio:** Create → Upload; title (the hook, under ~60 characters), description with 3–5 hashtags
  including #Shorts; not made for kids (unless it is); the **altered or synthetic content** label when visuals or
  voice are AI-made or heavily altered; Visibility → Schedule (the owner's best slots, e.g. 13:00 or 19:00 local).
  "You don't have permission" in Studio means the wrong Google account is active: avatar menu → Switch account.
- **TikTok Studio:** type the caption; finish hashtags with a space and press Escape; Post stays disabled until
  the upload reaches 100%; new posts sit in "under review / Only me" briefly, then go public.
- **Files over ~10 MB through the browser tools:** split into ~9.4 MB chunks, push each into a hidden file input,
  reassemble in page JS, check the SHA-256, then hand the result to the site's real input with a DataTransfer.
- Follow your grant: ask before each post, once per batch, or not at all ("Don't ask me"). Report every post
  with its link and time.

## 8. Growth and money (check the current numbers on the platform's own help pages)
- YouTube Partner Program: subscribers plus watch hours, or Shorts views over 90 days; the thresholds change, so
  read the official page before quoting them.
- Before monetization: affiliate links in descriptions (products shown in the video), a pinned comment, a series
  that brings viewers back, Shorts as the funnel to longer videos.
- After: sponsorships (prepare the pitch; the owner sends it unless you're granted email), your own products.
- Read the channel's public stats yourself (views, likes, upload dates) instead of asking for screenshots.
  Each standup: what you shipped, what the numbers say, today's plan, one new growth or money idea, what you need.

## 9. Before anything goes out (checklist)
- [ ] Original script and visuals (no re-uploaded clips: "reused content" blocks monetization).
- [ ] AI-made or heavily altered visuals or voice carry the platform's AI label.
- [ ] Every fact has a source in your notes.
- [ ] Title, description and thumbnail text fit the owner's brief and rules.
- [ ] Contact sheet checked: safe zone, no cut-off or overlapping text, readable, not washed out.
- [ ] Loudness about -14 LUFS (`ffmpeg -i final.mp4 -af ebur128 -f null -`).

## 10. Gotchas that cost hours
- Rendering is CPU: roughly 1–3 s per 3D frame. Render stills first (`render.js test`), then the full video.
- **Too much bloom washes everything out:** lower strength or raise threshold per scene. Dusty reds read pink:
  darken them.
- **A side-on subject doesn't fit 9:16:** use 3/4 angles and a wider field of view, or let the camera follow it.
- **Animated film grain makes huge files** (173 MB for 68 s); static grain: 24 MB.
- espeak-ng (the voice's phonemizer) can't read its data from a very long folder path; `vo.py` handles it.
- Delete files by explicit path; a shell guard may refuse `rm` with globs.
