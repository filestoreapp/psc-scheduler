# PSC Scheduler — free GitHub Actions poster

Posts the PSC study Shorts to **Instagram Reels + YouTube Shorts** on a
schedule, with **no server and no card**. GitHub Actions runs the work on
GitHub's own machines (public repos get unlimited free minutes).

## How it works

- `queue.json` lists the videos to post, in order. Each entry has the
  video file, the Instagram caption, and the YouTube title + description.
- The finished mp4s live in `queue/`. (Only the next batch — the Action
  deletes each mp4 after it posts, so the repo stays small.)
- The workflow `.github/workflows/post.yml` runs **10 times a day**
  (08:00, 09:30, 11:00, 12:30, 14:00, 15:30, 17:00, 18:30, 20:00,
  21:30 IST) and posts the **next pending video** to both platforms.
- After a post, `post.py` marks the entry `posted` in `queue.json`
  (with the Instagram + YouTube links) and deletes the mp4; the workflow
  commits that change back to the repo. The daily commits also keep the
  scheduled workflow alive (GitHub switches scheduled workflows off
  after 60 days without a push).
- If one platform succeeds and the other fails, the success is saved
  and the next run retries **only the failed platform** — a video is
  never posted twice to the same platform.
- If a video's mp4 is not in `queue/` yet, that entry is skipped and the
  run posts nothing (no error, no duplicate).

## Setup (one time)

### 1. Secrets — repo Settings → Secrets and variables → Actions → New repository secret

| Secret | What it is |
|---|---|
| `IG_ACCESS_TOKEN` | Long-lived Instagram Graph API token (see below) |
| `IG_USER_ID` | Instagram Business account id — `17841412118615814` |
| `YOUTUBE_CLIENT_ID` | Google Cloud OAuth client id |
| `YOUTUBE_CLIENT_SECRET` | Google Cloud OAuth client secret |
| `YOUTUBE_REFRESH_TOKEN` | OAuth refresh token for the channel owner |

### 2. Instagram token

The direct posting already works, so a Meta app + token exist. Get a
long-lived token (valid 60 days) from the
[Graph API Explorer](https://developers.facebook.com/tools/explorer/):
pick the app, add the `instagram_content_publish` permission, generate
the token, then exchange it for a long-lived one
(`GET /oauth/access_token?grant_type=fb_exchange_token&...`). Paste it
as `IG_ACCESS_TOKEN`. Renew it before the 60 days run out.

### 3. YouTube OAuth (Google Cloud)

This is the longest step, done once:

1. In [Google Cloud Console](https://console.cloud.google.com/) (signed
   in as **abinvinoy2296@gmail.com**, the channel owner), create a
   project (or reuse one) and enable **YouTube Data API v3**.
2. **OAuth consent screen** → set it to **Published** (not Testing).
   In Testing, refresh tokens expire after 7 days and the scheduler
   stops. A Published app keeps the token working.
3. **Credentials → Create Credentials → OAuth client ID → Desktop app**.
   Copy the client id + client secret into the two secrets above.
4. Get a refresh token with the scope
   `https://www.googleapis.com/auth/youtube.upload` — the easiest way is
   the [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/):
   open Settings, tick "Use your own OAuth credentials", paste the
   client id + secret, pick the YouTube Data API v3
   `.../auth/youtube.upload` scope, Authorize, Exchange for a refresh
   token. Paste that refresh token as `YOUTUBE_REFRESH_TOKEN`.

### 4. YouTube quota — read this

The YouTube Data API gives **10,000 quota units a day by default**, and
one video upload costs **1,600 units** — so only ~6 Shorts a day fit the
default quota. For 10 a day, request a quota increase in Google Cloud
Console → APIs & Services → YouTube Data API v3 → Quotas → pick the
`Queries per day` quota → request **20,000** (or more). Quota increases
are free; Google reviews the request, which can take a few days. Until
it is approved, the scheduler posts the first ~6 videos each day and
the rest wait (they stay queued, nothing is lost).

## Adding videos

Build the mp4 (the faceless-shorts pipeline), copy it to `queue/` as
`<slug>.mp4`, and add an entry to `queue.json`:

```json
{
  "slug": "anna-rajam-malhotra",
  "video_file": "queue/anna-rajam-malhotra.mp4",
  "caption": "<Instagram caption>",
  "yt_title": "<YouTube title>",
  "yt_description": "<YouTube description>",
  "status": "pending",
  "ig_url": null,
  "yt_url": null
}
```

Or regenerate the whole queue from the video projects with
`python3 build_queue.py` (it reads each project's `caption.txt`).

Commit + push. The next scheduled run picks the video up.

## Testing without posting

Actions tab → "Post next video" → Run workflow → tick **dry_run**.
It checks the Instagram token, refreshes the YouTube credentials, and
confirms the video file is there — and posts nothing. Run this once
after adding the secrets, before the first real run.

You can also post one specific video from the same menu by entering
its slug.

## Files

- `post.py` — the poster (Instagram Graph API resumable upload for
  Reels; YouTube Data API resumable upload; category 27 Education).
- `.github/workflows/post.yml` — the 10-a-day schedule + manual trigger.
- `queue.json` — the posting queue (order = posting order).
- `queue/` — the mp4s waiting to be posted.
- `build_queue.py` — rebuilds `queue.json` from the video projects.
