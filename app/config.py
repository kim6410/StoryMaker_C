# -*- coding: utf-8 -*-
"""
StoryMaker Claude Lab 중앙 설정 모듈.
프로젝트 루트와 모든 하위 경로를 이 파일 한 곳에서만 계산한다.
다른 모듈은 경로를 직접 조립하지 말고 이 모듈의 상수를 가져다 쓴다.
"""
from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv

# app/config.py -> app/ -> 프로젝트 루트
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 공용 환경설정 파일 위치(config/.env). 다른 세션과 공유하는 단일 설정 파일이다.
load_dotenv(PROJECT_ROOT / "config" / ".env")

DATA_DIR = PROJECT_ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
MEDIA_DIR = DATA_DIR / "media"
LOGS_DIR = PROJECT_ROOT / "logs"
BACKUPS_DIR = PROJECT_ROOT / "backups"

# 공용 배경음악 라이브러리. 용량을 줄이기 위해 data/ 안으로 복사하지 않고
# runtime/music/mp3를 읽기 전용으로 그대로 참조한다.
MUSIC_LIBRARY_DIR = PROJECT_ROOT / "runtime" / "music" / "mp3"

# 미디어 처리 실행 파일은 시스템 전역 PATH에 의존하지 않고 프로젝트 전용 경로를 사용한다.
FFMPEG_DIR = PROJECT_ROOT / "runtime" / "ffmpeg" / "bin"
FFPROBE_PATH = FFMPEG_DIR / "ffprobe.exe"
FFMPEG_PATH = FFMPEG_DIR / "ffmpeg.exe"

DB_PATH = DATA_DIR / "storymaker_claude.db"

# Gemini 연동. 값이 config/.env에 없으면 OS 환경변수(예: 다른 세션이 설정한
# 사용자 수준 GEMINI_API_KEY)를 그대로 사용한다 - load_dotenv는 기존 환경변수를
# 덮어쓰지 않는다.
import os as _os

GEMINI_API_KEY = _os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = _os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_REQUEST_TIMEOUT_SECONDS = 45

# 단계7: TTS(Supertonic, 공개 오픈소스 pip 패키지). 모델 가중치는 최초 실행 시
# Hugging Face에서 이 프로젝트 전용 캐시 경로로만 내려받는다(V1·Beta 모델 복사 없음).
SUPERTONIC_MODEL_DIR = PROJECT_ROOT / "runtime" / "models" / "supertonic"
SUPERTONIC_VOICE_FEMALE = _os.environ.get("SUPERTONIC_VOICE_FEMALE") or "F1"
SUPERTONIC_VOICE_MALE = _os.environ.get("SUPERTONIC_VOICE_MALE") or "M1"
SUPERTONIC_DEFAULT_SPEED = 1.0
SUPERTONIC_SENTENCE_GAP_SECONDS = 0.4

# 단계8: FFmpeg MP4 렌더. 폰트는 프로젝트 전용 경로에 직접 내려받아 사용한다
# (OS 폰트나 V1·Beta 자산을 참조하지 않는다. 오픈폰트 라이선스, 출처는 runtime/fonts/OFL.txt).
MP4_WIDTH = 1080
MP4_HEIGHT = 1920
MP4_FPS = 30
MP4_START_LEAD_SECONDS = 1.5   # 배경음악 페이드인 구간, 이 시간이 지난 뒤 TTS 시작
MP4_END_HOLD_SECONDS = 2.0     # 마지막 TTS 종료 후 배경음악 페이드아웃 + 엔딩 카드 유지 시간
MP4_TRANSITION_MAX_SECONDS = 2.5
FONT_BOLD_PATH = PROJECT_ROOT / "runtime" / "fonts" / "NanumGothic-Bold.ttf"
FONT_REGULAR_PATH = PROJECT_ROOT / "runtime" / "fonts" / "NanumGothic-Regular.ttf"
# TTS 발화 구간 배경음악 음량(덕킹, 선형 배율) / 무음(리드인·엔딩) 구간 음량 3단계
MUSIC_DUCKED_VOLUME = {"quiet": 0.08, "normal": 0.14, "loud": 0.20}
MUSIC_SOLO_VOLUME = {"quiet": 0.30, "normal": 0.45, "loud": 0.60}

for _d in (DATA_DIR, JOBS_DIR, MEDIA_DIR, LOGS_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def to_relative_path(absolute_path: Path | str) -> str:
    """DB에 저장할 때는 항상 PROJECT_ROOT 기준 상대경로 문자열로 변환한다."""
    p = Path(absolute_path).resolve()
    return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")


class PathEscapeError(ValueError):
    """DB나 요청에서 온 상대경로가 '..' 등으로 PROJECT_ROOT 밖을 가리킬 때 발생시킨다."""


def to_absolute_path(relative_path: str) -> Path:
    """DB에서 읽은 상대경로를 실제 파일 접근용 절대경로로 복원한다.
    '..'나 절대경로가 섞여 PROJECT_ROOT 밖을 가리키면 즉시 차단한다(경로 이탈 방지)."""
    candidate = (PROJECT_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PathEscapeError(f"path escapes PROJECT_ROOT: {relative_path!r} -> {candidate}") from None
    return candidate
