"""Background clips: AI-generated scenes interleaved with Pexels stock (free).

Per search term, even slots get an AI-generated image animated with Ken Burns
motion (unique visuals no other channel has); odd slots and every AI failure
use the stock chain — a plain generated background is a last resort only:
  1. AI image -> Ken Burns clip (even slots, config video.ai_image_ratio)
  2. Pexels: the exact term (with network retries)
  3. Pexels: the term's first word (broader search)
  4. generic niche terms from config (video.fallback_search_terms)
  5. a random clip from the local b-roll cache (every download is saved there)
  6. generated animated gradient
"""
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

import requests

PEXELS_SEARCH = "https://api.pexels.com/videos/search"
BROLL_CACHE = Path(__file__).resolve().parent.parent / "assets" / "broll"


def _pexels_clip(query: str, api_key: str, out_path: Path, min_seconds: float,
                 used_ids: set, orientation: str = "portrait",
                 target_height: int = 1920) -> bool:
    resp = None
    for attempt in range(3):  # ride out transient DNS/network blips
        try:
            resp = requests.get(
                PEXELS_SEARCH,
                headers={"Authorization": api_key},
                params={"query": query, "orientation": orientation, "per_page": 15},
                timeout=60,
            )
            break
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(8)
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    random.shuffle(videos)
    for video in videos:
        if video.get("id") in used_ids:
            continue
        if video.get("duration", 0) < min_seconds:
            continue
        files = [f for f in video.get("video_files", []) if f.get("height") and f["height"] >= 1080]
        if not files:
            continue
        # closest to the canvas height: sharp without huge downloads
        files.sort(key=lambda f: abs(f["height"] - target_height))
        url = files[0]["link"]
        used_ids.add(video.get("id"))
        with requests.get(url, stream=True, timeout=180) as dl:
            dl.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        try:  # grow the local b-roll cache for days when the API is unreachable
            BROLL_CACHE.mkdir(parents=True, exist_ok=True)
            cached = BROLL_CACHE / f"pexels_{video.get('id')}.mp4"
            if not cached.exists():
                shutil.copyfile(out_path, cached)
        except OSError:
            pass
        return True
    return False


def _cache_clip(out_path: Path, used_cache: set) -> bool:
    clips = [p for p in sorted(BROLL_CACHE.glob("*.mp4")) if p.name not in used_cache]
    if not clips:
        return False
    pick = random.choice(clips)
    used_cache.add(pick.name)
    shutil.copyfile(pick, out_path)
    return True


def _gradient_clip(seconds: float, index: int, out_path: Path, width: int, height: int, fps: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"gradients=s={width}x{height}:d={seconds:.2f}:speed=0.05:seed={index * 7 + 1}",
            "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            str(out_path),
        ],
        check=True, capture_output=True,
    )


def fetch_clips(search_terms: list, seconds_each: float, config: dict, workdir: Path) -> list:
    """Return a list of raw clip paths, one per search term (order preserved)."""
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    video_cfg = config["video"]
    orientation = "portrait" if video_cfg["height"] > video_cfg["width"] else "landscape"
    fallback_terms = list(video_cfg.get("fallback_search_terms", []))
    random.shuffle(fallback_terms)
    paths = []
    used_ids: set = set()
    used_cache: set = set()
    ai_ratio = float(video_cfg.get("ai_image_ratio", 0.5))
    for i, term in enumerate(search_terms):
        out = workdir / f"raw_{i}.mp4"
        got = False
        if ai_ratio > 0 and i % max(1, round(1 / ai_ratio)) == 0:
            from . import ai_images
            img = workdir / f"ai_{i}.jpg"
            try:
                if ai_images.generate_scene_image(term, video_cfg["width"],
                                                  video_cfg["height"], img):
                    ai_images.ken_burns(img, seconds_each, video_cfg["width"],
                                        video_cfg["height"], video_cfg["fps"], out)
                    print(f"  AI-generated visual for '{term}'")
                    got = True
            except Exception as e:
                print(f"  AI visual failed for '{term}', using stock: {e}")
            finally:
                img.unlink(missing_ok=True)  # the clip is what we keep, not the still
        if not got and api_key:
            queries = [term, term.split()[0]] + fallback_terms
            for query in queries:
                try:
                    got = _pexels_clip(query, api_key, out, seconds_each, used_ids,
                                       orientation, video_cfg["height"])
                except Exception as e:
                    print(f"  Pexels failed for '{query}': {e}")
                if got:
                    break
        if not got and _cache_clip(out, used_cache):
            print(f"  Using cached b-roll for '{term}'")
            got = True
        if not got:
            print(f"  Using generated background for '{term}' (last resort)")
            _gradient_clip(seconds_each, i, out, video_cfg["width"], video_cfg["height"], video_cfg["fps"])
        paths.append(out)
    return paths
