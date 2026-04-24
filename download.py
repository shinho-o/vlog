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


import re
_HANGUL = re.compile(r"[가-힣]")
# 비한국어 스크립트 — 하나라도 있으면 해외 콘텐츠로 간주
_THAI = re.compile(r"[฀-๿]")
_ARABIC = re.compile(r"[؀-ۿ]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_CJK = re.compile(r"[一-鿿]")
# 브이로그 포맷 지시어 (필수 중 하나 매치)
_VLOG = re.compile(
    r"(브이로그|vlog|일상|데일리|daily|하루|routine|루틴|주간|"
    r"morning routine|night routine|nightly|아침루틴|저녁루틴)",
    re.IGNORECASE,
)
# 20대 여성 · 대학생/취준/간호/아나운서 니치 (점수 2배 가산)
_NICHE = re.compile(
    r"(대학생|대학원생|대학원|캠퍼스|과외|"
    r"간호대|간호학|간호학과|간호사|너스|RN|"
    r"아나운서|아나운서준비|스피치|언론고시|"
    r"승무원|취준|취업준비|취준생|신입|"
    r"치대|약대|의대생|수시|재수|n수|"
    r"대학생활|자취|기숙사|OT|MT|"
    r"20대|이십대|20s|20\s?대)",
    re.IGNORECASE,
)
# 여성 힌트 (강제 아니고 가산)
_FEM = re.compile(
    r"(여자|여성|언니|누나|소녀|그녀|"
    r"she|girl|her vlog|female|여대생|여신)",
    re.IGNORECASE,
)
_BLOCK = re.compile(
    r"("
    # 인도
    r"hindi|desi|bhai|bhabhi|mumbai|delhi|kolkata|bengaluru|bangalore"
    r"|sourav|carryminati|aayu|pihu|dimple|lakhneet|shoaib|bharti"
    # 베트남
    r"|vietnam|việt|hanoi|hà\s?nội|saigon|sài\s?gòn|nhật\s?ký|vlog\s?việt"
    # 태국
    r"|thailand|bangkok|krungthep|สวัสดี"
    # 인도네시아
    r"|indonesia|jakarta|bali|surabaya|selamat|terima\s?kasih"
    # 필리핀·말레이시아
    r"|philippines|manila|tagalog|filipino|malaysia|kuala\s?lumpur"
    # 중화권
    r"|中国|日常|中文|上海|北京|台湾|香港"
    # 방송·다큐
    r"|휴먼다큐|휴먼스토리|인간극장|다큐멘터리|다큐프라임|다큐"
    r"|kbs|mbc|sbs|ebs|tvn|jtbc|channela|mbn"
    r"|방송사|다시보기|하이라이트|full episode|fullep"
    # 뉴스·시사
    r"|뉴스|보도|시사|현장중계|news"
    # 예능·드라마
    r"|런닝맨|무한도전|나혼자산다|복면가왕|드라마|예능클립"
    # 리얼리티쇼
    r"|나는솔로|환승연애|하트시그널"
    # 기타
    r"|공식채널|official channel"
    r")",
    re.IGNORECASE,
)


def _is_korean(title: str, channel: str) -> bool:
    """엄격한 한국 콘텐츠 판정.
    1) 블록 키워드 (인도/동남아/방송/뉴스 등) 있으면 reject
    2) 태국·아랍·힌디 문자 있으면 reject
    3) 한자만 있고 한글 0자면 reject (중·일)
    4) 한글 3자 이상 필요
    """
    text = (title or "") + " " + (channel or "")
    if _BLOCK.search(text):
        return False
    if _THAI.search(text) or _ARABIC.search(text) or _DEVANAGARI.search(text):
        return False
    hangul = len(_HANGUL.findall(text))
    cjk = len(_CJK.findall(text))
    if hangul < 3:
        return False
    # 한자가 한글보다 많으면 중/일본 콘텐츠
    if cjk > hangul:
        return False
    return True


def _is_vlog(title: str, channel: str) -> bool:
    text = (title or "") + " " + (channel or "")
    return bool(_VLOG.search(text))


def _velocity(row: dict) -> float:
    """조회수 / 업로드 후 일수 = 하루당 평균 조회수 (신선도 반영)."""
    try:
        pub = datetime.strptime(row["published"][:10], "%Y-%m-%d")
        days = max(0.5, (datetime.now() - pub).days)
        return float(row.get("views", 0)) / days
    except Exception:
        return float(row.get("views", 0))


def _niche_score(row: dict) -> float:
    """20대 여성 대학생/아나운서/간호대 등 니치 가산점 (1.0 ~ 3.0)."""
    text = ((row.get("title") or "") + " " + (row.get("channel") or ""))
    score = 1.0
    if _NICHE.search(text):
        score *= 2.0
    if _FEM.search(text):
        score *= 1.5
    return score


def fetch_top(top_n: int, category: str | None, days: int,
              korean_only: bool, hot: bool, published_days: int):
    """Supabase vlog_videos 에서 상위 영상 선별.
    - korean_only: 제목/채널에 한글 있는 것만
    - hot: 조회수 대신 하루당 조회수(신선도)로 정렬
    - published_days: 업로드된 지 N일 이내만
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("[ERROR] SUPABASE_URL / SUPABASE_KEY missing", file=sys.stderr)
        sys.exit(1)

    sb = create_client(url, key)
    from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    pub_from = (datetime.now() - timedelta(days=published_days)).strftime(
        "%Y-%m-%d")

    query = (sb.table("vlog_videos")
             .select("video_id,title,channel,views,likes,published,category,duration")
             .gte("date_collected", from_date)
             .gte("published", pub_from)
             .eq("hidden", False)
             .order("views", desc=True)
             .limit(top_n * 5))  # 넉넉히 뽑아 필터링 후 자름

    if category:
        query = query.eq("category", category)

    rows = query.execute().data or []

    # 1) 한국 콘텐츠 필터
    if korean_only:
        rows = [r for r in rows if _is_korean(r.get("title"), r.get("channel"))]

    # 2) 브이로그 포맷 필터 (브이로그/vlog/일상/루틴 등)
    rows = [r for r in rows if _is_vlog(r.get("title"), r.get("channel"))]

    # 3) 점수 = (속도 or 조회수) × 니치 가산
    for r in rows:
        base = _velocity(r) if hot else float(r.get("views", 0))
        r["_score"] = base * _niche_score(r)
    rows.sort(key=lambda r: r["_score"], reverse=True)

    # 4) 채널 중복 제거
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
    """yt-dlp → 임시 로컬 → Supabase 업로드 → (실패·예외 포함) 무조건 temp 정리."""
    # 이미 스토리지에 있으면 스킵
    try:
        if storage.exists(video_id):
            print(f"  [skip-cloud] {video_id} ({title[:40]}) — 이미 업로드됨")
            return True
    except Exception as e:
        print(f"  [warn] 스토리지 존재 확인 실패: {e}")

    tmpdir = Path(tempfile.mkdtemp(prefix="vlog_dl_"))
    tmp_path = tmpdir / f"{video_id}.mp4"
    success = False
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        # 720p 우선 (용량 절반, 분석 품질 충분)
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best[height<=720]",
            "--merge-output-format", "mp4",
            "-o", str(tmp_path),
            "--no-playlist",
            "--quiet", "--no-warnings",
            "--no-cache-dir",
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
        # 50MB 넘는 건 Supabase 무료 플랜에 업로드 실패 — 사전 체크
        if size_mb > 49:
            print(f"  [skip] {video_id} — {size_mb:.1f} MB (50MB 초과, Supabase 업로드 불가)")
            return False

        print(f"  [dl-ok] {video_id} ({title[:40]}) — {size_mb:.1f} MB")

        try:
            storage.upload(tmp_path, video_id)
            print(f"  [upload] {video_id} → Supabase")
            success = True
        except Exception as e:
            print(f"  [fail] 업로드 실패 ({video_id}): {e}")
            return False

        if keep_local and success:
            VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
            local_copy = VIDEOS_DIR / f"{video_id}.mp4"
            try:
                import shutil as _sh
                _sh.copy(tmp_path, local_copy)
            except Exception:
                pass
        return True
    finally:
        # 성공/실패 무관하게 임시 파일 제거
        try:
            import shutil as _sh2
            _sh2.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--category", type=str, default=None)
    ap.add_argument("--days", type=int, default=14, help="DB 수집된 지 N일 이내")
    ap.add_argument("--published-days", type=int, default=30,
                    help="유튜브 업로드된 지 N일 이내만 (기본 30일)")
    ap.add_argument("--no-korean-filter", action="store_true",
                    help="한국 필터 해제 (기본: 한글 2자 이상)")
    ap.add_argument("--no-hot", action="store_true",
                    help="하루당 조회수 정렬 대신 총 조회수 정렬")
    ap.add_argument("--keep-local", action="store_true",
                    help="Supabase 업로드 외에 로컬 data/videos/ 에도 복사")
    args = ap.parse_args()

    korean_only = not args.no_korean_filter
    hot = not args.no_hot

    print(f"[fetch] top {args.top} "
          f"(category={args.category or 'ALL'}, "
          f"published≤{args.published_days}d, "
          f"korean={korean_only}, hot={hot})")
    picked = fetch_top(args.top, args.category, args.days,
                       korean_only=korean_only, hot=hot,
                       published_days=args.published_days)
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
