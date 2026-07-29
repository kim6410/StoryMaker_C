# -*- coding: utf-8 -*-
"""
단계10: 대표 썸네일 8종 후보 생성과 선택 저장을 담당하는 서비스 계층.
완성된 MP4에서 서로 다른 8개 시점의 프레임을 FFmpeg로 추출해 후보로 쓴다
(신규 외부 서비스·API 키 없음, app/media/renderer.py의 검증된 FFmpeg 경로만 재사용).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import JOBS_DIR, MP4_HEIGHT, MP4_WIDTH, to_absolute_path, to_relative_path
from app.db import repository as repo
from app.media import renderer

CANDIDATE_COUNT = 8


@dataclass
class ThumbnailOutcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""


USER_THUMBNAIL_ERROR_MESSAGES = {
    "mp4_not_ready": "먼저 영상(MP4) 제작을 완료해야 썸네일을 고를 수 있습니다.",
    "mp4_missing": "완성된 영상 파일을 찾을 수 없습니다. MP4를 다시 만들어 주세요.",
    "invalid_duration": "영상 길이를 확인할 수 없어 썸네일을 만들 수 없습니다.",
    "extract_failed": "썸네일 추출 중 오류가 발생했습니다. 다시 시도해 주세요.",
    "invalid_candidate": "선택한 썸네일 후보를 찾을 수 없습니다. 후보를 다시 만들어 주세요.",
    "candidates_not_ready": "먼저 썸네일 8종 후보를 만들어야 선택할 수 있습니다.",
}


def _thumb_dir(job_uid: str) -> Path:
    d = JOBS_DIR / job_uid / "media" / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _candidate_path(job_uid: str, index: int) -> Path:
    return _thumb_dir(job_uid) / f"cand_{index}.jpg"


def candidates_ready(job_uid: str) -> bool:
    return all(_candidate_path(job_uid, i).is_file() and _candidate_path(job_uid, i).stat().st_size > 0
               for i in range(CANDIDATE_COUNT))


def candidate_path(job_uid: str, index: int) -> Optional[Path]:
    if not (0 <= index < CANDIDATE_COUNT):
        return None
    p = _candidate_path(job_uid, index)
    return p if p.is_file() else None


def ensure_candidates(project: dict) -> ThumbnailOutcome:
    """완성된 MP4에서 서로 다른 8개 시점을 골라 후보 썸네일을 만든다.
    이미 8개가 모두 있으면 다시 만들지 않는다(불필요한 재작업 방지)."""
    project_id = project["id"]
    job_uid = project["job_uid"]

    if candidates_ready(job_uid):
        return ThumbnailOutcome(ok=True)

    mp4 = repo.get_mp4_for_project(project_id)
    if not mp4 or mp4["status"] != "success":
        return ThumbnailOutcome(ok=False, error_code="mp4_not_ready",
                                 error_message=USER_THUMBNAIL_ERROR_MESSAGES["mp4_not_ready"])

    video_path = to_absolute_path(mp4["relative_mp4_path"])
    if not video_path.is_file():
        return ThumbnailOutcome(ok=False, error_code="mp4_missing",
                                 error_message=USER_THUMBNAIL_ERROR_MESSAGES["mp4_missing"])

    duration = mp4["duration_seconds"] or 0.0
    if duration <= 0:
        return ThumbnailOutcome(ok=False, error_code="invalid_duration",
                                 error_message=USER_THUMBNAIL_ERROR_MESSAGES["invalid_duration"])

    # 시작·끝의 페이드 구간을 피해 5%~92% 구간을 8등분한다(서로 다른 장면이 걸리도록).
    lo, hi = duration * 0.05, duration * 0.92
    span = max(hi - lo, 0.1)
    for i in range(CANDIDATE_COUNT):
        t = lo + span * (i / (CANDIDATE_COUNT - 1))
        ok, err = renderer.extract_frame_at(video_path, t, _candidate_path(job_uid, i),
                                             width=MP4_WIDTH, height=MP4_HEIGHT)
        if not ok:
            return ThumbnailOutcome(ok=False, error_code="extract_failed",
                                     error_message=f"{USER_THUMBNAIL_ERROR_MESSAGES['extract_failed']} ({err})")
    return ThumbnailOutcome(ok=True)


def select_candidate(project: dict, user_id: int, index: int) -> ThumbnailOutcome:
    """선택한 후보를 대표 썸네일로 저장한다. 기존 대표 썸네일이 있으면 파일·DB 참조를
    함께 교체한다(항상 최대 1개만 활성 상태로 유지)."""
    job_uid = project["job_uid"]
    if not candidates_ready(job_uid):
        return ThumbnailOutcome(ok=False, error_code="candidates_not_ready",
                                 error_message=USER_THUMBNAIL_ERROR_MESSAGES["candidates_not_ready"])

    src = candidate_path(job_uid, index)
    if src is None:
        return ThumbnailOutcome(ok=False, error_code="invalid_candidate",
                                 error_message=USER_THUMBNAIL_ERROR_MESSAGES["invalid_candidate"])

    dest = _thumb_dir(job_uid) / f"selected_{secrets.token_hex(5)}.jpg"
    dest.write_bytes(src.read_bytes())
    new_relative_path = to_relative_path(dest)

    old_relative_paths = repo.save_primary_thumbnail(
        project["id"], user_id, new_relative_path, dest.stat().st_size,
    )
    for rel in old_relative_paths:
        if rel == new_relative_path:
            continue
        old_abs = to_absolute_path(rel)
        old_abs.unlink(missing_ok=True)
    return ThumbnailOutcome(ok=True)
