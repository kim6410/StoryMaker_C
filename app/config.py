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

for _d in (DATA_DIR, JOBS_DIR, MEDIA_DIR, LOGS_DIR, BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def to_relative_path(absolute_path: Path | str) -> str:
    """DB에 저장할 때는 항상 PROJECT_ROOT 기준 상대경로 문자열로 변환한다."""
    p = Path(absolute_path).resolve()
    return str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")


def to_absolute_path(relative_path: str) -> Path:
    """DB에서 읽은 상대경로를 실제 파일 접근용 절대경로로 복원한다."""
    return (PROJECT_ROOT / relative_path).resolve()
