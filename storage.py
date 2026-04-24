"""
스토리지 래퍼 — 로컬 Google Drive 마운트 경로에 직접 저장.
Drive for Desktop 이 자동 동기화하므로 OAuth·API 셋업 없이 동작.

기본 저장소: `G:/내 드라이브/QuickCut_Vlogs/` (Windows 한국어)
- 환경변수 `DRIVE_VLOG_DIR` 로 오버라이드 가능
- 유효한 경로가 없으면 로컬 data/videos 로 폴백
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def _default_drive_path() -> Path | None:
    """Google Drive for Desktop 의 QuickCut_Vlogs 폴더 경로 찾기."""
    candidates = [
        r"G:\내 드라이브\QuickCut_Vlogs",
        r"G:\My Drive\QuickCut_Vlogs",
        # 로컬 사용자 폴더
        str(Path.home() / "Google Drive" / "내 드라이브" / "QuickCut_Vlogs"),
        str(Path.home() / "Google Drive" / "My Drive" / "QuickCut_Vlogs"),
    ]
    env = os.getenv("DRIVE_VLOG_DIR")
    if env:
        candidates.insert(0, env)
    for p in candidates:
        pp = Path(p)
        if pp.parent.exists():
            pp.mkdir(parents=True, exist_ok=True)
            return pp
    return None


_ROOT = _default_drive_path() or (Path(__file__).parent / "data" / "videos")
_ROOT.mkdir(parents=True, exist_ok=True)


def storage_root() -> Path:
    return _ROOT


def upload(local_path: Path, video_id: str) -> str:
    """로컬 임시 파일 → Drive 마운트 폴더로 복사 (Drive 가 자동 클라우드 업로드)."""
    dest = _ROOT / f"{video_id}.mp4"
    if dest.exists():
        dest.unlink()
    shutil.copy2(local_path, dest)
    return str(dest)


def download(video_id: str, out_path: Path) -> Path:
    """Drive 마운트 폴더에서 로컬 캐시로 복사."""
    src = _ROOT / f"{video_id}.mp4"
    if not src.exists():
        raise FileNotFoundError(f"Drive 에 {video_id}.mp4 없음")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out_path)
    return out_path


def exists(video_id: str) -> bool:
    return (_ROOT / f"{video_id}.mp4").exists()


def list_all() -> list[str]:
    return sorted(p.stem for p in _ROOT.glob("*.mp4"))


def remove(video_id: str):
    p = _ROOT / f"{video_id}.mp4"
    if p.exists():
        p.unlink()


if __name__ == "__main__":
    print(f"저장소 경로: {_ROOT}")
    print(f"현재 영상 수: {len(list_all())}")
