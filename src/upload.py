"""Upload the finished Short to YouTube via the Data API v3 (OAuth desktop flow).

First run: opens a browser window to sign in to your Google account; the grant is
cached in token.json so scheduled runs are fully unattended afterwards.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET = ROOT / "client_secret.json"
TOKEN_FILE = ROOT / "token.json"
# upload for the daily pipeline; analytics + readonly for the feedback loop;
# force-ssl for auto-comments and playlist sorting
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _stored_scopes() -> list:
    if not TOKEN_FILE.exists():
        return []
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scopes") or []


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        # load with the token's OWN scopes so an older upload-only grant keeps
        # working and a refresh never rewrites the file with a narrower list
        info = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            raise RuntimeError(
                "client_secret.json not found. Follow the 'YouTube upload setup' "
                "section of README.md to create it, then run: python authorize.py"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def authorize() -> None:
    """Interactive OAuth bootstrap; re-consents if the stored grant is missing scopes."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if set(SCOPES) <= set(_stored_scopes()):
        _credentials()
        print("token.json already covers upload + analytics — nothing to do.")
        return
    if not CLIENT_SECRET.exists():
        raise RuntimeError("client_secret.json not found — see README.md, then rerun.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print("Authorization complete. token.json now covers uploads + analytics.")


def upload_video(video_file: Path, plan: dict, config: dict, is_short: bool = True) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    up = config.get("upload", {})
    tags = list(dict.fromkeys(plan.get("tags", []) + up.get("extra_tags", [])))[:30]
    body = {
        "snippet": {
            "title": plan["title"][:100],
            "description": plan["description"][:4900],
            "tags": tags,
            "categoryId": up.get("category_id", "27"),
        },
        "status": {
            "privacyStatus": up.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(up.get("made_for_kids", False)),
            # Mandatory AI-content disclosure: the voiceover is synthetic (edge-tts)
            "containsSyntheticMedia": bool(up.get("contains_synthetic_media", True)),
        },
    }
    youtube = build("youtube", "v3", credentials=_credentials())
    media = MediaFileUpload(str(video_file), mimetype="video/mp4", resumable=True, chunksize=1 << 22)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")
    video_id = response["id"]
    if is_short:
        return f"https://www.youtube.com/shorts/{video_id}"
    return f"https://www.youtube.com/watch?v={video_id}"


def _video_id(video_url: str) -> str:
    return video_url.rstrip("/").split("v=")[-1].split("/")[-1]


def _has_force_ssl() -> bool:
    return "https://www.googleapis.com/auth/youtube.force-ssl" in _stored_scopes()


def post_comment(video_url: str, text: str) -> bool:
    """Drop the engagement question as a channel comment on the fresh upload.
    Silently skipped until the stored grant includes force-ssl (rerun authorize.py)."""
    if not _has_force_ssl():
        print("    comment skipped: run `python authorize.py` once to enable")
        return False
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", credentials=_credentials())
    youtube.commentThreads().insert(
        part="snippet",
        body={"snippet": {
            "videoId": _video_id(video_url),
            "topLevelComment": {"snippet": {"textOriginal": text[:500]}},
        }},
    ).execute()
    return True


PLAYLIST_CACHE = ROOT / "data" / "playlists.json"


def add_to_playlist(video_url: str, playlist_title: str) -> bool:
    """Sort the upload into its themed playlist, creating the playlist on first use.
    Silently skipped until the stored grant includes force-ssl."""
    if not _has_force_ssl() or not playlist_title:
        if playlist_title:
            print("    playlist skipped: run `python authorize.py` once to enable")
        return False
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", credentials=_credentials())

    cache = {}
    if PLAYLIST_CACHE.exists():
        cache = json.loads(PLAYLIST_CACHE.read_text(encoding="utf-8-sig"))
    playlist_id = cache.get(playlist_title)
    if not playlist_id:
        found = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        for item in found.get("items", []):
            if item["snippet"]["title"].strip().lower() == playlist_title.strip().lower():
                playlist_id = item["id"]
                break
    if not playlist_id:
        created = youtube.playlists().insert(
            part="snippet,status",
            body={"snippet": {"title": playlist_title,
                              "description": "Curated by the channel."},
                  "status": {"privacyStatus": "public"}},
        ).execute()
        playlist_id = created["id"]
    cache[playlist_title] = playlist_id
    PLAYLIST_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PLAYLIST_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    youtube.playlistItems().insert(
        part="snippet",
        body={"snippet": {"playlistId": playlist_id,
                          "resourceId": {"kind": "youtube#video",
                                         "videoId": _video_id(video_url)}}},
    ).execute()
    return True


def set_thumbnail(video_url: str, image_file: Path) -> None:
    """Attach a custom thumbnail (long-form only; needs a phone-verified channel)."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    video_id = video_url.rstrip("/").split("v=")[-1].split("/")[-1]
    youtube = build("youtube", "v3", credentials=_credentials())
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(image_file), mimetype="image/jpeg"),
    ).execute()
