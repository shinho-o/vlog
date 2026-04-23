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


def run_ffmpeg(args: list[str]):
    r = subprocess.run(args, capture_output=True, text=True)
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

    # 1) 트림
    if trim_sec:
        print(f"[trim] → {trim_sec}s")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(video), "-t", str(trim_sec),
                    "-c", "copy", str(trimmed)])
    else:
        trimmed = video  # no-op

    # 2) 자막
    if captions:
        print("[captions] faster-whisper small (ko)")
        segs = transcribe(trimmed)
        srt = work / "captions.srt"
        write_srt(segs, srt)
        # ffmpeg subtitle filter: single-quote escape path
        srt_esc = str(srt).replace("\\", "/").replace(":", "\\:")
        vf = (
            f"subtitles='{srt_esc}':force_style="
            f"'FontName=Malgun Gothic,FontSize={font_size},"
            f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"Outline=2,Shadow=0,Alignment=2,MarginV={margin}'"
        )
        print(f"[burn] → {out}")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(trimmed), "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium",
                    "-c:a", "copy", str(out)])
    else:
        print(f"[copy] → {out}")
        run_ffmpeg(["ffmpeg", "-y", "-i", str(trimmed), "-c", "copy", str(out)])


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
