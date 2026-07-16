"""Assemble the final Short with ffmpeg: normalize clips, concat, burn captions, mix audio."""
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_MUSIC = ROOT / "assets" / "music"


def _brand_logo(config: dict) -> Path | None:
    """The channel's sonic signature, if configured and present."""
    rel = config.get("branding", {}).get("sonic_logo")
    if not rel:
        return None
    p = ROOT / rel
    return p if p.exists() else None


def _run(args: list, cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({' '.join(args[:6])}...):\n{proc.stderr[-3000:]}")


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())


def _pick_music(mood: str | None) -> Path | None:
    """Prefer a track from assets/music/<mood>/, fall back to any mp3 in assets/music."""
    if not ASSETS_MUSIC.exists():
        return None
    if mood:
        mood_tracks = sorted((ASSETS_MUSIC / mood.strip().lower()).glob("*.mp3"))
        if mood_tracks:
            return random.choice(mood_tracks)
    any_tracks = sorted(ASSETS_MUSIC.rglob("*.mp3"))
    return random.choice(any_tracks) if any_tracks else None


# subtle, professional transition styles (xfade)
TRANSITIONS = ["fade", "fade", "smoothleft", "smoothright", "smoothup", "circleopen"]


def build_video(raw_clips: list, voice_mp3: Path, ass_file: Path, config: dict,
                workdir: Path, out_file: Path, music_mood: str | None = None,
                with_music: bool = True, with_logo: bool = True) -> Path:
    v = config["video"]
    w, h, fps = v["width"], v["height"], v["fps"]
    td = float(v.get("transition_seconds", 0.35))
    music_vol = float(v.get("music_volume", 0.06))
    logo_vol = float(config.get("branding", {}).get("sonic_logo_volume", 0.5))
    audio_len = _probe_duration(voice_mp3)
    total = audio_len + 0.6  # small tail so the last word isn't clipped
    n = len(raw_clips)
    # clips overlap during each crossfade, so each must be a little longer
    per_clip = (total + (n - 1) * td) / n

    # 1. Normalize every clip to identical codec/size/fps.
    norm_paths = []
    for i, raw in enumerate(raw_clips):
        norm = workdir / f"norm_{i}.mp4"
        _run([
            "ffmpeg", "-y", "-i", str(raw), "-t", f"{per_clip:.3f}",
            "-vf",
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", str(norm),
        ], workdir)
        norm_paths.append(norm)

    # 2. One pass: crossfade chain + burn captions + mix audio.
    music = _pick_music(music_mood) if with_music else None
    logo = _brand_logo(config) if with_logo else None
    args = ["ffmpeg", "-y"]
    for p in norm_paths:
        args += ["-i", p.name]
    voice_idx = n
    args += ["-i", str(voice_mp3)]
    next_idx = voice_idx + 1
    music_idx = logo_idx = None
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        music_idx = next_idx
        next_idx += 1
    if logo:
        args += ["-i", str(logo)]  # short; plays once under the opening hook
        logo_idx = next_idx
        next_idx += 1

    filters = []
    if n == 1:
        filters.append(f"[0:v]ass={ass_file.name}[v]")
    else:
        prev = "[0:v]"
        for i in range(1, n):
            trans = random.choice(TRANSITIONS)
            offset = i * (per_clip - td)
            label = f"[x{i}]" if i < n - 1 else "[xv]"
            filters.append(
                f"{prev}[{i}:v]xfade=transition={trans}:duration={td:.3f}:offset={offset:.3f}{label}"
            )
            prev = label
        filters.append(f"[xv]ass={ass_file.name}[v]")

    # Layer the audio: voice at full loudness, music quiet underneath, and the
    # sonic logo playing once at the very start (under the hook). normalize=0
    # keeps the voice from being ducked by the mix.
    mix_sources = [f"[{voice_idx}:a]"]
    if music:
        filters.append(f"[{music_idx}:a]volume={music_vol}[m]")
        mix_sources.append("[m]")
    if logo:
        filters.append(f"[{logo_idx}:a]volume={logo_vol}[l]")
        mix_sources.append("[l]")
    if len(mix_sources) > 1:
        filters.append(
            f"{''.join(mix_sources)}amix=inputs={len(mix_sources)}:"
            "duration=first:dropout_transition=0:normalize=0[a]")
        audio_map = "[a]"
    else:
        audio_map = f"{voice_idx}:a"

    args += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", audio_map,
             "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", str(out_file)]
    _run(args, workdir)
    return out_file
