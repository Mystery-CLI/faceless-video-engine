"""Voiceover via Microsoft Edge neural TTS (free), with emotional pacing.

The script is synthesized sentence-by-sentence with varied rate/pitch so the
delivery has energy and never drones:
  - hook (1st sentence): faster + brighter, followed by a dramatic pause
  - body: gentle pitch alternation between sentences
  - twist (2nd-to-last): slower + lower, preceded by a pause
  - CTA (last): upbeat
Word timings are collected per sentence and shifted onto the final timeline
so captions stay perfectly synced.
"""
import asyncio
import re
import subprocess
import time
from pathlib import Path

import edge_tts


def _split_sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _fmt_rate(base: str, delta: int) -> str:
    val = int(base.replace("%", "").replace("+", "")) + delta
    return f"{val:+d}%"


def _plan_prosody(n: int, base_rate: str) -> list:
    """Return per-sentence (rate, pitch, pre_pause_seconds)."""
    plan = []
    for i in range(n):
        if i == 0:  # hook: energetic
            plan.append((_fmt_rate(base_rate, 6), "+6Hz", 0.0))
        elif n >= 3 and i == n - 1:  # CTA: upbeat
            plan.append((_fmt_rate(base_rate, 4), "+8Hz", 0.20))
        elif n >= 3 and i == n - 2:  # twist: slower, lower, dramatic pause before
            plan.append((_fmt_rate(base_rate, -6), "-4Hz", 0.30))
        else:  # body: subtle alternation so it never drones
            pitch = "+3Hz" if i % 2 else "-2Hz"
            plan.append((_fmt_rate(base_rate, 0), pitch, 0.35 if i == 1 else 0.0))
    return plan


async def _synth(text: str, voice: str, rate: str, pitch: str, out_path: Path) -> list:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch,
                                       boundary="WordBoundary")
    words = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "word": chunk["text"],
                    "start": chunk["offset"] / 10_000_000,
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                })
    if not words:
        raise RuntimeError(f"TTS produced no word timings for: {text[:60]}")
    return words


def _synth_with_retry(text: str, voice: str, rate: str, pitch: str,
                      out_path: Path, attempts: int = 4) -> list:
    """edge-tts occasionally returns no audio for a perfectly fine sentence;
    a patient backoff and retry rides out both glitches and short outages."""
    last = None
    for attempt in range(attempts):
        try:
            return asyncio.run(_synth(text, voice, rate, pitch, out_path))
        except Exception as e:
            last = e
            time.sleep(6 * (attempt + 1))
    raise last


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _silence(seconds: float, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds:.2f}", "-c:a", "libmp3lame", "-b:a", "48k", str(out_path)],
        check=True, capture_output=True,
    )


def make_voiceover(text: str, config: dict, out_mp3: Path) -> list:
    """Generate out_mp3 and return [{word, start, end}, ...] timings in seconds."""
    tts_cfg = config.get("tts", {})
    voice = tts_cfg.get("voice", "en-US-AndrewMultilingualNeural")
    base_rate = tts_cfg.get("rate", "+8%")
    workdir = out_mp3.parent

    # drop "sentences" with nothing speakable (bare numbers-only lines are kept;
    # pure punctuation would make edge-tts return no audio)
    sentences = [s for s in _split_sentences(text) if re.search(r"[A-Za-z0-9]", s)]
    if not tts_cfg.get("dynamic", True) or len(sentences) < 3:
        words = _synth_with_retry(text, voice, base_rate, "+0Hz", out_mp3)
        return words

    prosody = _plan_prosody(len(sentences), base_rate)
    all_words, concat_entries, cursor = [], [], 0.0
    for i, (sentence, (rate, pitch, pre_pause)) in enumerate(zip(sentences, prosody)):
        if pre_pause > 0:
            sil = workdir / f"sil_{i}.mp3"
            _silence(pre_pause, sil)
            concat_entries.append(sil)
            cursor += pre_pause
        seg = workdir / f"seg_{i}.mp3"
        seg_words = _synth_with_retry(sentence, voice, rate, pitch, seg)
        for w in seg_words:
            all_words.append({"word": w["word"], "start": w["start"] + cursor,
                              "end": w["end"] + cursor})
        concat_entries.append(seg)
        cursor += _duration(seg)

    concat_list = workdir / "voice_concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.name}'\n" for p in concat_entries), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:a", "libmp3lame", "-b:a", "96k", str(out_mp3)],
        check=True, capture_output=True, cwd=workdir,
    )
    return all_words
