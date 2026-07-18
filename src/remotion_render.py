"""Remotion renderer: the priority path for final assembly.

Stages the run's assets into the Remotion project's public dir, renders the
Short composition via npx, and cleans up after itself. assemble.build_video
calls this first and falls back to its ffmpeg path if the project is not
installed or the render fails, so unattended runs never depend on Node.

The project lives in <repo>/remotion by default; a deployment that shares one
install across channels can point REMOTION_DIR at it instead.
"""
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_dir() -> Path:
    env = os.getenv("REMOTION_DIR", "").strip()
    return Path(env) if env else ROOT / "remotion"


def available() -> bool:
    pd = project_dir()
    return (pd / "package.json").exists() and (pd / "node_modules").exists() \
        and shutil.which("npx") is not None


def _ass_color_to_hex(color: str, fallback: str) -> str:
    """ASS &HAABBGGRR (or &HBBGGRR) -> #rrggbb CSS hex."""
    try:
        s = "".join(c for c in str(color) if c in "0123456789abcdefABCDEF")
        s = s[-6:].zfill(6)  # BBGGRR
        return f"#{s[4:6]}{s[2:4]}{s[0:2]}"
    except Exception:
        return fallback


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def render(raw_clips: list, voice_mp3: Path, words: list, hook: str | None,
           config: dict, workdir: Path, out_file: Path,
           music: Path | None, logo: Path | None) -> Path:
    pd = project_dir()
    v = config["video"]
    cap = config.get("captions", {})
    td = float(v.get("transition_seconds", 0.35))
    total = _probe_duration(voice_mp3) + 0.6
    n = len(raw_clips)
    per_clip = (total + (n - 1) * td) / n

    stage = pd / "public" / f"run_{uuid.uuid4().hex[:8]}"
    stage.mkdir(parents=True, exist_ok=True)
    try:
        clips_rel = []
        for i, clip in enumerate(raw_clips):
            dest = stage / f"clip_{i}{Path(clip).suffix or '.mp4'}"
            shutil.copyfile(clip, dest)
            clips_rel.append(f"{stage.name}/{dest.name}")
        shutil.copyfile(voice_mp3, stage / "voice.mp3")
        if music:
            shutil.copyfile(music, stage / "music.mp3")
        if logo:
            shutil.copyfile(logo, stage / "logo.mp3")

        props = {
            "width": v["width"], "height": v["height"], "fps": v["fps"],
            "durationSec": round(total, 3),
            "clips": clips_rel,
            "clipSec": round(per_clip, 3),
            "transitionSec": td,
            "words": [{"word": w["word"], "start": round(w["start"], 3),
                       "end": round(w["end"], 3)} for w in words],
            "hook": hook,
            "captions": {
                "font": cap.get("font", "Arial Black"),
                "fontSize": int(cap.get("font_size", 88)),
                "wordsPerChunk": int(cap.get("words_per_chunk", 3)),
                "primary": _ass_color_to_hex(cap.get("primary_color", ""), "#ffffff"),
                "highlight": _ass_color_to_hex(cap.get("highlight_color", ""), "#FFD700"),
            },
            "voice": f"{stage.name}/voice.mp3",
            "music": f"{stage.name}/music.mp3" if music else None,
            "musicVolume": float(v.get("music_volume", 0.06)),
            "logo": f"{stage.name}/logo.mp3" if logo else None,
            "logoVolume": float(config.get("branding", {}).get("sonic_logo_volume", 0.5)),
        }
        props_file = workdir / "remotion_props.json"
        props_file.write_text(json.dumps(props), encoding="utf-8")

        npx = shutil.which("npx")
        proc = subprocess.run(
            [npx, "remotion", "render", "src/index.ts", "Short", str(out_file),
             "--props", str(props_file), "--codec", "h264"],
            cwd=pd, capture_output=True, text=True, timeout=1800,
            encoding="utf-8", errors="replace",  # progress bars are unicode
        )
        if proc.returncode != 0:
            raise RuntimeError(f"remotion render failed:\n{proc.stderr[-3000:]}")
        if not out_file.exists() or out_file.stat().st_size < 100_000:
            raise RuntimeError("remotion render produced no usable output file")
        return out_file
    finally:
        shutil.rmtree(stage, ignore_errors=True)
