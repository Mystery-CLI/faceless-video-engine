"""Weekly long-form countdown video — orchestrator.

Builds an 8-10 minute landscape countdown from little-known facts: each segment
(intro, items, outro) runs through the same engine as the daily Shorts, then the
segments are stitched with chapters, a music bed, and an auto-generated custom
thumbnail before uploading.

Usage:
  python run_weekly.py               # full run: generate + build + upload
  python run_weekly.py --no-upload   # build but don't upload
"""
import argparse
import copy
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from run_daily import OUT_DIR, cleanup, engage, log, recover_orphans  # noqa: E402
from src import assemble, captions, longform_gen, tts, visuals  # noqa: E402

FONT_CANDIDATES = [
    Path("C:/Windows/Fonts/ariblk.ttf"),   # Arial Black
    Path("C:/Windows/Fonts/arialbd.ttf"),  # Arial Bold
]


def _longform_config(config: dict) -> dict:
    """Derive a landscape config so the Shorts engine renders 16:9 segments."""
    lf = config.get("longform", {})
    cfg = copy.deepcopy(config)
    cfg["video"].update({
        "width": int(lf.get("width", 1920)),
        "height": int(lf.get("height", 1080)),
        "transition_seconds": 0.4,
    })
    cfg["captions"].update({
        "font_size": int(lf.get("font_size", 60)),
        "hook_font_size": int(lf.get("hook_font_size", 80)),
        "words_per_chunk": 4,
    })
    return cfg


