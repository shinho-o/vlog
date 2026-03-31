"""
Vlog Trend Dashboard — YouTube 브이로그 트렌드 분석 + 모니터링
"""
import os
import json
import re
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect
from dotenv import load_dotenv
from supabase import create_client

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

app = Flask(__name__)


def sb():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── YouTube helpers ──

def _yt():
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def fetch_youtube_info(url):
    if not YOUTUBE_API_KEY:
        return None
    video_id = None
    for pattern in [r"v=([^&]+)", r"youtu\.be/([^?]+)", r"shorts/([^?]+)"]:
        m = re.search(pattern, url)
        if m:
            video_id = m.group(1)
            break
    if not video_id:
        return None
    youtube = _yt()
    resp = youtube.videos().list(part="snippet,statistics,contentDetails", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    item = items[0]
    s = item["statistics"]
    duration = item.get("contentDetails", {}).get("duration", "")
    return {
        "video_id": video_id,
        "title": item["snippet"]["title"],
        "channel": item["snippet"]["channelTitle"],
        "views": int(s.get("viewCount", 0)),
        "likes": int(s.get("likeCount", 0)),
        "comments": int(s.get("commentCount", 0)),
        "published": item["snippet"]["publishedAt"][:10],
        "duration": duration,
        "description": item["snippet"].get("description", "")[:300],
    }


def resolve_channel_id(input_str):
    if not YOUTUBE_API_KEY:
        return None
    youtube = _yt()
    channel_id = None
    m = re.search(r"@([\w.-]+)", input_str)
    if m:
        resp = youtube.search().list(part="snippet", q=f"@{m.group(1)}", type="channel", maxResults=1).execute()
        if resp.get("items"):
            channel_id = resp["items"][0]["snippet"]["channelId"]
    if not channel_id:
        m = re.search(r"channel/(UC[\w-]+)", input_str)
        if m:
            channel_id = m.group(1)
    if not channel_id:
        resp = youtube.search().list(part="snippet", q=input_str, type="channel", maxResults=1).execute()
        if resp.get("items"):
            channel_id = resp["items"][0]["snippet"]["channelId"]
    if not channel_id:
        return None
    ch_resp = youtube.channels().list(part="snippet,statistics", id=channel_id).execute()
    if not ch_resp.get("items"):
        return None
    ch = ch_resp["items"][0]
    return {
        "channel_id": channel_id,
        "name": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", "")[:200],
        "thumbnail": ch["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "total_videos": int(ch["statistics"].get("videoCount", 0)),
        "total_views": int(ch["statistics"].get("viewCount", 0)),
    }


def fetch_channel_videos(channel_id, max_results=15):
    if not YOUTUBE_API_KEY:
        return []
    youtube = _yt()
    resp = youtube.search().list(
        part="snippet", channelId=channel_id, type="video",
        order="date", maxResults=max_results,
    ).execute()
    video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
    if not video_ids:
        return []
    stats_resp = youtube.videos().list(part="statistics,snippet,contentDetails", id=",".join(video_ids)).execute()
    videos = []
    for item in stats_resp.get("items", []):
        s = item["statistics"]
        videos.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
            "published": item["snippet"]["publishedAt"][:10],
            "thumbnail": item["snippet"]["thumbnails"].get("medium", {}).get("url", ""),
            "duration": item.get("contentDetails", {}).get("duration", ""),
        })
    videos.sort(key=lambda x: x["views"], reverse=True)
    return videos


# ── Routes ──

