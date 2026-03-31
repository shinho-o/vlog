"""
Vlog 자동 수집 — GitHub Actions 용
한국 브이로그 가중치 + 인도 콘텐츠 필터
"""
import os
import re
import sys
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 인도 콘텐츠 필터 (채널명 / 제목 키워드)
BLOCK_KEYWORDS = [
    "hindi", "desi", "bhai", "bhabhi", "yaar", "kya", "nahi", "bohot",
    "aagya", "ghar pe", "pahli", "kirtan", "bhajan", "iftaar", "gaon",
    "street food india", "indian street", "mumbai", "delhi vlog",
    "sourav joshi", "carryminati", "aayu and pihu", "dimple malhan",
    "lakhneet", "shoaib ibrahim", "bharti singh",
]

# 한국 콘텐츠 보너스 키워드
KOREAN_KEYWORDS = [
    "한국", "korean", "korea", "서울", "seoul", "브이로그", "일상",
    "대학생", "직장인", "카페", "간호", "아나운서", "서울대",
    "aesthetic", "study with me", "공부", "대학원",
]


def is_blocked(title, channel):
    """인도/불필요 콘텐츠 필터"""
    text = (title + " " + channel).lower()
    return any(kw in text for kw in BLOCK_KEYWORDS)


def is_korean_content(title, channel):
    """한국 콘텐츠 여부"""
    text = (title + " " + channel).lower()
    return any(kw in text for kw in KOREAN_KEYWORDS)


def run():
    if not YOUTUBE_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
        print("[ERROR] Missing API keys")
        sys.exit(1)

    from supabase import create_client
    from googleapiclient.discovery import build

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = datetime.now().replace(day=max(1, datetime.now().day - 14)).strftime("%Y-%m-%dT00:00:00Z")

    queries = sb.table("vlog_queries").select("*").eq("enabled", True).execute().data
    if not queries:
        print("[SKIP] No active queries")
        return

    # 한국어 키워드를 먼저 수집 (가중치)
    korean_queries = [q for q in queries if any(kw in q["query"].lower() for kw in ["한국", "korean", "korea", "서울", "브이로그", "간호", "아나운서", "서울대", "대학생", "직장인", "카페"])]
    other_queries = [q for q in queries if q not in korean_queries]
    sorted_queries = korean_queries + other_queries

    print(f"[START] {len(sorted_queries)} queries ({len(korean_queries)} Korean priority)")
    total = 0
    blocked = 0

    for q in sorted_queries:
        try:
            # 한국 키워드는 더 많이 수집
            max_results = 15 if q in korean_queries else 8

            # 한국 키워드면 KR 리전도 추가
            regions = ["KR", "US"] if q in korean_queries else ["US"]

            all_items = []
            video_ids = []

            for region in regions:
                resp = youtube.search().list(
                    q=q["query"], part="snippet", type="video",
                    order="viewCount", maxResults=max_results,
                    publishedAfter=from_date,
                    videoDuration="medium", regionCode=region,
                ).execute()
                for item in resp.get("items", []):
                    vid = item["id"]["videoId"]
                    if vid not in video_ids:
                        video_ids.append(vid)
                        all_items.append(item)

                # 최신순도
                recent = youtube.search().list(
                    q=q["query"], part="snippet", type="video",
                    order="date", maxResults=5,
                    publishedAfter=from_date,
                    videoDuration="medium", regionCode=region,
                ).execute()
                for item in recent.get("items", []):
                    vid = item["id"]["videoId"]
                    if vid not in video_ids:
                        video_ids.append(vid)
                        all_items.append(item)

            if not video_ids:
                print(f"  [{q['query']}] 0")
                continue

            stats_resp = youtube.videos().list(part="statistics,contentDetails", id=",".join(video_ids[:50])).execute()
            stats = {}
            for v in stats_resp.get("items", []):
                st = v["statistics"]
                stats[v["id"]] = {
                    "views": int(st.get("viewCount", 0)),
                    "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                    "duration": v.get("contentDetails", {}).get("duration", ""),
                }

            rows = []
            seen = set()
            q_blocked = 0
            for item in all_items:
                vid = item["id"]["videoId"]
                if vid in seen or vid not in stats:
                    continue
                seen.add(vid)

                title = item["snippet"]["title"]
                channel = item["snippet"]["channelTitle"]

                # 인도 콘텐츠 필터
                if is_blocked(title, channel):
                    q_blocked += 1
                    continue

                st = stats[vid]
                rows.append({
                    "video_id": vid, "title": title, "channel": channel,
                    "views": st["views"], "likes": st["likes"], "comments": st["comments"],
                    "query": q["query"], "published": item["snippet"]["publishedAt"][:10],
                    "date_collected": today, "category": q.get("category", "Uncategorized"),
                    "hidden": False, "duration": st.get("duration", ""), "description": "",
                })

            if rows:
                sb.table("vlog_videos").upsert(rows, on_conflict="video_id").execute()
                total += len(rows)
                blocked += q_blocked
            print(f"  [{q['query']}] {len(rows)} saved, {q_blocked} blocked")

        except Exception as e:
            print(f"  [{q['query']}] ERROR: {e}")

    sb.table("vlog_runs").insert({
        "date": today, "videos_collected": total,
        "summary": f"Auto: {total} videos, {blocked} blocked (from {len(sorted_queries)} queries)",
    }).execute()
    print(f"[DONE] {total} saved, {blocked} blocked")


if __name__ == "__main__":
    run()
