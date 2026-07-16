"""Daily YouTube Shorts automation — orchestrator.

Usage:
  python run_daily.py                 # full run: generate + build + upload
  python run_daily.py --no-upload     # build the video but don't upload
  python run_daily.py --topic "..."   # force a specific topic
  python run_daily.py --plan-file p.json  # skip AI, use a prepared plan (testing)
  python run_daily.py --recover-only  # only upload videos stranded by a crashed run
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from src import assemble, captions, script_gen, tts, visuals  # noqa: E402

LOG_DIR = ROOT / "logs"
OUT_DIR = ROOT / "output"
BROLL_DIR = ROOT / "assets" / "broll"


def _pending_upload(video: Path) -> bool:
    """True if this video is still waiting to reach YouTube (recovery will send it)."""
    stamp = video.stem.split("_", 1)[-1]
    return (ROOT / "work" / stamp / "plan.json").exists()


def cleanup(current_workdir: Path, out_file: Path, uploaded: bool, config: dict) -> None:
    """Delete everything the pipeline created that is no longer needed.

    Policy: nothing is kept locally. Finished videos live on YouTube, stock clips
    live on Pexels. The ONLY thing spared is a video that hasn't reached YouTube
    yet (crash recovery uploads it on the next run, then deletes it).
    """
    # temp working files (clips, audio, subtitles) — always
    shutil.rmtree(current_workdir, ignore_errors=True)
    # the local copy of an uploaded video — it lives on YouTube now
    if uploaded and out_file.exists():
        out_file.unlink()
    # local builds: delete everything except videos still pending upload
    keep = int(config.get("cleanup", {}).get("keep_local_videos", 0))
    videos = sorted(OUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in videos[keep:]:
        if old == out_file and not uploaded:
            continue  # a --no-upload build survives its own run; the next run sweeps it
        if not _pending_upload(old):
            old.unlink(missing_ok=True)
    # leftover work dirs from crashed runs — spare only those backing a pending video
    work_root = ROOT / "work"
    if work_root.exists():
        for leftover in work_root.iterdir():
            if leftover == current_workdir:
                continue
            stamp = leftover.name
            # a work dir touched within the last few hours may belong to a run
            # that is still rendering (daily + weekly catch-up can start together
            # after a boot); a genuinely crashed dir is swept by a later run
            try:
                if time.time() - leftover.stat().st_mtime < 6 * 3600:
                    continue
            except OSError:
                pass
            pending = any((OUT_DIR / f"{p}_{stamp}.mp4").exists() for p in ("short", "long"))
            if not pending:
                shutil.rmtree(leftover, ignore_errors=True)
        for husk in work_root.iterdir():  # OneDrive can leave locked empty shells
            try:
                husk.rmdir()
            except OSError:
                pass
    # cap the b-roll fallback cache (newest clips kept; only exists so a Pexels
    # outage never produces a blank-screen video)
    cap_mb = int(config.get("cleanup", {}).get("broll_cache_mb", 150))
    total = 0
    if BROLL_DIR.exists():
        for clip in sorted(BROLL_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            total += clip.stat().st_size
            if total > cap_mb * 1024 * 1024:
                clip.unlink(missing_ok=True)


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / f"{datetime.now():%Y-%m}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _video_ok(path: Path) -> bool:
    """ffprobe sanity check so a half-written file is never uploaded."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and float(r.stdout.strip()) >= 10
    except Exception:
        return False


def engage(url: str, plan: dict) -> None:
    """Post the engagement comment and sort into a themed playlist.
    Both are best-effort growth boosters — a failure never touches the run."""
    from src import upload
    try:
        if plan.get("comment") and upload.post_comment(url, plan["comment"]):
            log(f"    comment posted: {plan['comment'][:60]}")
    except Exception as e:
        log(f"    comment failed (non-fatal): {e}")
    try:
        if plan.get("playlist") and upload.add_to_playlist(url, plan["playlist"]):
            log(f"    added to playlist: {plan['playlist']}")
    except Exception as e:
        log(f"    playlist failed (non-fatal): {e}")


