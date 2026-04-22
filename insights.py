"""
data/analysis/ 의 영상별 JSON 을 집계해 일일 "편집 지침서" md 를 생성.

- 숫자 통계는 로컬에서 계산 (평균·분산)
- 질감 있는 요약 및 훅 패턴 분류는 Claude API 에 위임
- editor.py 가 이 md 의 frontmatter / 파라미터 섹션을 파싱해 편집에 적용

사용:
    python insights.py                 # 오늘자
    python insights.py --date 2026-04-23
"""
import argparse
import json
import os
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

ANALYSIS_DIR = SCRIPT_DIR / "data" / "analysis"
INSIGHTS_DIR = SCRIPT_DIR / "data" / "insights"
INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)


def load_today(target_date: str) -> list[dict]:
    """target_date(YYYY-MM-DD) 에 수정된 분석 JSON 전부 로드."""
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    items = []
    for p in ANALYSIS_DIR.glob("*.json"):
        mtime = date.fromtimestamp(p.stat().st_mtime)
        if mtime == target:
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return items


def aggregate(items: list[dict]) -> dict:
    cut_intervals = [i["cuts"]["avg_interval_sec"] for i in items if "cuts" in i]
    chars_per_sec = [i["speech"]["chars_per_sec"] for i in items if "speech" in i]
    bpms = [i["audio"]["bpm"] for i in items if i.get("audio", {}).get("has_bgm")]
    pacings = Counter(i["cuts"]["pacing"] for i in items)

    colors: Counter = Counter()
    for i in items:
        for c in i.get("thumbnail", {}).get("dominant_colors", []):
            colors[c] += 1

    hooks = [i["speech"]["hook_text"] for i in items if i.get("speech", {}).get("hook_text")]

    def stat(xs):
        if not xs:
            return {"mean": None, "median": None, "min": None, "max": None}
        return {
            "mean": round(statistics.mean(xs), 2),
            "median": round(statistics.median(xs), 2),
            "min": round(min(xs), 2),
            "max": round(max(xs), 2),
        }

    return {
        "video_count": len(items),
        "cut_interval_sec": stat(cut_intervals),
        "chars_per_sec": stat(chars_per_sec),
        "bpm": stat(bpms),
        "pacing_distribution": dict(pacings),
        "top_colors": [c for c, _ in colors.most_common(5)],
        "hooks": hooks[:30],
    }


def claude_summarize(agg: dict) -> str:
    """Claude 에 훅 패턴 분류 + 실행 지침 요약 요청."""
    import anthropic

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        # 키 없으면 로컬 숫자만 채운 기본 요약 반환
        return _fallback_summary(agg)

    client = anthropic.Anthropic(api_key=key)
    prompt = f"""다음은 최근 반응 좋은 한국 브이로그 쇼츠 {agg['video_count']}개의 편집 스타일 집계 데이터입니다.
편집자가 바로 따라할 수 있는 **1주치 편집 지침서**를 작성하세요.

[집계]
- 컷 평균 간격: 평균 {agg['cut_interval_sec']['mean']}초 (중앙 {agg['cut_interval_sec']['median']})
- 자막 밀도(초당 글자): 평균 {agg['chars_per_sec']['mean']}자
- 페이싱 분포: {agg['pacing_distribution']}
- BGM BPM 평균: {agg['bpm']['mean']}
- 썸네일 dominant 컬러 top5: {agg['top_colors']}

[훅 텍스트 샘플]
{chr(10).join('- ' + h for h in agg['hooks'][:20])}

작성 항목(한국어, 각 섹션 3~5줄):
## 훅 패턴 분석
(질문형/선언형/감탄사 비율 추정과 평균 글자수, 좋은 훅 공식 1~2개)

## 페이싱·컷
(초당 몇 컷, 점프컷/매치컷 활용 방향)

## 자막
(권장 위치·글자수·폰트 스타일)

## BGM
(장르·BPM 범위, 볼륨 톤)

## 이번주 편집자 체크리스트
(- 로 시작하는 4~6개 액션 아이템)
"""
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _fallback_summary(agg: dict) -> str:
    return f"""## 훅 패턴 분석
수집 영상 {agg['video_count']}개의 훅 텍스트 샘플은 `## Raw Hook Samples` 섹션 참고.

## 페이싱·컷
평균 컷 간격 {agg['cut_interval_sec']['mean']}초. 분포: {agg['pacing_distribution']}.

## 자막
초당 평균 {agg['chars_per_sec']['mean']}자.

## BGM
평균 BPM {agg['bpm']['mean']}.

## 이번주 편집자 체크리스트
- ANTHROPIC_API_KEY 를 .env 에 넣어 더 자세한 지침 생성
"""


def write_markdown(target_date: str, agg: dict, summary: str) -> Path:
    out = INSIGHTS_DIR / f"{target_date}.md"

    # YAML frontmatter — editor.py 가 파싱해 사용할 파라미터
    fm = f"""---
date: {target_date}
video_count: {agg['video_count']}
cut_interval_mean: {agg['cut_interval_sec']['mean']}
cut_interval_median: {agg['cut_interval_sec']['median']}
chars_per_sec_mean: {agg['chars_per_sec']['mean']}
bpm_mean: {agg['bpm']['mean']}
top_colors: {agg['top_colors']}
---
"""
    hooks_block = "\n".join(f"- {h}" for h in agg["hooks"][:20]) or "- (샘플 없음)"

    body = f"""# 편집 지침서 — {target_date}

수집 영상 **{agg['video_count']}개** 분석 요약.

{summary}

---

## 집계 데이터

| 지표 | 평균 | 중앙값 | 최소 | 최대 |
|---|---:|---:|---:|---:|
| 컷 간격 (초) | {agg['cut_interval_sec']['mean']} | {agg['cut_interval_sec']['median']} | {agg['cut_interval_sec']['min']} | {agg['cut_interval_sec']['max']} |
| 자막 초당 글자 | {agg['chars_per_sec']['mean']} | {agg['chars_per_sec']['median']} | {agg['chars_per_sec']['min']} | {agg['chars_per_sec']['max']} |
| BGM BPM | {agg['bpm']['mean']} | {agg['bpm']['median']} | {agg['bpm']['min']} | {agg['bpm']['max']} |

페이싱 분포: {agg['pacing_distribution']}

썸네일 dominant 컬러 (top5): {' '.join(agg['top_colors'])}

## Raw Hook Samples
{hooks_block}
"""

    out.write_text(fm + body, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()

    items = load_today(args.date)
    if not items:
        print(f"[skip] no analysis JSONs for {args.date}. Run analyze.py first.")
        return

    print(f"[aggregate] {len(items)} analyses for {args.date}")
    agg = aggregate(items)

    print("[claude] summarizing...")
    summary = claude_summarize(agg)

    path = write_markdown(args.date, agg, summary)
    print(f"[done] wrote {path}")


if __name__ == "__main__":
    main()
