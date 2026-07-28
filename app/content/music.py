# -*- coding: utf-8 -*-
"""배경음악 목록/스트리밍. runtime/music/mp3를 읽기 전용으로만 참조하고
data/ 안으로 복사하지 않는다(용량 절약, 원본은 단일 소스로 유지).

DB 접근은 app.db.repository를 통해서만 하고, 이 모듈에서 SQL을 직접 실행하지 않는다."""
from __future__ import annotations

from pathlib import Path

from app.config import MUSIC_LIBRARY_DIR, PROJECT_ROOT
from app.db import repository as repo


def list_music_files(include_duplicates: bool = False) -> list[dict]:
    rows = repo.list_music_catalog(exclude_duplicates=not include_duplicates)
    if rows:
        return [
            {
                "name": r["filename"].rsplit(".", 1)[0],
                "relative_path": r["relative_path"],
                "size_mb": round(r["size_bytes"] / 1024 / 1024, 1),
                "duration_seconds": r["duration_seconds"],
            }
            for r in rows
        ]
    return _list_from_filesystem()


def _list_from_filesystem() -> list[dict]:
    """카탈로그가 아직 스캔되지 않았을 때의 임시 폴백. scan_music_catalog 실행을 권장한다."""
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
            "name": path.stem, "relative_path": rel,
            "size_mb": round(size_bytes / 1024 / 1024, 1), "duration_seconds": 0,
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