def recover_orphans(config: dict) -> None:
    """Finish the job for any earlier run that died between render and upload.

    A crashed run leaves two things behind: the finished mp4 in output/ and its
    work/<stamp>/plan.json (cleanup only runs after a successful upload). That
    pair is the signature of an orphan; test builds get their work dir cleaned,
    so they are never picked up here.
    """
    if not config.get("upload", {}).get("enabled", True):
        return
    for video in sorted(list(OUT_DIR.glob("short_*.mp4")) + list(OUT_DIR.glob("long_*.mp4"))):
        is_short = video.name.startswith("short_")
        stamp = video.stem.split("_", 1)[1]
        plan_path = ROOT / "work" / stamp / "plan.json"
        if not plan_path.exists():
            continue
        try:
            if not _video_ok(video):
                log(f"Recovery: {video.name} is incomplete, deleting it.")
                video.unlink(missing_ok=True)
                shutil.rmtree(plan_path.parent, ignore_errors=True)
                continue
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            label = plan.get("topic") or plan.get("theme")
            log(f"Recovery: uploading stranded video {video.name} ({label})...")
            from src import upload
            url = upload.upload_video(video, plan, config, is_short=is_short)
            log(f"    LIVE: {url}")
            engage(url, plan)
            thumb = plan_path.parent / "thumb.jpg"
            if not is_short and thumb.exists():
                try:
                    upload.set_thumbnail(url, thumb)
                except Exception as e:
                    log(f"    thumbnail skipped: {e}")
            entry = {
                "date": f"{datetime.now():%Y-%m-%d}",
                "title": plan["title"],
                "file": video.name,
                "url": url,
            }
            if is_short:
                script_gen.save_history_entry({**entry, "topic": plan["topic"]})
            else:
                from src import longform_gen
                longform_gen.save_history_entry({**entry, "theme": plan["theme"]})
            video.unlink(missing_ok=True)
            shutil.rmtree(plan_path.parent, ignore_errors=True)
        except Exception:
            log("Recovery failed for " + video.name + ":\n" + traceback.format_exc())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--plan-file", default=None)
    parser.add_argument("--recover-only", action="store_true")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    # pick up anything a crashed run left behind before (or instead of) a new run
    if args.recover_only:
        recover_orphans(config)
        log("Recovery pass finished.")
        return 0
    if not args.no_upload and not args.plan_file:
        recover_orphans(config)
        # Grace-period retries fire this task repeatedly; once today's video is
        # live (fresh upload or recovery), every later attempt is a no-op so the
        # one-quality-video-per-day rule can never be broken.
        today = f"{datetime.now():%Y-%m-%d}"
        if not args.topic and any(
            h.get("date") == today and h.get("url") for h in script_gen.load_history()
        ):
            log("Today's Short is already live — nothing to do.")
            return 0

    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    workdir = ROOT / "work" / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)

    try:
        log("1/6 Generating topic + script...")
        if args.plan_file:
            plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        else:
            plan = script_gen.generate_video_plan(config, forced_topic=args.topic)
        log(f"    topic: {plan['topic']}")
        log(f"    title: {plan['title']}")
        (workdir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        log("2/6 Creating voiceover (edge-tts)...")
        voice_mp3 = workdir / "voice.mp3"
        words = tts.make_voiceover(plan["script"], config, voice_mp3)
        duration = words[-1]["end"]
        log(f"    {len(words)} words, {duration:.1f}s")

        log("3/6 Building captions...")
        ass_file = workdir / "subs.ass"
        # thumbnail-frame text: the hook, or the title when the hook runs long
        hook = plan["script"].split(".")[0].split("?")[0].strip()
        if len(hook.split()) > 12:
            hook = plan["title"].replace("#Shorts", "").strip()
        captions.build_ass(words, config, ass_file, hook=hook)

        log("4/6 Fetching background clips...")
        n_clips = config["video"].get("clips_count", 5)
        td = float(config["video"].get("transition_seconds", 0.35))
        terms = (plan["search_terms"] * n_clips)[:n_clips]
        # clips overlap during crossfades, so each must be slightly longer (+ margin)
        per_clip = (duration + 0.6 + (n_clips - 1) * td) / n_clips + 0.3
        clips = visuals.fetch_clips(terms, per_clip, config, workdir)

        log("5/6 Assembling video (ffmpeg)...")
        out_file = OUT_DIR / f"short_{stamp}.mp4"
        assemble.build_video(clips, voice_mp3, ass_file, config, workdir, out_file,
                             music_mood=plan.get("music_mood"))
        log(f"    saved: {out_file}")

        url = None
        if args.no_upload or not config.get("upload", {}).get("enabled", True):
            log("6/6 Upload skipped (--no-upload or disabled in config).")
        else:
            log("6/6 Uploading to YouTube...")
            from src import upload
            url = upload.upload_video(out_file, plan, config)
            log(f"    LIVE: {url}")
            engage(url, plan)

        script_gen.save_history_entry({
            "date": f"{datetime.now():%Y-%m-%d}",
            "topic": plan["topic"],
            "title": plan["title"],
            "file": out_file.name,
            "url": url,
        })
        cleanup(workdir, out_file, uploaded=url is not None, config=config)
        log("Done (temp files cleaned).")
        return 0
    except Exception:
        log("FAILED:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
