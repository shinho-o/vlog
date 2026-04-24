"""
타겟 크리에이터·키워드를 vlog_queries 테이블에 추가.
한 번 실행 후 collect.py 가 YouTube API 로 해당 영상들을 수집한다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).parent / ".env")

TARGETS = [
    # 특정 크리에이터
    {"query": "헤옹 브이로그",        "category": "여성대학생"},
    {"query": "헤옹 일상",            "category": "여성대학생"},
    {"query": "스꺼르 브이로그",      "category": "여성대학생"},
    {"query": "스꺼르 vlog",          "category": "여성대학생"},
    {"query": "이주은 브이로그",      "category": "여성대학생"},
    {"query": "이주은 vlog",          "category": "여성대학생"},
    # 같은 스타일 확장
    {"query": "여대생 브이로그",      "category": "여성대학생"},
    {"query": "대학생 일상 vlog",     "category": "여성대학생"},
    {"query": "간호대생 브이로그",    "category": "여성대학생"},
    {"query": "간호대 일상",          "category": "여성대학생"},
    {"query": "아나운서 준비 브이로그", "category": "여성대학생"},
    {"query": "아나운서 지망생 일상", "category": "여성대학생"},
    {"query": "취준생 브이로그",      "category": "여성대학생"},
    {"query": "20대 여자 브이로그",   "category": "여성대학생"},
    {"query": "자취 일상 vlog",       "category": "여성대학생"},
    {"query": "모닝 루틴 한국",       "category": "여성대학생"},
    {"query": "study with me 한국",   "category": "여성대학생"},
]


def main():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    rows = []
    for t in TARGETS:
        rows.append({"query": t["query"], "category": t["category"], "enabled": True})
    # upsert 로 중복 방지 (query 가 unique 라고 가정)
    try:
        sb.table("vlog_queries").upsert(rows, on_conflict="query").execute()
    except Exception:
        # unique 제약 없으면 insert. 기존 동일 query 는 수동 정리
        for r in rows:
            try:
                sb.table("vlog_queries").insert(r).execute()
            except Exception as e:
                print(f"[skip] {r['query']}: {e}")
    print(f"[done] {len(rows)}개 쿼리 등록/유지")


if __name__ == "__main__":
    main()