def _probe(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _fmt_chapter(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _find_resumable() -> Path | None:
    """Long-form work dir whose run died before its video was rendered.

    Prefers the dir with the most finished segments (least work left), then the
    newest, so an almost-done build always wins over a barely-started one.
    """
    candidates = []
    for plan_path in (ROOT / "work").glob("*/plan.json"):
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "items" in plan and not (OUT_DIR / f"long_{plan_path.parent.name}.mp4").exists():
            built = len(list(plan_path.parent.glob("*/*.mp4")))
            candidates.append((built, plan_path.parent.name, plan_path.parent))
    if not candidates:
        return None
    return max(candidates)[2]


def _build_segment(name: str, script: str, terms: list, hook: str | None,
                   cfg: dict, workdir: Path, scene_prompts: list | None = None) -> Path:
    """One countdown segment = one mini video through the normal engine, no music."""
    seg_dir = workdir / name
    seg_dir.mkdir(parents=True, exist_ok=True)
    done = seg_dir / f"{name}.mp4"
    if done.exists():  # resume: an earlier interrupted run already built this one
        try:
            _probe(done)
            return done
        except Exception:
            pass
    voice = seg_dir / "voice.mp3"
    words = tts.make_voiceover(script, cfg, voice)
    duration = words[-1]["end"]
    ass_file = seg_dir / "subs.ass"
    captions.build_ass(words, cfg, ass_file, hook=hook)
    # Shorts-style pacing: a fresh clip roughly every 9-10 seconds, never a long
    # static shot. Terms repeat if needed; used_ids in visuals prevents dupes.
    n_clips = max(1, round(duration / 9.5))
    briefs = visuals.scene_prompt_list(terms, scene_prompts)
    terms = (list(terms) * ((n_clips // max(1, len(terms))) + 1))[:n_clips] if terms else []
    if briefs:  # cycled with the same formula so brief i still narrates clip i
        briefs = (briefs * ((n_clips // max(1, len(briefs))) + 1))[:n_clips]
    td = float(cfg["video"]["transition_seconds"])
    per_clip = (duration + 0.6 + (n_clips - 1) * td) / n_clips + 0.3
    clips = visuals.fetch_clips(terms[:n_clips], per_clip, cfg, seg_dir, ai_prompts=briefs)
    seg_out = seg_dir / f"{name}.mp4"
    # sonic logo plays once, under the intro's hook — not on every segment
    assemble.build_video(clips, voice, ass_file, cfg, seg_dir, seg_out,
                         with_music=False, with_logo=(name == "intro"),
                         words=words, hook=hook)
    return seg_out


def _concat_with_music(segments: list, cfg: dict, workdir: Path,
                       out_file: Path, music_mood: str | None) -> None:
    """Stitch segments, then lay one continuous quiet music bed under everything."""
    concat_list = workdir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    stitched = workdir / "stitched.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(stitched)],
        check=True, capture_output=True)

    music = assemble._pick_music(music_mood)
    if not music:
        stitched.replace(out_file)
        return
    vol = float(cfg["video"].get("music_volume", 0.06))
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(stitched), "-stream_loop", "-1", "-i", str(music),
         "-filter_complex",
         f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:"
         "dropout_transition=0:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         str(out_file)],
        check=True, capture_output=True)


def _make_thumbnail(video: Path, text: str, workdir: Path) -> Path | None:
    """Grab a clean frame and stamp the thumbnail text on it, brand gold on black."""
    font = next((f for f in FONT_CANDIDATES if f.exists()), None)
    if not font:
        return None
    thumb = workdir / "thumb.jpg"
    fontfile = str(font).replace("\\", "/").replace(":", "\\:")
    safe = text.upper().replace("\\", "").replace("'", "").replace(":", "\\:").replace('"', "")
    # balance onto two lines when long, and size the font so the widest line
    # fits the 1280px frame (Arial Black is roughly 0.78 * fontsize per char)
    words = safe.split()
    if len(safe) > 14 and len(words) > 1:
        best = min(range(1, len(words)),
                   key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    else:
        lines = [safe]
    widest = max(len(l) for l in lines)
    size = max(60, min(150, int(1150 / (0.78 * widest))))
    border = max(6, size // 14)
    # classic thumbnail composition: first line pinned top, second pinned bottom,
    # so the frame's subject stays visible in the middle
    positions = ["y=60"] if len(lines) == 1 else ["y=60", "y=h-text_h-60"]
    draws = []
    for line, ypos in zip(lines, positions):
        draws.append(
            f"drawtext=fontfile='{fontfile}':text='{line}':"
            f"fontcolor=0xF5A623:fontsize={size}:borderw={border}:bordercolor=black:"
            f"x=(w-text_w)/2:{ypos}"
        )
    draw = ",".join(draws)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "6", "-i", str(video),
         "-vf", f"scale=1280:720,eq=contrast=1.05:saturation=1.25,{draw}",
         "-frames:v", "1", "-q:v", "3", str(thumb)],
        check=True, capture_output=True)
    return thumb if thumb.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg = _longform_config(config)
    OUT_DIR.mkdir(exist_ok=True)

    try:
        if not args.no_upload:
            recover_orphans(config)

        resume_dir = _find_resumable()
        if resume_dir:
            workdir, stamp = resume_dir, resume_dir.name
            plan = json.loads((workdir / "plan.json").read_text(encoding="utf-8"))
            n = len(plan["items"])
            log(f"[LONG] 1/6 Resuming interrupted build {stamp} ({plan['theme']})")
        else:
            stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
            workdir = ROOT / "work" / stamp
            workdir.mkdir(parents=True, exist_ok=True)
            log("[LONG] 1/6 Generating countdown plan...")
            plan = longform_gen.generate_longform_plan(config)
            n = len(plan["items"])
            log(f"    theme: {plan['theme']} ({n} items)")
            log(f"    title: {plan['title']}")
            (workdir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        log("[LONG] 2/6 Building segments...")
        segments, chapters, cursor = [], [], 0.0
        parts = [("intro", plan["intro"], "Intro", plan["thumbnail_text"])]
        for i, item in enumerate(plan["items"]):
            rank = n - i
            parts.append((f"item_{rank}", item, f"#{rank} {item['name']}",
                          f"#{rank} {item['name']}"))
        parts.append(("outro", plan["outro"], "Outro", None))

        for name, part, chapter_label, hook in parts:
            seg = _build_segment(name, part["script"], part.get("search_terms", []),
                                 hook, cfg, workdir,
                                 scene_prompts=part.get("scene_prompts"))
            chapters.append(f"{_fmt_chapter(cursor)} {chapter_label}")
            cursor += _probe(seg)
            segments.append(seg)
            log(f"    segment done: {chapter_label} ({_fmt_chapter(cursor)} total)")

        log("[LONG] 3/6 Stitching + music bed...")
        out_file = OUT_DIR / f"long_{stamp}.mp4"
        _concat_with_music(segments, cfg, workdir, out_file, plan.get("music_mood"))
        log(f"    saved: {out_file} ({_fmt_chapter(_probe(out_file))})")

        if "Chapters:" not in plan["description"]:
            plan["description"] = plan["description"].rstrip() + "\n\nChapters:\n" + "\n".join(chapters)
        (workdir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        log("[LONG] 4/6 Generating thumbnail...")
        thumb = _make_thumbnail(segments[1] if len(segments) > 1 else out_file,
                                plan["thumbnail_text"], workdir)
        log(f"    thumbnail: {thumb if thumb else 'skipped (no font found)'}")

        url = None
        if args.no_upload or not config.get("upload", {}).get("enabled", True):
            log("[LONG] 5/6 Upload skipped (--no-upload or disabled in config).")
        else:
            log("[LONG] 5/6 Uploading to YouTube...")
            from src import upload
            url = upload.upload_video(out_file, plan, config, is_short=False)
            log(f"    LIVE: {url}")
            engage(url, plan)
            if thumb:
                try:
                    upload.set_thumbnail(url, thumb)
                    log("    custom thumbnail set.")
                except Exception as e:
                    log(f"    thumbnail skipped (channel not phone-verified?): {e}")

        longform_gen.save_history_entry({
            "date": f"{datetime.now():%Y-%m-%d}",
            "theme": plan["theme"],
            "title": plan["title"],
            "file": out_file.name,
            "url": url,
        })
        log("[LONG] 6/6 Cleaning up...")
        cleanup(workdir, out_file, uploaded=url is not None, config=config)
        log("Done (long-form).")
        return 0
    except Exception:
        log("[LONG] FAILED:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
