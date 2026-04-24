"""
지정 채널의 최근 영상을 yt-dlp 로 직접 긁어 Drive 의 _index JSON 으로 저장.
YouTube API 를 아예 쓰지 않아 쿼터 제약 없음.

사용:
    python fetch_channels.py "@Ong_Hyewon" "@Joohyunjoohyuny" "@쓰까르"
    python fetch_channels.py --per-channel 50 "@Ong_Hyewon"
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import storage

DRIVE_ROOT = storage.storage_root()
INDEX_DIR = DRIVE_ROOT / "_index"
INDEX_DIR.mkdir(exist_ok=True)


def fetch_channel(handle: str, limit: int) -> tuple[str, str, list[dict]]:
    """yt-dlp --flat-playlist 로 채널의 최근 영상 limit 개 메타 추출.
    반환: (channel_id, channel_title, videos)
    """
    handle = handle.strip()
    if not handle.startswith("@") and not handle.startswith("UC"):
        handle = "@" + handle
    url = f"https://www.youtube.com/{handle}/videos"

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--playlist-end", str(limit),
        "--dump-single-json",
        "--no-warnings",
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp 실패 (exit {r.returncode}): {r.stderr[-300:]}")

    data = json.loads(r.stdout)
    ch_id = data.get("channel_id", "") or data.get("uploader_id", "")
    ch_title = data.get("channel", "") or data.get("uploader", handle)

    videos = []
    for e in (data.get("entries") or [])[:limit]:
        if not e:
            continue
        vid = e.get("id") or e.get("video_id")
        if not vid:
            continue
        # yt-dlp flat-playlist 는 업로드 날짜가 없을 수 있음
        videos.append({
            "video_id": vid,
            "title": e.get("title", ""),
            "channel": ch_title,
            "views": int(e.get("view_count") or 0),
            "likes": 0,  # flat-playlist 에는 좋아요 없음
            "comments": 0,
            "duration": e.get("duration") or 0,
            "published": (e.get("timestamp") and
                          datetime.fromtimestamp(e["timestamp"]).strftime("%Y-%m-%d"))
                          or "",
        })
    return ch_id, ch_title, videos


def save_channel_json(channel_id: str, channel_title: str,
                      videos: list[dict], handle: str) -> Path:
    safe = "".join(c for c in channel_title if c.isalnum() or c in "_-") or channel_id
    out = INDEX_DIR / f"channel_{safe}.json"
    out.write_text(json.dumps({
        "channel_id": channel_id,
        "channel_title": channel_title,
        "handle": handle,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "videos": videos,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("handles", nargs="+", help="@핸들 또는 UC채널ID")
    ap.add_argument("--per-channel", type=int, default=30)
    args = ap.parse_args()

    total = 0
    for h in args.handles:
        try:
            print(f"[fetch] {h} — yt-dlp 로 긁는 중...")
            ch_id, ch_title, videos = fetch_channel(h, args.per_channel)
            out = save_channel_json(ch_id, ch_title, videos, h)
            print(f"  {ch_title} ({ch_id}) → {len(videos)}개 → {out.name}")
            total += len(videos)
        except Exception as e:
            print(f"[error] {h}: {e}")

    print(f"\n[done] 총 {total}개 영상 메타 → {INDEX_DIR}")


if __name__ == "__main__":
    main()
