"""
vlog_videos 테이블에서 상위 반응 쇼츠 N개 뽑아 yt-dlp로 다운로드.

사용:
    python download.py --top 10 --category "한국브이로그"
    python download.py --top 20  # 전체 카테고리
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

VIDEOS_DIR = SCRIPT_DIR / "data" / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def fetch_top(top_n: int, category: str | None, days: int):
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("[ERROR] SUPABASE_URL / SUPABASE_KEY missing", file=sys.stderr)
        sys.exit(1)

    sb = create_client(url, key)
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    query = (sb.table("vlog_videos")
             .select("video_id,title,channel,views,likes,published,category")
             .gte("date_collected", from_date)
             .eq("hidden", False)
             .order("views", desc=True)
             .limit(top_n * 3))  # oversample, then filter

    if category:
        query = query.eq("category", category)

    rows = query.execute().data or []

    # de-dup by channel (편집 스타일 다양성)
    seen_channel = set()
    picked = []
    for r in rows:
        if r["channel"] in seen_channel:
            continue
        seen_channel.add(r["channel"])
        picked.append(r)
        if len(picked) >= top_n:
            break

    return picked


def download(video_id: str, title: str) -> Path | None:
    out = VIDEOS_DIR / f"{video_id}.mp4"
    if out.exists():
        print(f"  [skip] {video_id} ({title[:40]}) — already downloaded")
        return out

    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", str(out),
        "--no-playlist",
        "--quiet", "--no-warnings",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300)
        print(f"  [ok]   {video_id} ({title[:40]})")
        return out
    except subprocess.CalledProcessError as e:
        print(f"  [fail] {video_id} — yt-dlp exit {e.returncode}")
    except subprocess.TimeoutExpired:
        print(f"  [fail] {video_id} — timeout")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--category", type=str, default=None)
    ap.add_argument("--days", type=int, default=14, help="수집된 지 N일 이내")
    args = ap.parse_args()

    print(f"[fetch] top {args.top} videos (category={args.category or 'ALL'}, days={args.days})")
    picked = fetch_top(args.top, args.category, args.days)
    if not picked:
        print("[skip] no videos matched")
        return

    print(f"[download] {len(picked)} videos → {VIDEOS_DIR}")
    ok = 0
    for r in picked:
        if download(r["video_id"], r["title"]):
            ok += 1

    print(f"[done] {ok}/{len(picked)} downloaded")


if __name__ == "__main__":
    main()
