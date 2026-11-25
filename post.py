#!/usr/bin/env python3
"""PSC Current Affairs — scheduled poster (GitHub Actions).

Posts the next pending video from queue.json to Instagram Reels and
YouTube Shorts, then marks it posted in queue.json and deletes the mp4
(the workflow step commits those changes back to the repo).

Secrets (GitHub repo Settings -> Secrets and variables -> Actions):
  IG_ACCESS_TOKEN        Long-lived Instagram Graph API token
                         (needs instagram_content_publish)
  IG_USER_ID             Instagram Business account id (e.g. 17841412118615814)
  YOUTUBE_CLIENT_ID      Google Cloud OAuth client id
  YOUTUBE_CLIENT_SECRET  Google Cloud OAuth client secret
  YOUTUBE_REFRESH_TOKEN  OAuth refresh token for the channel owner
                         (scope https://www.googleapis.com/auth/youtube.upload)

Usage:
  python post.py                  Post the next pending video (both platforms)
  python post.py --slug <slug>    Post one specific video
  python post.py --dry-run        Validate tokens + video, post nothing
  python post.py --instagram-only / --youtube-only

Notes:
- Instagram: Graph API resumable upload (REELS). Video must be <= 90s.
- YouTube: vertical 9:16 under 60s auto-detects as a Short. Category 27
  (Education). Each upload costs 1600 YouTube Data API quota units; the
  default daily quota is 10,000 units, so ~6 uploads/day max until the
  user requests a quota increase in Google Cloud Console.
- If one platform succeeds and the other fails, the success is recorded
  (ig_url / yt_url) and the next run retries only the failed platform,
  so a video is never posted twice to the same platform.
"""

import argparse
import json
import os
import re
import sys
import time

import requests

GRAPH = "https://graph.facebook.com/v22.0"
QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue.json")

IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_queue():
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue):
    with open(QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.write("\n")


def video_path(entry):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), entry["video_file"])


def pick_entry(queue, slug=None):
    for e in queue:
        if e.get("status") == "posted":
            continue
        if slug and e["slug"] != slug:
            continue
        p = video_path(e)
        if not os.path.exists(p):
            log(f"SKIP {e['slug']}: video file missing ({e['video_file']})")
            continue
        return e
    return None


# ---------------- Instagram ----------------

def ig_post(entry):
    """Post the video as an Instagram Reel. Returns the permalink."""
    path = video_path(entry)
    size = os.path.getsize(path)
    caption = entry["caption"]

    # 1. Create a resumable upload container.
    r = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "thumb_offset": 1200,
            "access_token": IG_TOKEN,
        },
        timeout=60,
    )
    r.raise_for_status()
    container = r.json()
    container_id = container["id"]
    upload_uri = container["uri"]
    log(f"IG container {container_id}")

    # 2. Upload the video bytes to the resumable URI.
    # Read the whole file into memory so requests sends a Content-Length
    # header: streaming a file object uses chunked transfer encoding,
    # which the rupload endpoint rejects with 400 Bad Request.
    with open(path, "rb") as f:
        video_bytes = f.read()
    up = requests.post(
        upload_uri,
        data=video_bytes,
        headers={
            "Authorization": f"OAuth {IG_TOKEN}",
            "offset": "0",
            "file_size": str(size),
            "Content-Type": "video/mp4",
        },
        timeout=300,
    )
    up.raise_for_status()
    log("IG bytes uploaded")

    # 3. Poll until the container is FINISHED.
    deadline = time.time() + 180
    while time.time() < deadline:
        s = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
            timeout=30,
        )
        s.raise_for_status()
        st = s.json()
        code = st.get("status_code")
        log(f"IG container status: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG container failed: {st}")
        time.sleep(5)
    else:
        raise RuntimeError("IG container did not finish in time")

    # 4. Publish the container.
    p = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_TOKEN},
        timeout=60,
    )
    p.raise_for_status()
    media_id = p.json()["id"]
    log(f"IG published media {media_id}")

    # 5. Permalink.
    m = requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": IG_TOKEN},
        timeout=30,
    )
    m.raise_for_status()
    permalink = m.json().get("permalink", "")
    log(f"IG permalink: {permalink}")
    return permalink


def ig_check():
    r = requests.get(f"{GRAPH}/me", params={"access_token": IG_TOKEN}, timeout=30)
    r.raise_for_status()
    log(f"IG token OK: {r.json()}")


# ---------------- YouTube ----------------

def yt_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(Request())
    log("YT credentials refreshed")
    return build("youtube", "v3", credentials=creds)


def yt_post(entry):
    """Upload the video as a YouTube Short. Returns the Shorts URL."""
    from googleapiclient.http import MediaFileUpload

    service = yt_service()
    path = video_path(entry)
    tags = re.findall(r"#(\w+)", entry.get("yt_description", ""))
    body = {
        "snippet": {
            "title": entry["yt_title"],
            "description": entry["yt_description"],
            "tags": tags[:30],
            "categoryId": "27",  # Education
            "defaultLanguage": "ml",
            "defaultAudioLanguage": "ml",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(path, mimetype="video/mp4", chunksize=1024 * 1024, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"YT upload {int(status.progress() * 100)}%")
    video_id = response["id"]
    url = f"https://www.youtube.com/shorts/{video_id}"
    log(f"YT uploaded: {url}")
    return url


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--instagram-only", action="store_true")
    ap.add_argument("--youtube-only", action="store_true")
    args = ap.parse_args()

    if not IG_TOKEN or not IG_USER_ID:
        print("Missing IG_ACCESS_TOKEN or IG_USER_ID", file=sys.stderr)
        return 2
    if not args.instagram_only and not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        print("Missing YouTube OAuth secrets (set them, or use --instagram-only)", file=sys.stderr)
        return 2

    queue = load_queue()
    entry = pick_entry(queue, args.slug)
    if not entry:
        log("Nothing to post (queue empty or videos not uploaded yet).")
        return 0

    slug = entry["slug"]
    log(f"Next video: {slug} ({entry['video_file']})")

    if args.dry_run:
        ig_check()
        yt_service()  # validates YT credentials (refreshes the token)
        size = os.path.getsize(video_path(entry))
        log(f"DRY RUN OK: {slug}, {size} bytes, caption {len(entry['caption'])} chars, "
            f"YT title {len(entry['yt_title'])} chars. Nothing posted.")
        return 0

    posted = False
    if not args.youtube_only and not entry.get("ig_url"):
        try:
            entry["ig_url"] = ig_post(entry)
            posted = True
        except Exception as e:
            log(f"IG FAILED for {slug}: {e}")
    if not args.instagram_only and not entry.get("yt_url"):
        try:
            entry["yt_url"] = yt_post(entry)
            posted = True
        except Exception as e:
            log(f"YT FAILED for {slug}: {e}")

    if entry.get("ig_url") and entry.get("yt_url"):
        entry["status"] = "posted"
        entry["posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        p = video_path(entry)
        if os.path.exists(p):
            os.remove(p)
            log(f"Deleted uploaded video {entry['video_file']}")
        log(f"POSTED {slug}: IG {entry['ig_url']} | YT {entry['yt_url']}")
    elif posted:
        log(f"PARTIAL {slug}: IG={entry.get('ig_url') or '-'} YT={entry.get('yt_url') or '-'} "
            f"(next run retries only the missing platform)")
    else:
        log(f"FAILED {slug}: nothing posted, will retry next run")
        save_queue(queue)
        return 1

    save_queue(queue)
    return 0


if __name__ == "__main__":
    sys.exit(main())