@app.route("/")
def index():
    s = sb()
    all_videos = s.table("vlog_videos").select("*").execute().data
    saved_channels = s.table("vlog_channels").select("*").execute().data
    search_queries = s.table("vlog_queries").select("*").order("id").execute().data
    runs = s.table("vlog_runs").select("*").order("id", desc=True).limit(10).execute().data

    videos = [v for v in all_videos if not v.get("hidden")]
    hidden_count = sum(1 for v in all_videos if v.get("hidden"))

    # 카테고리별 통계
    cat_stats = {}
    for v in videos:
        cat = v.get("category", "Uncategorized")
        if cat not in cat_stats:
            cat_stats[cat] = {"count": 0, "total_views": 0, "total_likes": 0}
        cat_stats[cat]["count"] += 1
        cat_stats[cat]["total_views"] += v.get("views", 0)
        cat_stats[cat]["total_likes"] += v.get("likes", 0)
    for cs in cat_stats.values():
        cs["avg_views"] = cs["total_views"] // cs["count"] if cs["count"] > 0 else 0

    # 채널별 통계
    channel_stats = {}
    for v in videos:
        ch = v["channel"]
        if ch not in channel_stats:
            channel_stats[ch] = {"count": 0, "total_views": 0, "total_likes": 0}
        channel_stats[ch]["count"] += 1
        channel_stats[ch]["total_views"] += v.get("views", 0)
        channel_stats[ch]["total_likes"] += v.get("likes", 0)
    for cs in channel_stats.values():
        cs["engagement"] = (cs["total_likes"] / cs["total_views"] * 100) if cs["total_views"] > 0 else 0
    channel_stats = dict(sorted(channel_stats.items(), key=lambda x: x[1]["total_views"], reverse=True)[:20])

    categories = sorted(cat_stats.keys())
    total_views = sum(v.get("views", 0) for v in videos)

    return render_template("index.html",
        videos=sorted(videos, key=lambda x: x.get("views", 0), reverse=True),
        saved_channels=saved_channels,
        search_queries=search_queries,
        runs=runs,
        categories=categories,
        cat_stats=cat_stats,
        channel_stats=channel_stats,
        total_views=total_views,
        hidden_count=hidden_count,
    )


@app.route("/add_video", methods=["POST"])
def add_video():
    url = request.form.get("url", "").strip()
    category = request.form.get("category", "Uncategorized")
    if not url:
        return redirect("/")
    info = fetch_youtube_info(url)
    if not info:
        return redirect("/")
    sb().table("vlog_videos").upsert({
        "video_id": info["video_id"], "title": info["title"], "channel": info["channel"],
        "views": info["views"], "likes": info["likes"], "comments": info["comments"],
        "query": "manual", "published": info["published"],
        "date_collected": datetime.now().strftime("%Y-%m-%d"),
        "category": category, "hidden": False,
        "duration": info.get("duration", ""),
        "description": info.get("description", ""),
    }, on_conflict="video_id").execute()
    return redirect("/")


@app.route("/toggle_video", methods=["POST"])
def toggle_video():
    data = request.json
    vid = data.get("video_id")
    s = sb()
    row = s.table("vlog_videos").select("hidden").eq("video_id", vid).execute().data
    if row:
        s.table("vlog_videos").update({"hidden": not row[0]["hidden"]}).eq("video_id", vid).execute()
    return jsonify({"ok": True})


@app.route("/add_channel", methods=["POST"])
def add_channel():
    data = request.form if request.form else request.json or {}
    channel_input = data.get("channel", "").strip()
    category = data.get("category", "").strip()
    note = data.get("note", "").strip()
    if not channel_input:
        return redirect("/")
    s = sb()
    ch_info = resolve_channel_id(channel_input)
    if ch_info:
        s.table("vlog_channels").upsert({
            "channel_id": ch_info["channel_id"], "name": ch_info["name"],
            "thumbnail": ch_info["thumbnail"], "subscribers": ch_info["subscribers"],
            "total_videos": ch_info["total_videos"], "total_views": ch_info["total_views"],
            "description": ch_info["description"],
            "category": category or "Uncategorized", "note": note,
            "date_added": datetime.now().strftime("%Y-%m-%d"),
        }, on_conflict="channel_id").execute()
    else:
        s.table("vlog_channels").insert({
            "channel_id": "", "name": channel_input, "thumbnail": "",
            "subscribers": 0, "total_videos": 0, "total_views": 0, "description": "",
            "category": category or "Uncategorized", "note": note,
            "date_added": datetime.now().strftime("%Y-%m-%d"),
        }).execute()
    return redirect("/")


@app.route("/remove_channel", methods=["POST"])
def remove_channel():
    data = request.json
    sb().table("vlog_channels").delete().eq("name", data.get("name", "")).execute()
    return jsonify({"ok": True})


