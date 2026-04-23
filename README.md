# Vlog Trend & Editor

한국 유튜브 브이로그 트렌드 수집 · 편집 스타일 분석 · 자동 편집기를 한 서버에
묶은 Flask 대시보드. Render 배포본(`vlog-trend.onrender.com`)은 **수집·대시보드
전용**이고, 자동 편집은 로컬(데스크탑/노트북)에서 돌려야 한다.

---

## 기능

| 경로 | 하는 일 | 실행 환경 |
|---|---|---|
| `/` | YouTube 쇼츠 수집·통계·채널/쿼리 관리·조회수 예측 | Render ✅ / 로컬 ✅ |
| `/insights` | 일일 편집 지침서 (md) 리스트 & 상세 보기 | Render ✅ / 로컬 ✅ |
| `/editor` | 원본 영상 업로드 → 자동 자막 + 트림 → 편집본 다운로드 | **로컬 전용** (Whisper·ffmpeg 필요) |

---

## 다른 컴퓨터에서 셋업하기

### 1. 필수 프로그램

| | Windows | macOS | Linux |
|---|---|---|---|
| Python 3.10+ | [python.org](https://www.python.org/downloads/) | `brew install python@3.11` | `sudo apt install python3` |
| ffmpeg | `winget install Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| git | [git-scm.com](https://git-scm.com/) | `brew install git` | `sudo apt install git` |

설치 후 터미널 재시작 → `ffmpeg -version`, `python --version` 동작 확인.

### 2. 리포 clone + 의존성

```bash
git clone https://github.com/shinho-o/vlog.git
cd vlog

# 로컬 전체 (편집 기능 포함)
pip install -r requirements-local.txt

# 또는 웹 UI만 (편집 기능 제외, 가벼움)
pip install -r requirements.txt
```

### 3. 환경변수 설정

`.env` 파일을 루트에 만들고 본인 키 채우기:

```
YOUTUBE_API_KEY=...       # Google Cloud Console에서 발급
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=...          # service_role key
ANTHROPIC_API_KEY=...     # 편집 지침서 요약용 (없으면 숫자만 출력)
```

### 4. 실행

```bash
python dashboard.py
# → http://localhost:5000/
```

메인 페이지 헤더에 **편집 지침서** · **영상 편집** 버튼 뜨면 정상.

---

## 편집 기능 사용법

### 웹 UI (`/editor`)
1. mp4/mov/webm 업로드
2. 옵션: 트림 길이(초), 자막 크기/여백, 자동 자막 on/off
3. "편집 시작" → 1-5분 처리 → 결과 다운로드

### CLI (동일 기능)
```bash
python editor.py my_clip.mp4                       # 자동 자막 + 원본 길이
python editor.py my_clip.mp4 --trim 60             # 60초로 트림
python editor.py my_clip.mp4 --no-captions         # 자막 생략
python editor.py my_clip.mp4 --font-size 52 --margin 120
```

결과물은 `data/edited/<id>_<name>_edited.mp4` 로 저장됨.

### 첫 실행 주의
- faster-whisper **'small' 모델 460MB** 자동 다운로드
- 영상 1개당 **1-3분** (CPU i5/i7 기준, 30초 영상)
- 디스크 **2GB+ 여유** 필요

---

## 트렌드 분석 파이프라인 (선택)

`insights.md` 를 실제로 채우려면 별도 4단계 파이프라인 실행. 상세는
[PIPELINE.md](./PIPELINE.md) 참고.

```bash
python collect.py                 # Supabase 에 쇼츠 메타 수집
python download.py --top 10       # 상위 반응 10개 mp4 다운
python analyze.py                 # 컷·자막·BGM 분석 → data/analysis/*.json
python insights.py                # Claude 요약 → data/insights/YYYY-MM-DD.md
```

---

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `ffmpeg: command not found` | PATH 누락. 설치 후 터미널 재시작 또는 절대경로 지정 |
| 첫 편집이 너무 오래 걸림 | Whisper 모델 다운로드 중. 460MB 한 번만 받으면 이후부터 빠름 |
| `No space left on device` | `data/videos/`, `data/edited/`, `data/uploads/` 용량 정리 |
| Render 배포에서 `/editor` 실패 | 정상 — Render 무료 티어는 메모리 부족으로 편집 불가. 로컬에서 돌릴 것 |
| `MODULE_NOT_FOUND: faster_whisper` | `requirements-local.txt`로 설치했는지 확인 (requirements.txt 만으로는 안 됨) |

---

## 구조

```
vlog/
├── dashboard.py          Flask 앱 (라우트 전부)
├── collect.py            YouTube Shorts 수집기
├── download.py           상위 반응 영상 yt-dlp 다운
├── analyze.py            scene detect + Whisper + librosa 분석
├── insights.py           Claude 요약 → 일일 편집 지침서 md
├── editor.py             ffmpeg 트림 + 자막 번인
├── predictor.py          조회수 예측 모델
├── templates/            Jinja2 HTML
├── data/
│   ├── videos/           (gitignore) 다운받은 쇼츠
│   ├── analysis/         (gitignore) 개별 영상 분석 JSON
│   ├── uploads/          (gitignore) 편집기 업로드 원본
│   ├── edited/           (gitignore) 편집 결과
│   └── insights/         일일 편집 지침서 md (커밋 O)
├── requirements.txt       Render 배포용 (웹 서버만)
├── requirements-local.txt 로컬용 (+ ML 파이프라인)
└── .env                   (gitignore) API 키
```
