# Vlog 편집 스타일 학습 파이프라인

한국 브이로그 쇼츠의 편집 패턴을 학습해 **내 영상 자동 편집의 지침서**로 사용.

---

## 흐름

```
collect.py   → Supabase vlog_videos (메타 수집, KR 가중)
download.py  → data/videos/{id}.mp4    (yt-dlp, 상위 반응 N개)
analyze.py   → data/analysis/{id}.json (컷·자막·BGM·색상)
insights.py  → data/insights/YYYY-MM-DD.md (Claude 요약 지침서)
editor.py    → (예정) 내 원본 + insights md → 편집된 쇼츠
```

---

## 최초 셋업

```bash
# 로컬 파이프라인(무거운 ML 패키지 포함) — requirements.txt 는 Render 배포용(경량)
pip install -r requirements-local.txt

# ffmpeg 필수 (PATH 에 있어야 함)
#   Windows: scoop install ffmpeg  또는  choco install ffmpeg
#   macOS  : brew install ffmpeg
#   Linux  : apt install ffmpeg

# .env 필요한 키
#   YOUTUBE_API_KEY= ...
#   SUPABASE_URL=    ...
#   SUPABASE_KEY=    ...
#   ANTHROPIC_API_KEY= ...  (없으면 insights 는 숫자만 채워 출력)
```

---

## 실행 예

**일일 파이프라인 (크론화 가능):**
```bash
python collect.py                    # 메타데이터 수집
python download.py --top 10          # 상위 10개 다운로드
python analyze.py                    # 신규 영상 분석
python insights.py                   # 오늘자 지침서 생성
```

**특정 영상만 재분석:**
```bash
python analyze.py --video ABC123xyz --force
```

**특정 날짜 지침서 다시 만들기:**
```bash
python insights.py --date 2026-04-22
```

---

## 산출물 구조

```
data/
├── videos/
│   └── {video_id}.mp4            # 다운로드 원본 (크기 주의)
├── analysis/
│   └── {video_id}.json           # 개별 영상 분석
└── insights/
    └── 2026-04-23.md             # 일일 편집 지침서 (editor.py 입력)
```

각 `analysis/*.json` 스키마:
```json
{
  "video_id": "abc",
  "duration_sec": 58.3,
  "cuts":     { "count": 32, "avg_interval_sec": 1.82, "pacing": "fast" },
  "speech":   { "hook_text": "...", "chars_per_sec": 4.1, "segments": [...] },
  "audio":    { "bpm": 98.4, "rms_mean": 0.12, "has_bgm": true },
  "thumbnail":{ "dominant_colors": ["#f4d1a1", "#2b2b2b", "#e6e6e6"] }
}
```

각 `insights/*.md` 는 상단 **YAML frontmatter** 에 숫자 파라미터가 들어있어
`editor.py` 가 그대로 파싱해 편집에 적용한다.

```yaml
---
date: 2026-04-23
cut_interval_mean: 1.82
chars_per_sec_mean: 4.1
bpm_mean: 98.4
top_colors: ['#f4d1a1', '#2b2b2b', '#e6e6e6']
---
```

---

## Phase 다음 단계 (예정)

### editor.py
- 입력: 내 원본 영상 + 최신 insights md
- 자동 적용:
  - scene detect → 평균 컷 간격에 맞춰 자동 컷
  - Whisper STT → 자막 생성 (글자수·위치 스타일은 md 파라미터)
  - BGM 추가 (BPM 대역 매칭)
  - 색보정 (top_colors 톤 맞추기)
- CLI 옵션으로 각 단계 **개별 off / 수동 오버라이드** 가능

### uploader.py / UI
- 내 원본 영상 업로드 간단 폼
- 편집 결과 프리뷰 + 디테일 수동 조정 (컷 시점·자막 텍스트·BGM 바꾸기)

---

## 주의

- `faster-whisper small` 모델은 첫 실행 시 **약 460MB** 자동 다운로드
- Whisper + librosa + scenedetect 모두 CPU 에서 동작하지만 영상 1개당 **1-3분** 소요
- Render 무료/유료 Tier 에서는 안 돌림 — 로컬 Windows/Mac 에서 크론 실행 권장
