"""
다운로드된 쇼츠 영상을 분석해 편집 스타일 지표를 뽑는다.

출력: data/analysis/{video_id}.json
    {
      "video_id": "...",
      "duration_sec": 58.3,
      "cuts": { "count": 32, "avg_interval_sec": 1.82, "pacing": "fast" },
      "speech": { "hook_text": "...", "total_chars": 240, "chars_per_sec": 4.1, "segments": [...] },
      "audio": { "bpm": 98.4, "rms_mean": 0.12, "has_bgm": true },
      "thumbnail": { "dominant_colors": ["#f4d1a1", "#2b2b2b", "#e6e6e6"] }
    }

사용:
    python analyze.py                  # data/videos/ 전체 신규 분석
    python analyze.py --video VIDEO_ID # 단일 영상
"""
import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
VIDEOS_DIR = SCRIPT_DIR / "data" / "videos"
ANALYSIS_DIR = SCRIPT_DIR / "data" / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def probe_duration(video_path: Path) -> float:
    """ffprobe로 길이(초) 얻기."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0.0)


def analyze_cuts(video_path: Path, duration: float) -> dict:
    """PySceneDetect로 컷 감지."""
    from scenedetect import detect, ContentDetector

    scenes = detect(str(video_path), ContentDetector(threshold=27.0, min_scene_len=8))
    count = len(scenes)
    avg = duration / count if count else duration

    pacing = "fast" if avg < 1.5 else "medium" if avg < 3.0 else "slow"
    return {
        "count": count,
        "avg_interval_sec": round(avg, 2),
        "pacing": pacing,
    }


def analyze_speech(video_path: Path, duration: float) -> dict:
    """faster-whisper로 자막 추출."""
    from faster_whisper import WhisperModel

    # CPU 최적화된 small 모델 (첫 실행 시 자동 다운로드, 약 460MB)
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments_iter, _info = model.transcribe(
        str(video_path), language="ko", beam_size=1, vad_filter=True,
    )
    segments = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in segments_iter
    ]

    total_chars = sum(len(s["text"]) for s in segments)
    hook = next(
        (s["text"] for s in segments if s["end"] <= 4.0),
        segments[0]["text"] if segments else "",
    )
    cps = (total_chars / duration) if duration > 0 else 0.0

    return {
        "hook_text": hook,
        "total_chars": total_chars,
        "chars_per_sec": round(cps, 2),
        "segment_count": len(segments),
        "segments": segments[:30],  # 상위 30개만 보관
    }


def analyze_audio(video_path: Path) -> dict:
    """librosa로 BPM, RMS 추출."""
    import librosa
    import numpy as np

    y, sr = librosa.load(str(video_path), sr=22050, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    rms_mean = float(np.mean(librosa.feature.rms(y=y)))

    # 휴리스틱: 음량 있고 BPM 60-200 사이면 BGM 존재
    has_bgm = (rms_mean > 0.02) and (60 < float(tempo) < 200)

    return {
        "bpm": round(float(tempo), 1),
        "rms_mean": round(rms_mean, 4),
        "has_bgm": has_bgm,
    }


def analyze_thumbnail(video_path: Path) -> dict:
    """첫 프레임 추출해 dominant color 추출."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_MSEC, 500)  # 0.5초 지점
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return {"dominant_colors": []}

    small = cv2.resize(frame, (80, 80))
    pixels = small.reshape(-1, 3)
    # k-means 대신 더 가벼운 양자화
    quantized = (pixels // 32 * 32).astype(np.uint8)
    buckets = Counter(tuple(p) for p in quantized)
    top = buckets.most_common(3)
    colors = ["#%02x%02x%02x" % (c[2], c[1], c[0]) for (c, _) in top]  # BGR→RGB

    return {"dominant_colors": colors}


def analyze_one(video_path: Path) -> dict:
    vid = video_path.stem
    print(f"[analyze] {vid}")
    duration = probe_duration(video_path)

    return {
        "video_id": vid,
        "duration_sec": round(duration, 2),
        "cuts": analyze_cuts(video_path, duration),
        "speech": analyze_speech(video_path, duration),
        "audio": analyze_audio(video_path),
        "thumbnail": analyze_thumbnail(video_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", help="특정 video_id만 분석")
    ap.add_argument("--force", action="store_true", help="기존 분석 덮어쓰기")
    args = ap.parse_args()

    if args.video:
        targets = [VIDEOS_DIR / f"{args.video}.mp4"]
    else:
        targets = sorted(VIDEOS_DIR.glob("*.mp4"))

    if not targets:
        print("[skip] no videos found. Run download.py first.")
        return

    for vp in targets:
        if not vp.exists():
            print(f"[miss] {vp.name}")
            continue
        out = ANALYSIS_DIR / f"{vp.stem}.json"
        if out.exists() and not args.force:
            print(f"[skip] {vp.stem} (already analyzed)")
            continue
        try:
            result = analyze_one(vp)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  → {out.name}")
        except Exception as e:
            print(f"  [error] {vp.stem}: {e}")


if __name__ == "__main__":
    main()
