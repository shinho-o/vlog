"""
지정 채널의 최근 영상을 YouTube API 로 끌어와 `vlog_videos` 에 업서트.

사용:
    python fetch_channels.py @Ong_Hyewon @Joohyunjoohyuny @쓰까르
    python fetch_channels.py --per-channel 30 @Ong_Hyewon

기본 20개. 채널 핸들(@xxx) 또는 채널ID(UCxxxxx) 둘 다 허용.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import storage  # Drive 마운트 경로

load_dotenv(Path(__file__).parent / ".env")

DRIVE_ROOT = storage.storage_root()
INDEX_DIR = DRIVE_ROOT / "_index"
INDEX_DIR.mkdir(exist_ok=True)


def _yt():
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))


def resolve_channel_id(yt, handle_or_id: str) -> tuple[str, str] | None:
    """핸들/ID → (channel_id, channel_title)."""
    s = handle_or_id.strip()
    if s.startswith("UC") and len(s) == 24:
        r = yt.channels().list(part="snippet", id=s).execute()
    else:
        if not s.startswith("@"):
            s = "@" + s
        # forHandle 사용 (2024+ 지원)
        r = yt.channels().list(part="snippet", forHandle=s).execute()
    items = r.get("items", [])
    if not items:
        return None
    ch = items[0]
    return ch["id"], ch["snippet"]["title"]


def fetch_channel_videos(yt, channel_id: str, limit: int = 20) -> list[dict]:
    """채널의 uploads 플레이리스트에서 최근 limit 개 가져오기."""
    r = yt.channels().list(part="contentDetails", id=channel_id).execute()
    items = r.get("items", [])
    if not items:
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    vids = []
    page_token = None
    while len(vids) < limit:
        pl = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads,
            maxResults=min(50, limit - len(vids)),
            pageToken=page_token,
        ).execute()
        for it in pl.get("items", []):
            vids.append({
                "video_id": it["contentDetails"]["videoId"],
                "title": it["snippet"]["title"],
                "channel": it["snippet"]["channelTitle"],
                "published": it["contentDetails"].get("videoPublishedAt", "")[:10],
            })
        page_token = pl.get("nextPageToken")
        if not page_token:
            break

    # 통계 (조회수·좋아요)
    for i in range(0, len(vids), 50):
        chunk = vids[i:i + 50]
        ids = ",".join(v["video_id"] for v in chunk)
        stats = yt.videos().list(part="statistics,contentDetails", id=ids).execute()
        by_id = {v["id"]: v for v in stats.get("items", [])}
        for v in chunk:
            s = by_id.get(v["video_id"], {})
            st = s.get("statistics", {})
            v["views"] = int(st.get("viewCount", 0))
            v["likes"] = int(st.get("likeCount", 0))
            v["comments"] = int(st.get("commentCount", 0))
            v["duration"] = s.get("contentDetails", {}).get("duration", "")
    return vids


def save_channel_json(channel_id: str, channel_title: str,
                      videos: list[dict], handle: str):
    """Drive 에 채널별 JSON 저장 — Supabase 의존성 제거."""
    safe = "".join(c for c in channel_title if c.isalnum() or c in "_-") or channel_id
    out = INDEX_DIR / f"channel_{safe}.json"
    data = {
        "channel_id": channel_id,
        "channel_title": channel_title,
        "handle": handle,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "videos": videos,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("handles", nargs="+", help="@핸들 또는 UC채널ID")
    ap.add_argument("--per-channel", type=int, default=20)
    args = ap.parse_args()

    yt = _yt()
    total = 0
    for h in args.handles:
        try:
            res = resolve_channel_id(yt, h)
        except Exception as e:
            print(f"[error] {h}: {e}")
            continue
        if not res:
            print(f"[miss] 채널 찾기 실패: {h}")
            continue
        ch_id, ch_title = res
        print(f"[fetch] {h} → {ch_title} ({ch_id})")
        videos = fetch_channel_videos(yt, ch_id, limit=args.per_channel)
        print(f"  {len(videos)}개 영상 수집")
        out = save_channel_json(ch_id, ch_title, videos, h)
        print(f"  → {out}")
        total += len(videos)

    print(f"\n[done] 총 {total}개 영상 → Drive {INDEX_DIR}")


if __name__ == "__main__":
    main()
