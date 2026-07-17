"""AI-generated scene images (free tiers) turned into Ken Burns motion clips.

Source order: Pollinations (keyless) then Gemini image model (existing API key).
Any failure returns False and the caller falls back to stock footage, so this
layer can never break a build. Generated images live in the run's workdir and
die with it — nothing is kept.
"""
import base64
import os
import random
import subprocess
import time
import urllib.parse
from pathlib import Path

import requests

# House look for generated visuals. A channel whose identity depends on where the
# footage appears to be shot overrides this with config video.ai_style — the search
# term itself cannot carry that, because the same term is also a Pexels query and
# Pexels has little footage outside the usual Western defaults.
DEFAULT_STYLE = ("cinematic photograph, moody dramatic lighting, shallow depth of field, "
                 "photorealistic, high detail, no text, no words, no watermark")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
GEMINI_IMAGE_MODELS = ["gemini-2.5-flash-image"]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _valid_image(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 20_000:
        return False
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() != ""


def _pollinations(prompt: str, w: int, h: int, out_path: Path) -> bool:
    url = POLLINATIONS_URL.format(prompt=urllib.parse.quote(prompt))
    for _ in range(2):
        try:
            resp = requests.get(
                url,
                params={"width": w, "height": h, "nologo": "true",
                        "seed": random.randint(1, 10 ** 9), "model": "flux"},
                timeout=120)
            if resp.ok and resp.headers.get("content-type", "").startswith("image/"):
                out_path.write_bytes(resp.content)
                if _valid_image(out_path):
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _gemini(prompt: str, w: int, h: int, out_path: Path) -> bool:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False
    ratio = "9:16" if h > w else "16:9"
    for model in GEMINI_IMAGE_MODELS:
        try:
            resp = requests.post(
                GEMINI_URL.format(model=model),
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": f"Generate a single image, aspect ratio {ratio}: {prompt}"}]}],
                    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
                },
                timeout=120)
            if not resp.ok:
                continue
            for part in resp.json()["candidates"][0]["content"]["parts"]:
                data = part.get("inlineData", {}).get("data")
                if data:
                    out_path.write_bytes(base64.b64decode(data))
                    if _valid_image(out_path):
                        return True
        except Exception:
            continue
    return False


def generate_scene_image(term: str, w: int, h: int, out_path: Path,
                         style: str | None = None) -> bool:
    prompt = f"{term}, {style or DEFAULT_STYLE}"
    return _pollinations(prompt, w, h, out_path) or _gemini(prompt, w, h, out_path)


def ken_burns(image: Path, seconds: float, w: int, h: int, fps: int, out_path: Path) -> None:
    """Animate a still image with a slow zoom and drift so it feels like footage."""
    frames = max(1, round(seconds * fps))
    z = f"1+0.12*on/{frames}" if random.random() < 0.5 else f"1.12-0.12*on/{frames}"
    drift = random.choice([
        "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*0.35'",
        f"x='(iw-iw/zoom)*on/{frames}':y='(ih-ih/zoom)/2'",
        f"x='(iw-iw/zoom)*(1-on/{frames})':y='(ih-ih/zoom)/2'",
        "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'",
    ])
    # free tiers return ~1024px images; lanczos + gentle unsharp keeps the
    # upscale crisp on phone screens before the zoom crops into it
    vf = (f"scale={w * 2}:{h * 2}:flags=lanczos,unsharp=5:5:0.6:5:5:0.0,"
          f"zoompan=z='{z}':{drift}:d={frames}:s={w}x{h}:fps={fps}")
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-vf", vf,
         "-frames:v", str(frames), "-c:v", "libx264", "-preset", "fast", "-crf", "22",
         "-pix_fmt", "yuv420p", str(out_path)],
        check=True, capture_output=True)
