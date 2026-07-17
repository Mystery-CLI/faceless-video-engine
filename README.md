# Faceless Video Engine

An autonomous pipeline that produces and publishes a full faceless YouTube video every
day, and a long-form video every week, with no human in the loop after setup. Point it at
a niche in `config.json` and it writes, voices, illustrates, captions, renders, uploads,
and files the result, then repeats tomorrow.

It runs entirely on free tiers. It is niche-agnostic: the same code runs a psychology-facts
channel and a channel about financial censorship in Nigeria, with nothing different between
them but a config file.

> This is the engine behind **Proof of Necessity**, a channel explaining how centralized
> money and platforms control ordinary people, told from Nigeria. It is open source so any
> creator can run their own channel from it. If that is why you are here: the whole system
> is below, and everything channel-specific lives in one `config.json`.

---

## What one daily run does

```
topic  ─▶  script + metadata  ─▶  voiceover  ─▶  captions  ─▶  visuals  ─▶  render  ─▶  upload  ─▶  file & clean up
```

1. **Chooses a topic.** Brainstorms candidates in your niche, scores them, and writes only
   the best one. It reads a history of everything already covered so it never repeats, and
   it reads real audience retention data (once there is any) to steer toward what works.
2. **Writes the script and metadata.** Hook-first, length-controlled, with SEO title,
   description, tags, an engagement comment, and a playlist assignment. Editorial rules
   (what to cover, what to ban, the exact call-to-action) are configuration, not code.
3. **Voices it** with Microsoft Edge neural TTS (free), timed per word.
4. **Captions it** with animated word-by-word karaoke subtitles burned in by ffmpeg, plus
   a hook title card on the opening frame (which becomes the Shorts thumbnail).
5. **Illustrates it.** Generates unique AI visuals (Pollinations, keyless; Gemini as
   second choice) animated with Ken Burns motion, interleaved with Pexels stock footage at
   a configurable ratio, with a five-level fallback chain so a frame is never blank.
6. **Renders** the video with crossfades, a music bed, and an optional sonic-logo sting.
7. **Uploads** to YouTube with the AI-content disclosure set automatically, posts the
   engagement comment, and sorts the video into a themed playlist.
8. **Files and cleans up.** Records the upload in history and deletes local working files;
   finished videos live on YouTube, not on disk.

A separate weekly pipeline (`run_weekly.py`) builds long-form countdown videos through the
same engine, with chapters, an auto-generated thumbnail, and the week's best-performing
short seeded as the theme.

## Built to run unattended

The parts that matter when nobody is watching:

- **Crash recovery.** If a run dies between render and upload, the next run detects the
  stranded video, validates it, and uploads it.
- **No double-posting.** Once a day's video is live, every retry that day is a no-op, so
  the one-video-per-day rule cannot be broken by a restart.
- **Battery- and boot-safe.** The scheduled task survives the PC being asleep or on
  battery, and catches up when it can.
- **Never breaks on a missing signal.** No analytics data, a failed image service, a
  Pexels outage, a transient API 503: each degrades to a fallback instead of failing the
  run.
- **Analytics feedback loop.** Per-video views, retention, and subscribers gained flow
  back into topic selection as data accumulates.

---

## Setup

Needs **Python 3.11+** and **ffmpeg** on PATH.

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. API keys (both free, no card)
Copy `.env.example` to `.env` and fill in:

- **GEMINI_API_KEY**: https://aistudio.google.com/apikey. Scripts and topic selection.
- **PEXELS_API_KEY**: https://www.pexels.com/api/. Stock footage. Optional; without it the
  pipeline leans on generated visuals and the b-roll cache.
- **YOUTUBE_API_KEY**: optional, public-stats fallback for the analytics loop.

### 3. Configure your channel
Copy `config.example.json` to `config.json` and edit it. The example is fully commented;
at minimum set `niche` and `channel_persona`, then work through the rest as your channel
finds its identity (see *Making it your channel* below).

### 4. YouTube access (one time)
1. https://console.cloud.google.com/ → create a project.
2. APIs & Services → Library → enable **YouTube Data API v3**
   (and **YouTube Analytics API** for the feedback loop).
3. OAuth consent screen → External → add your Google account as a **test user**.
4. Credentials → Create credentials → **OAuth client ID** → **Desktop app** → download the
   JSON as `client_secret.json` in the project root.
5. `python authorize.py`. A browser opens; **sign in as the channel you want to publish
   to** and allow access. The consent screen will warn the app is unverified (it is your
   own app; that is expected): Advanced → Go to app → Allow.

> **Running more than one channel?** Each channel needs its own copy of the project folder
> with its own `config.json`, `client_secret.json`, and `token.json`. The consent screen
> does not tell you which channel you picked, so after `authorize.py` confirm it bound to
> the right one before scheduling. *(First-class multi-channel support via a `--profile`
> flag is on the roadmap.)*

### 5. Try it
```bash
python run_daily.py --no-upload   # build into output/ without uploading
python run_daily.py               # full run including upload
python run_weekly.py --no-upload  # build a long-form video
```

### 6. Schedule
```powershell
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1          # daily
powershell -ExecutionPolicy Bypass -File setup_schedule_weekly.ps1   # weekly
```

---

## Making it your channel

Everything channel-specific is in **`config.json`**, which you create by copying
`config.example.json`. No code changes.

| Key | Controls |
|---|---|
| `niche`, `channel_persona` | What the channel is about and how it sounds |
| `editorial` | The rules the AI writes under: exact call-to-action, banned topics, required stakes, hook examples, and `visual_direction` (what the visuals may and may not show) |
| `video.ai_style` | The house look of generated visuals; the single most important setting for a channel with a distinct visual identity |
| `video.ai_image_ratio` | Balance of AI-generated vs stock footage (0 = all stock, 1 = all AI) |
| `captions` | Fonts and colours, including the karaoke highlight |
| `playlists`, `upload` | Playlist names, tags, privacy, category |
| `schedule_time`, `longform` | When it runs; long-form length and cadence |

The `editorial` block is what makes one codebase serve unrelated channels: the topic rules,
the ban list, and the call-to-action are all data. Leave `editorial` out entirely and the
engine falls back to sensible defaults.

---

## YouTube policy notes

- **Uploads may start locked to private** on an unverified API project. Publish manually
  from Studio, or request an API audit to lift it.
- **One quality video per day.** Mass, repetitive uploads trigger YouTube's *inauthentic
  content* policy and can disqualify a channel from monetization. The engine enforces one
  per day by design.
- **AI disclosure is set automatically** (`containsSyntheticMedia`) because the voice is
  synthetic. Keep it accurate; AI-assisted educational content is monetizable, deceptive
  synthetic content is not.
- **Music:** only tracks you have rights to. The YouTube Audio Library is safe.

## Layout

| Path | Purpose |
|---|---|
| `run_daily.py` / `run_weekly.py` | The daily and weekly orchestrators |
| `src/script_gen.py`, `src/longform_gen.py` | Topic selection + writing; holds the editorial defaults |
| `src/tts.py`, `src/captions.py` | Voiceover and animated captions |
| `src/visuals.py`, `src/ai_images.py` | Stock footage and AI visuals |
| `src/assemble.py` | Final ffmpeg render |
| `src/upload.py`, `src/analytics.py` | YouTube upload and the retention feedback loop |
| `config.json` | Everything channel-specific |
| `data/` | History (prevents repeats) and cached analytics |

## License

MIT. Use it, fork it, run your own channel.
