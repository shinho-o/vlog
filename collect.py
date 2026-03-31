"""
Vlog 자동 수집 — GitHub Actions 용
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


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

    print(f"[START] {len(queries)} queries")
    total = 0

    for q in queries:
        try:
            resp = youtube.search().list(
                q=q["query"], part="snippet", type="video",
                order="viewCount", maxResults=10,
                publishedAfter=from_date,
                videoDuration="medium", regionCode="US",
            ).execute()
            video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]

            recent = youtube.search().list(
                q=q["query"], part="snippet", type="video",
                order="date", maxResults=5,
                publishedAfter=from_date,
                videoDuration="medium", regionCode="US",
            ).execute()
            for item in recent.get("items", []):
                vid = item["id"]["videoId"]
                if vid not in video_ids:
                    video_ids.append(vid)

            if not video_ids:
                print(f"  [{q['query']}] 0")
                continue

            stats_resp = youtube.videos().list(part="statistics,contentDetails", id=",".join(video_ids)).execute()
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
            for item in resp.get("items", []) + recent.get("items", []):
                vid = item["id"]["videoId"]
                if vid in seen or vid not in stats:
                    continue
                seen.add(vid)
                st = stats[vid]
                rows.append({
                    "video_id": vid, "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "views": st["views"], "likes": st["likes"], "comments": st["comments"],
                    "query": q["query"], "published": item["snippet"]["publishedAt"][:10],
                    "date_collected": today, "category": q.get("category", "Uncategorized"),
                    "hidden": False, "duration": st.get("duration", ""), "description": "",
                })

            if rows:
                sb.table("vlog_videos").upsert(rows, on_conflict="video_id").execute()
                total += len(rows)
            print(f"  [{q['query']}] {len(rows)}")

        except Exception as e:
            print(f"  [{q['query']}] ERROR: {e}")

    sb.table("vlog_runs").insert({
        "date": today, "videos_collected": total,
        "summary": f"Auto: {total} videos from {len(queries)} queries",
    }).execute()
    print(f"[DONE] {total} videos")


if __name__ == "__main__":
    run()
