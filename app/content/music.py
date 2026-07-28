# -*- coding: utf-8 -*-
"""배경음악 목록/스트리밍. runtime/music/mp3를 읽기 전용으로만 참조하고
data/ 안으로 복사하지 않는다(용량 절약, 원본은 단일 소스로 유지)."""
from __future__ import annotations

from pathlib import Path

from app.config import MUSIC_LIBRARY_DIR, PROJECT_ROOT


def list_music_files() -> list[dict]:
    if not MUSIC_LIBRARY_DIR.is_dir():
        return []
    items = []
    for path in sorted(MUSIC_LIBRARY_DIR.glob("*.mp3")):
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        items.append({
            "name": path.stem,
            "relative_path": rel,
            "size_mb": round(size_bytes / 1024 / 1024, 1),
        })
    return items


def resolve_music_path(relative_path: str) -> Path | None:
    """사용자가 선택한 상대경로를 실제 파일로 안전하게 변환한다(경로 이탈 방지)."""
    if not relative_path:
        return None
    candidate = (PROJECT_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(MUSIC_LIBRARY_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
