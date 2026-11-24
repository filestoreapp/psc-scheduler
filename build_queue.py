#!/usr/bin/env python3
"""Build queue.json for psc-scheduler from the video projects' caption.txt files.

Reads ~/workspace/faceless-shorts/buffer-queue/<slug>/caption.txt for each
slug in ORDER and writes ~/workspace/psc-scheduler/queue.json.
Run again whenever new videos are ready to be queued.
"""
import json
import os
import re

BASE = os.path.expanduser("~/workspace/faceless-shorts/buffer-queue")
OUT = os.path.expanduser("~/workspace/psc-scheduler/queue.json")

ORDER = [
    "anna-rajam-malhotra",
    "sucheta-kripalani",
    "cv-raman",
    "sree-narayana-guru",
    "pt-usha",
    "quit-india",
    "preamble",
    "apj-abdul-kalam",
    "satyendranath-tagore",
    "jallianwala-bagh",
]

HEADERS = ["INSTAGRAM CAPTION", "YOUTUBE TITLE", "YOUTUBE DESCRIPTION"]


def parse_caption(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Split on the three section headers.
    parts = {}
    # Find each header's position.
    idx = {}
    for h in HEADERS:
        m = re.search(rf"^{re.escape(h)}\s*$", text, flags=re.M)
        if not m:
            raise ValueError(f"header {h!r} not found in {path}")
        idx[h] = m.end()
    order = sorted(idx, key=idx.get)
    for i, h in enumerate(order):
        end = idx[order[i + 1]] - len(order[i + 1]) if i + 1 < len(order) else len(text)
        # back up over the next header line itself
        if i + 1 < len(order):
            nxt = order[i + 1]
            end = text.rfind(nxt, 0, idx[nxt])
        seg = text[idx[h]:end]
        # drop a leading line of dashes and surrounding blank lines
        seg = re.sub(r"^\s*-+\s*\n", "", seg)
        parts[h] = seg.strip("\n").strip()
    return parts


def main():
    queue = []
    for slug in ORDER:
        cap = os.path.join(BASE, slug, "caption.txt")
        parts = parse_caption(cap)
        queue.append({
            "slug": slug,
            "video_file": f"queue/{slug}.mp4",
            "caption": parts["INSTAGRAM CAPTION"],
            "yt_title": parts["YOUTUBE TITLE"],
            "yt_description": parts["YOUTUBE DESCRIPTION"],
            "status": "pending",
            "ig_url": None,
            "yt_url": None,
        })
        print(f"ok {slug}: caption {len(parts['INSTAGRAM CAPTION'])} chars, "
              f"title {len(parts['YOUTUBE TITLE'])} chars")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {OUT} ({len(queue)} entries)")


if __name__ == "__main__":
    main()
