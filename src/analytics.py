"""Per-video YouTube performance -> a feedback signal for daily topic selection.

Preferred source is the YouTube Analytics API (views, avg % viewed, subs gained
per video), which needs the yt-analytics.readonly scope — run `python authorize.py`
once to grant it. Falls back to public view/like counts via an optional
YOUTUBE_API_KEY in .env, and degrades to "(no data)" without ever breaking the
daily run.
"""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "token.json"
CACHE_FILE = ROOT / "data" / "performance.json"
CACHE_HOURS = 12
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _history_videos() -> list:
    """Uploaded Shorts from topics_history.json (entries that actually went live)."""
    from . import script_gen
    videos = []
    for h in script_gen.load_history():
        url = h.get("url") or ""
        if "/shorts/" in url:
            videos.append({
                "id": url.rstrip("/").rsplit("/", 1)[-1],
                "topic": h.get("topic", "?"),
                "date": h.get("date"),
            })
    return videos


def _analytics_creds():
    """Non-interactive credentials for the Analytics API, or None if the stored
    grant doesn't cover it (never opens a browser — the daily run is unattended)."""
    if not TOKEN_FILE.exists():
        return None
    info = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    if ANALYTICS_SCOPE not in (info.get("scopes") or []):
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds if creds.valid else None


def _fetch_analytics(videos: list) -> dict | None:
    creds = _analytics_creds()
    if creds is None:
        return None
    from googleapiclient.discovery import build
    yt = build("youtubeAnalytics", "v2", credentials=creds)
    start = min((v["date"] for v in videos if v.get("date")), default="2026-01-01")
    resp = yt.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=date.today().isoformat(),
        metrics="views,likes,averageViewPercentage,subscribersGained",
        dimensions="video",
        filters="video==" + ",".join(v["id"] for v in videos[:200]),
        maxResults=200,
    ).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    stats = {}
    for row in resp.get("rows") or []:
        d = dict(zip(cols, row))
        stats[d["video"]] = {
            "views": int(d.get("views", 0)),
            "likes": int(d.get("likes", 0)),
            "avg_pct": round(float(d.get("averageViewPercentage", 0)), 1),
            "subs": int(d.get("subscribersGained", 0)),
        }
    return stats


def _fetch_public(videos: list) -> dict | None:
    """Public view/like counts via API key — weaker signal, no OAuth needed."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return None
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", developerKey=key)
    resp = yt.videos().list(
        part="statistics", id=",".join(v["id"] for v in videos[:50])
    ).execute()
    stats = {}
    for item in resp.get("items", []):
        s = item.get("statistics", {})
        stats[item["id"]] = {
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
        }
    return stats


def _fetch_retention(video_id: str, creds) -> dict | None:
    """Second-by-second drop-off curve -> two numbers the prompt can act on:
    how well the hook holds, and where half the audience is gone."""
    from googleapiclient.discovery import build
    yt = build("youtubeAnalytics", "v2", credentials=creds)
    resp = yt.reports().query(
        ids="channel==MINE",
        startDate="2026-01-01",
        endDate=date.today().isoformat(),
        metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio",
        filters=f"video=={video_id}",
    ).execute()
    rows = resp.get("rows") or []
    if not rows:
        return None
    hook_hold = next((w for r, w in rows if r >= 0.05), None)
    half_gone = next((r for r, w in rows if w < 0.5), None)
    return {
        "hook_hold_pct": round(hook_hold * 100) if hook_hold is not None else None,
        "half_gone_pct": round(half_gone * 100) if half_gone is not None else None,
    }


def _fetch_scrape(videos: list) -> dict | None:
    """Last resort, zero credentials: read the public view count off the watch
    page HTML. Fragile by nature, so any miss just returns what it got."""
    import re
    import requests
    stats = {}
    for v in videos[:20]:
        try:
            html = requests.get(
                f"https://www.youtube.com/watch?v={v['id']}",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
            ).text
            m = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
            if m:
                stats[v["id"]] = {"views": int(m.group(1))}
        except Exception:
            continue
    return stats or None


def get_performance(force: bool = False) -> dict | None:
    """Fetch (or reuse cached) per-video stats. Returns None when no source works."""
    cache = None
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            cache = None
    if cache and not force:
        age = datetime.now() - datetime.fromisoformat(cache["fetched_at"])
        if age < timedelta(hours=CACHE_HOURS):
            return cache

    videos = _history_videos()
    if not videos:
        return cache
    stats = None
    for fetch in (_fetch_analytics, _fetch_public, _fetch_scrape):
        try:
            stats = fetch(videos)
        except Exception as exc:
            print(f"    performance fetch failed ({fetch.__name__}): {exc}")
        if stats:  # empty results fall through to the next source
            break
    if not stats:
        return cache  # stale data beats no data; None if there never was any

    fresh = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "videos": [{**v, **stats[v["id"]]} for v in videos if v["id"] in stats],
    }
    # retention curves for the newest few videos (only possible via OAuth analytics)
    try:
        creds = _analytics_creds()
        if creds is not None:
            for v in fresh["videos"][-3:]:
                ret = _fetch_retention(v["id"], creds)
                if ret:
                    v["retention"] = ret
    except Exception as exc:
        print(f"    retention fetch skipped: {exc}")
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(fresh, indent=2), encoding="utf-8")
    return fresh


def performance_block() -> str:
    """Human-readable performance summary for the script-writing prompt."""
    try:
        data = get_performance()
    except Exception as exc:
        print(f"    performance signal skipped: {exc}")
        data = None
    if not data or not data.get("videos"):
        return "(no performance data yet — pick purely on the scoring rules)"

    today = date.today()
    scored = []
    for v in data["videos"]:
        try:
            age = max((today - date.fromisoformat(v["date"])).days, 1)
        except Exception:
            age = 1
        scored.append((v.get("views", 0) / age, age, v))
    scored.sort(key=lambda t: t[0], reverse=True)

    def fmt(vpd: float, age: int, v: dict) -> str:
        bits = [f"{v.get('views', 0)} views ({vpd:.0f}/day, {age}d old)"]
        if "avg_pct" in v:
            bits.append(f"{v['avg_pct']}% avg watched")
        if "likes" in v:
            bits.append(f"{v['likes']} likes")
        if "subs" in v:
            bits.append(f"+{v['subs']} subs")
        ret = v.get("retention") or {}
        if ret.get("hook_hold_pct") is not None:
            bits.append(f"hook holds {ret['hook_hold_pct']}% of viewers")
        if ret.get("half_gone_pct") is not None:
            bits.append(f"half the audience gone by {ret['half_gone_pct']}% mark")
        return f"- \"{v['topic']}\": " + ", ".join(bits)

    if len(scored) < 5:
        lines = ["Results so far (small sample — treat as a weak signal):"]
        lines += [fmt(*s) for s in scored]
    else:
        lines = ["OVERPERFORMERS (make more with this emotional angle):"]
        lines += [fmt(*s) for s in scored[:3]]
        lines.append("UNDERPERFORMERS (avoid this flavor):")
        lines += [fmt(*s) for s in scored[-3:]]
    return "\n".join(lines)
