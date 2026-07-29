# -*- coding: utf-8 -*-
"""
단계10A: 제작 흐름 공통 단계표시기 계산.
projects.status(+실패 시 error_code)만으로 화면에 보여줄 6단계 상태를 계산한다.
라우터·템플릿은 이 함수 하나만 사용하고 상태 문자열을 직접 비교하지 않는다."""
from __future__ import annotations

from app.constants import (
    GEMINI_ERROR_CODES,
    MP4_ERR_AUDIO_MIX_FAILED,
    MP4_ERR_CONCAT_FAILED,
    MP4_ERR_MUX_FAILED,
    MP4_ERR_NO_TTS,
    MP4_ERR_SCENE_RENDER_FAILED,
    MP4_ERR_VERIFY_FAILED,
    SRT_ERR_DRIFT_EXCEEDED,
    SRT_ERR_INCOMPLETE_AUDIO,
    SRT_ERR_NO_SENTENCES,
    TTS_ERROR_CODES,
)

STEP_DEFS = [
    {"key": "info", "label": "정보 입력"},
    {"key": "generate", "label": "AI 원고 생성"},
    {"key": "channels", "label": "SNS 8채널 확인"},
    {"key": "tts", "label": "음성·자막 생성"},
    {"key": "mp4", "label": "영상(MP4) 제작"},
    {"key": "done", "label": "완료·보관함"},
]

_STATUS_STEP_INDEX = {
    "draft": 0, "queued": 0,
    "prompting": 1, "generating": 1, "validating": 1,
    "content_ready": 2,
    "tts_ready": 3, "subtitle_ready": 3,
    "media_ready": 4, "rendering": 4,
    "completed": 5,
}

_MP4_ERR_CODES = {MP4_ERR_NO_TTS, MP4_ERR_SCENE_RENDER_FAILED, MP4_ERR_CONCAT_FAILED,
                   MP4_ERR_AUDIO_MIX_FAILED, MP4_ERR_MUX_FAILED, MP4_ERR_VERIFY_FAILED}
_SRT_ERR_CODES = {SRT_ERR_NO_SENTENCES, SRT_ERR_INCOMPLETE_AUDIO, SRT_ERR_DRIFT_EXCEEDED}


def _failed_step_index(error_code: str) -> int:
    """실패 오류코드의 접두 영역으로 어느 단계에서 멈췄는지 추정한다(정확한 실패 시점을
    별도로 기록하지 않으므로 최선 추정치다)."""
    if error_code in GEMINI_ERROR_CODES:
        return 1
    if error_code in TTS_ERROR_CODES or error_code in _SRT_ERR_CODES:
        return 3
    if error_code in _MP4_ERR_CODES:
        return 4
    return 1


def build_step_states(project: dict) -> list[dict]:
    status = project.get("status", "draft")
    error_code = project.get("error_code") or ""
    failed = status == "failed"
    current_index = _failed_step_index(error_code) if failed else _STATUS_STEP_INDEX.get(status, 0)

    is_completed = status == "completed"
    steps = []
    for i, d in enumerate(STEP_DEFS):
        if is_completed:
            state = "done"
        elif failed and i == current_index:
            state = "failed"
        elif i < current_index:
            state = "done"
        elif i == current_index:
            state = "current"
        else:
            state = "pending"
        steps.append({"key": d["key"], "label": d["label"], "state": state})
    return steps