@app.route("/channel/<channel_id>")
def channel_detail(channel_id):
    s = sb()
    rows = s.table("vlog_channels").select("*").eq("channel_id", channel_id).execute().data
    if not rows:
        return redirect("/")
    ch = rows[0]
    videos = fetch_channel_videos(channel_id, max_results=15)
    existing_ids = {v["video_id"] for v in s.table("vlog_videos").select("video_id").execute().data}
    for v in videos:
        v["already_added"] = v["video_id"] in existing_ids
    return render_template("channel.html", ch=ch)


@app.route("/import_video", methods=["POST"])
def import_video():
    data = request.json or {}
    video_id = data.get("video_id", "")
    category = data.get("category", "Uncategorized")
    if not video_id:
        return jsonify({"error": "no video_id"}), 400
    info = fetch_youtube_info(f"https://youtube.com/watch?v={video_id}")
    if not info:
        return jsonify({"error": "fetch failed"}), 400
    sb().table("vlog_videos").upsert({
        "video_id": info["video_id"], "title": info["title"], "channel": info["channel"],
        "views": info["views"], "likes": info["likes"], "comments": info["comments"],
        "query": "channel_import", "published": info["published"],
        "date_collected": datetime.now().strftime("%Y-%m-%d"),
        "category": category, "hidden": False,
        "duration": info.get("duration", ""),
        "description": info.get("description", ""),
    }, on_conflict="video_id").execute()
    return jsonify({"ok": True})


@app.route("/add_query", methods=["POST"])
def add_query():
    data = request.form if request.form else request.json or {}
    query = data.get("query", "").strip()
    category = data.get("category", "Uncategorized").strip()
    if not query:
        return redirect("/")
    sb().table("vlog_queries").upsert(
        {"query": query, "category": category, "enabled": True},
        on_conflict="query"
    ).execute()
    return redirect("/")


@app.route("/toggle_query", methods=["POST"])
def toggle_query():
    data = request.json
    s = sb()
    row = s.table("vlog_queries").select("enabled").eq("id", data.get("id")).execute().data
    if row:
        s.table("vlog_queries").update({"enabled": not row[0]["enabled"]}).eq("id", data.get("id")).execute()
    return jsonify({"ok": True})


@app.route("/delete_query", methods=["POST"])
def delete_query():
    sb().table("vlog_queries").delete().eq("id", request.json.get("id")).execute()
    return jsonify({"ok": True})


@app.route("/collect_videos", methods=["POST"])
def collect_videos():
    if not YOUTUBE_API_KEY:
        return jsonify({"message": "YouTube API key missing"}), 400
    s = sb()
    queries = s.table("vlog_queries").select("*").eq("enabled", True).execute().data
    if not queries:
        return jsonify({"message": "No active queries", "collected": 0})

    youtube = _yt()
    today = datetime.now().strftime("%Y-%m-%d")
    from_date = datetime.now().replace(day=max(1, datetime.now().day - 14)).strftime("%Y-%m-%dT00:00:00Z")
    total = 0
    details = []

    for q in queries:
        try:
            # 브이로그는 중간 길이 (4~20분)
            resp = youtube.search().list(
                q=q["query"], part="snippet", type="video",
                order="viewCount", maxResults=10,
                publishedAfter=from_date,
                videoDuration="medium", regionCode="US",
            ).execute()
            video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]

            # 최신순도
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
                details.append({"query": q["query"], "count": 0})
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
                    "video_id": vid,
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "views": st["views"], "likes": st["likes"], "comments": st["comments"],
                    "query": q["query"], "published": item["snippet"]["publishedAt"][:10],
                    "date_collected": today, "category": q.get("category", "Uncategorized"),
                    "hidden": False, "duration": st.get("duration", ""), "description": "",
                })

            if rows:
                s.table("vlog_videos").upsert(rows, on_conflict="video_id").execute()
                total += len(rows)
            details.append({"query": q["query"], "count": len(rows)})
        except Exception as e:
            details.append({"query": q["query"], "count": 0, "error": str(e)[:100]})

    s.table("vlog_runs").insert({
        "date": today, "videos_collected": total,
        "summary": f"{total} videos from {len(queries)} queries",
    }).execute()

    summary = "\n".join([f"{d['query']}: {d['count']}개" for d in details])
    return jsonify({"message": f"{total}개 영상 수집 완료!\n{summary}", "collected": total})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    print(f"Vlog Dashboard: http://localhost:{port}")
    from waitress import serve
    if port == 5002:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    serve(app, host="0.0.0.0", port=port)
