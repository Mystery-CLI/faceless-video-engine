# YouTube Shorts Daily Automation

Fully automated faceless-Shorts pipeline. Every day it:

1. Picks a fresh viral topic in your niche (avoids everything already covered)
2. Writes a hook-driven ~45s script + SEO title/description/tags (AI)
3. Generates a natural voiceover (free Microsoft Edge neural TTS)
4. Downloads matching vertical stock clips (Pexels, free)
5. Assembles the video with animated word-by-word captions (ffmpeg)
6. Uploads it to your YouTube channel

Niche, voice, caption style, video length, and schedule are all in `config.json`.

---

## Setup (one time, ~15 minutes)

### 1. Install dependencies
```powershell
pip install -r requirements.txt
```
(Python and ffmpeg are already installed on this PC.)

### 2. Free API keys
Copy `.env.example` to `.env`, then fill in:

- **GEMINI_API_KEY** — https://aistudio.google.com/apikey → "Create API key". Free, no card.
  (Without it the script falls back to a keyless free AI service, but Gemini is more reliable.)
- **PEXELS_API_KEY** — https://www.pexels.com/api/ → sign up → key is shown instantly. Free.
  (Without it, videos get generated gradient backgrounds — fine for testing, bad for retention.)

### 3. YouTube upload setup
1. Go to https://console.cloud.google.com/ → create a project (any name).
2. "APIs & Services" → "Library" → enable **YouTube Data API v3**.
3. "APIs & Services" → "OAuth consent screen" → External → fill app name/email →
   add your own Gmail as a **test user**.
4. "Credentials" → "Create credentials" → **OAuth client ID** → type **Desktop app** →
   download the JSON → save it in this folder as `client_secret.json`.
5. Run `python authorize.py` — a browser opens, sign in with the Google account that
   owns your channel, allow access. Done; it never asks again.

### 4. Test it
```powershell
python run_daily.py --no-upload   # builds a video into output\ without uploading
python run_daily.py               # full run including upload
```

### 5. Schedule daily runs
```powershell
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
```
Runs daily at the time in `config.json` (`schedule_time`). If the PC was off,
it catches up when it next boots. Your PC must be on (not asleep) for it to run.

---

## Important: YouTube policy & monetization notes

- **API uploads may be locked to private at first.** Google restricts uploads from
  unverified API projects. If your uploads land as private: publish them manually from
  YouTube Studio (takes 2 clicks), and apply for an API audit in the Cloud Console to
  lift the restriction. Alternatively set `"privacy": "private"` in config and treat
  the automation as a "video factory" you approve each morning.
- **Monetization thresholds (YouTube Partner Program):** 1,000 subscribers AND either
  4,000 public watch hours (12 months) or **10M Shorts views (90 days)**. Shorts ads
  revenue is shared at 45% to creators.
- **Do not run more than 1 video/day at the start.** Mass-produced repetitive uploads
  trigger YouTube's *inauthentic content* policy and can permanently disqualify the
  channel from monetization. Quality and consistency beat volume.
- **Add disclosure.** In YouTube Studio, when videos use AI voice/visuals, keep the
  "altered content" disclosure accurate. AI-assisted educational content is allowed
  and monetizable; deceptive synthetic content is not.
- **Music:** drop royalty-free `.mp3` files into `assets\music\` and one is picked at
  random as a low-volume bed. Only use tracks you have rights to (YouTube Audio Library
  is safe: https://studio.youtube.com → Audio Library).

## Files

| File | Purpose |
|---|---|
| `config.json` | Niche, persona, voice, captions, schedule — edit freely |
| `run_daily.py` | The daily pipeline (`--no-upload`, `--topic "..."`) |
| `authorize.py` | One-time YouTube sign-in |
| `setup_schedule.ps1` | Registers the Windows daily task |
| `data/topics_history.json` | Everything already covered (prevents repeats) |
| `output/` | Finished videos |
| `logs/` | Run logs (check here if a day fails) |
