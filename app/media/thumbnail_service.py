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


_HEADLINE_CHARS_PER_LINE = 13
_HEADLINE_MAX_LINES = 2


def _thumb_dir(job_uid: str) -> Path:
    d = JOBS_DIR / job_uid / "media" / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _wrap_headline(title: str) -> str:
    """FFmpeg drawtext는 자동 줄바꿈이 없으므로 글자 수 기준으로 최대 2줄까지 직접
    나누고, 그래도 넘치면 말줄임표로 축약한다(V1·Beta의 fitText류 자동 축소를 폰트 크기
    동적 계산 대신 글자수 기준으로 단순화해 재구현 - FFmpeg에는 텍스트 폭 측정 API가 없음)."""
    words = title.split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for w in words:
        candidate = f"{current} {w}".strip()
        if len(candidate) > _HEADLINE_CHARS_PER_LINE and current:
            if len(lines) == _HEADLINE_MAX_LINES:
                break
            lines.append(current)
            consumed += len(current.split())
            current = w
        else:
            current = candidate
    if current and len(lines) < _HEADLINE_MAX_LINES:
        lines.append(current)
        consumed += len(current.split())

    # 단어 단위로도 한 줄을 못 채우는 경우(공백 없는 긴 문자열 등) 글자수로 강제 절단한다.
    lines = [(line if len(line) <= _HEADLINE_CHARS_PER_LINE else line[:_HEADLINE_CHARS_PER_LINE])
             for line in lines[:_HEADLINE_MAX_LINES]]

    if consumed < len(words) or (lines and len(lines[-1]) > _HEADLINE_CHARS_PER_LINE):
        last = lines[-1] if lines else ""
        if len(last) >= _HEADLINE_CHARS_PER_LINE:
            last = last[:_HEADLINE_CHARS_PER_LINE - 1]
        lines[-1] = last.rstrip() + "…"

    return "\n".join(lines)


def _pick_thumbnail_headline(project: dict) -> str:
    """우선순위: 쇼츠용 핵심 제목 > SNS 결과 중 대표 제목(네이버 블로그) > 그 외 채널 제목
    > 기초 콘텐츠(제작 주제)에서 추출한 짧은 문구. 화면 밖으로 넘치지 않도록 줄바꿈·축약한다."""
    import json
    from app.constants import CHANNEL_NAVER_BLOG, CHANNEL_SHORTFORM_SCRIPT

    rows = {r["channel_code"]: r for r in repo.list_channel_results_for_project(project["id"])}
    title = ""
    shortform = rows.get(CHANNEL_SHORTFORM_SCRIPT)
    if shortform and shortform.get("title"):
        title = shortform["title"]
    if not title:
        naver = rows.get(CHANNEL_NAVER_BLOG)
        if naver and naver.get("title"):
            title = naver["title"]
    if not title:
        title = next((r["title"] for r in rows.values() if r and r.get("title")), "")
    if not title:
        snapshot = json.loads(project.get("input_snapshot_json") or "{}")
        title = snapshot.get("topic", "")

    return _wrap_headline((title or "").strip())


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

    headline = _pick_thumbnail_headline(project)
    texts_dir = JOBS_DIR / job_uid / "media" / "text"

    # 시작·끝의 페이드 구간을 피해 5%~92% 구간을 8등분한다(서로 다른 장면이 걸리도록).
    lo, hi = duration * 0.05, duration * 0.92
    span = max(hi - lo, 0.1)
    for i in range(CANDIDATE_COUNT):
        t = lo + span * (i / (CANDIDATE_COUNT - 1))
        ok, err = renderer.extract_thumbnail_candidate(
            video_path, t, _candidate_path(job_uid, i), texts_dir, i, headline,
            width=MP4_WIDTH, height=MP4_HEIGHT,
        )
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
