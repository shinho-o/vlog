"""
vlog_videos 테이블에서 상위 반응 쇼츠 N개 뽑아 yt-dlp로 받고
Supabase Storage(vlog-videos 버킷)에 업로드.

로컬에는 임시 파일만 잠깐 남고 업로드 성공 시 삭제한다.

사용:
    python download.py --top 30
    python download.py --top 30 --category "한국브이로그"
    python download.py --top 10 --keep-local   # 로컬 mp4도 남겨두기
"""
import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import storage

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

VIDEOS_DIR = SCRIPT_DIR / "data" / "videos"   # 옵션 --keep-local 때만 사용


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
             .limit(top_n * 3))

    if category:
        query = query.eq("category", category)

    rows = query.execute().data or []
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


def download_and_upload(video_id: str, title: str, keep_local: bool) -> bool:
    """yt-dlp → 임시 로컬 → Supabase 업로드 → (옵션) 로컬 삭제."""
    # 이미 스토리지에 있으면 스킵
    try:
        if storage.exists(video_id):
            print(f"  [skip-cloud] {video_id} ({title[:40]}) — 이미 업로드됨")
            return True
    except Exception as e:
        print(f"  [warn] 스토리지 존재 확인 실패: {e}")

    # 임시 경로 (keep_local 이면 data/videos/ 에도 복사)
    tmpdir = Path(tempfile.mkdtemp(prefix="vlog_dl_"))
    tmp_path = tmpdir / f"{video_id}.mp4"

    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", str(tmp_path),
        "--no-playlist",
        "--quiet", "--no-warnings",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        print(f"  [fail] {video_id} — yt-dlp exit {e.returncode}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [fail] {video_id} — timeout")
        return False

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        print(f"  [fail] {video_id} — 결과 파일 없음")
        return False

    size_mb = tmp_path.stat().st_size / 1024 / 1024
    print(f"  [dl-ok] {video_id} ({title[:40]}) — {size_mb:.1f} MB")

    # 업로드
    try:
        storage.upload(tmp_path, video_id)
        print(f"  [upload] {video_id} → Supabase Storage")
    except Exception as e:
        print(f"  [fail] 업로드 실패 ({video_id}): {e}")
        return False

    # 로컬 보존 옵션
    if keep_local:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        local_copy = VIDEOS_DIR / f"{video_id}.mp4"
        try:
            tmp_path.replace(local_copy)
        except Exception:
            import shutil
            shutil.copy(tmp_path, local_copy)

    # 임시 정리
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        tmpdir.rmdir()
    except Exception:
        pass
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--category", type=str, default=None)
    ap.add_argument("--days", type=int, default=14, help="수집된 지 N일 이내")
    ap.add_argument("--keep-local", action="store_true",
                    help="Supabase 업로드 외에 로컬 data/videos/ 에도 복사")
    args = ap.parse_args()

    print(f"[fetch] top {args.top} (category={args.category or 'ALL'}, days={args.days})")
    picked = fetch_top(args.top, args.category, args.days)
    if not picked:
        print("[skip] no videos matched")
        return

    print(f"[download] {len(picked)} videos → Supabase Storage")
    ok = 0
    for r in picked:
        if download_and_upload(r["video_id"], r["title"], args.keep_local):
            ok += 1

    print(f"[done] {ok}/{len(picked)} uploaded")


if __name__ == "__main__":
    main()
