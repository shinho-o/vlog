"""
간단 영상 편집기 — 원본 영상 → 자막 자동 생성 + 번인 + 길이 트림.

분석 파이프라인의 첫 editor 버전. 이후 insights.md의 파라미터(컷 간격·
BGM BPM 등)를 옵션으로 오버라이드 가능하도록 확장 예정.

사용:
    python editor.py input.mp4
    python editor.py input.mp4 --out result.mp4 --trim 60
    python editor.py input.mp4 --no-captions        # 자막 생성 생략
    python editor.py input.mp4 --font-size 52       # 자막 크기
    python editor.py input.mp4 --margin 120         # 하단 여백(px)
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUT_DIR = SCRIPT_DIR / "data" / "edited"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def transcribe(video: Path) -> list[dict]:
    """faster-whisper로 음성→자막 세그먼트."""
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(video), language="ko", beam_size=1, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]


def write_srt(segments: list[dict], path: Path):
    def ts(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        if not seg["text"]:
            continue
        lines.append(str(i))
        lines.append(f"{ts(seg['start'])} --> {ts(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _find_korean_font() -> str | None:
    """Windows/Mac/Linux 에 한국어 폰트 탐색."""
    candidates = [
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\NanumGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _escape_drawtext(text: str) -> str:
    """ffmpeg drawtext 값에 쓰는 특수문자 escape."""
    return (text
            .replace("\\", r"\\")
            .replace(":", r"\:")
            .replace("'", r"\'")
            .replace(",", r"\,")
            .replace("%", r"\%"))


def build_drawtext_filter(segments: list[dict], font_size: int,
                          margin: int, font_path: str | None) -> str:
    """Whisper 세그먼트를 drawtext 필터 체인으로 변환.
    subtitles 필터 경로 문제를 우회하기 위함.
    """
    ff_font = None
    if font_path:
        # ffmpeg 필터 안의 경로: 백슬래시→슬래시, 콜론 이스케이프
        ff_font = font_path.replace("\\", "/").replace(":", r"\:")

    filters = []
    for seg in segments:
        if not seg["text"]:
            continue
        text = _escape_drawtext(seg["text"])
        parts = [
            f"drawtext=text='{text}'",
            f"fontsize={font_size}",
            "fontcolor=white",
            "borderw=3", "bordercolor=black",
            "x=(w-text_w)/2",
            f"y=h-{margin}",
            f"enable='between(t\\,{seg['start']:.2f}\\,{seg['end']:.2f})'",
        ]
        if ff_font:
            parts.append(f"fontfile='{ff_font}'")
        filters.append(":".join(parts))
    return ",".join(filters)


def run_ffmpeg(args: list[str], cwd: str | None = None):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(r.stderr[-800:], file=sys.stderr)
        raise RuntimeError(f"ffmpeg exit {r.returncode}")


def edit(
    video: Path,
    out: Path,
    trim_sec: float | None,
    captions: bool,
    font_size: int,
    margin: int,
):
    work = Path(tempfile.mkdtemp(prefix="vlog_edit_"))
    trimmed = work / "trimmed.mp4"

    # 1) 트림 (copy 대신 H.264 재인코딩 — Windows 기본 플레이어 호환)
    if trim_sec:
        print(f"[trim] → {trim_sec}s")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(video), "-t", str(trim_sec),
                    "-c:v", "libx264", "-preset", "fast",
                    "-c:a", "aac", str(trimmed)])
    else:
        trimmed = video  # no-op

    # 2) 자막 (drawtext 필터로 구성 — subtitles 필터 경로 문제 우회)
    if captions:
        print("[captions] faster-whisper small (ko)")
        segs = transcribe(trimmed)
        non_empty = [s for s in segs if s.get("text")]
        if not non_empty:
            print("[captions] no speech detected — re-encode only")
            run_ffmpeg(["ffmpeg", "-y", "-i", str(trimmed),
                        "-c:v", "libx264", "-preset", "fast",
                        "-c:a", "aac", str(out)])
            return

        # 원본 검증용 SRT 도 저장 (디버그용)
        write_srt(non_empty, work / "captions.srt")

        font_path = _find_korean_font()
        if not font_path:
            print("[warn] 한국어 폰트를 찾지 못함 — 기본 폰트 사용 (한글 네모 표시 가능)")

        vf = build_drawtext_filter(non_empty, font_size, margin, font_path)
        print(f"[burn] {len(non_empty)} segments → {out}")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(trimmed), "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium",
                    "-c:a", "copy", str(out)])
    else:
        print(f"[encode H.264] → {out}")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(trimmed),
                    "-c:v", "libx264", "-preset", "fast",
                    "-c:a", "aac", str(out)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", help="출력 경로 (기본: data/edited/<name>_edited.mp4)")
    ap.add_argument("--trim", type=float, help="N초로 트림")
    ap.add_argument("--no-captions", action="store_true", help="자막 생성 생략")
    ap.add_argument("--font-size", type=int, default=48)
    ap.add_argument("--margin", type=int, default=100, help="자막 하단 여백 px")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"[ERROR] {video} not found", file=sys.stderr)
        sys.exit(1)

    out = Path(args.out) if args.out else OUT_DIR / f"{video.stem}_edited.mp4"

    edit(
        video, out,
        trim_sec=args.trim,
        captions=not args.no_captions,
        font_size=args.font_size,
        margin=args.margin,
    )
    print(f"[done] {out}")


if __name__ == "__main__":
    main()
