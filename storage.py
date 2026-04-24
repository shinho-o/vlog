"""
Supabase Storage 래퍼 — 영상 업로드·다운로드·존재 확인.

버킷: `vlog-videos`
객체 키: `{video_id}.mp4`
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BUCKET = "vlog-videos"


def _client():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수 필요")
    return create_client(url, key)


def upload(local_path: Path, video_id: str) -> str:
    """로컬 mp4 → Supabase Storage. 성공 시 스토리지 경로 반환."""
    sb = _client()
    key = f"{video_id}.mp4"
    with open(local_path, "rb") as f:
        data = f.read()
    # upsert=true 로 재시도 안전
    sb.storage.from_(BUCKET).upload(
        path=key, file=data,
        file_options={"content-type": "video/mp4",
                      "upsert": "true"},
    )
    return key


def download(video_id: str, out_path: Path) -> Path:
    """Supabase → 로컬 캐시 경로. out_path 부모 폴더 자동 생성."""
    sb = _client()
    key = f"{video_id}.mp4"
    data = sb.storage.from_(BUCKET).download(key)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def exists(video_id: str) -> bool:
    """스토리지에 해당 video_id 영상이 있는지."""
    sb = _client()
    try:
        lst = sb.storage.from_(BUCKET).list(
            path="", options={"search": f"{video_id}.mp4", "limit": 1})
        return any(item.get("name") == f"{video_id}.mp4" for item in (lst or []))
    except Exception:
        return False


def list_all() -> list[str]:
    """버킷의 모든 video_id 목록 (파일명 .mp4 제거)."""
    sb = _client()
    items = sb.storage.from_(BUCKET).list(path="", options={"limit": 1000})
    out = []
    for it in items or []:
        name = it.get("name", "")
        if name.endswith(".mp4"):
            out.append(name[:-4])
    return out


def remove(video_id: str):
    sb = _client()
    sb.storage.from_(BUCKET).remove([f"{video_id}.mp4"])
