# -*- coding: utf-8 -*-
"""
6A단계 시험용 출력 계약 검증기.

Gemini 응답을 화면에 바로 꽂지 않고, 여기서 JSON 파싱 -> 필수 필드 -> 타입 ->
최대 길이 -> 빈 필드 -> 금지 정보(API 키·내부 경로·시스템 규칙 유출) 순서로
검증한다(작업지시 8장). 하나라도 실패하면 결과를 저장하지 않는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.constants import (
    CHANNEL_CODES,
    CHANNEL_SHORTFORM_SCRIPT,
    GEMINI_ERR_INVALID_JSON,
    GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
)

_REQUIRED_STRING_FIELDS = {
    "title": 60,
    "summary": 150,
    "body": 800,
    "call_to_action": 60,
    "shortform_script": 400,
}
_MAX_KEYWORDS = 10
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# 응답에 절대 섞여 나오면 안 되는 내부 마커. API 키는 호출 시점에 별도로 검사한다.
_LEAK_MARKERS = ("PROJECT_ROOT", "GEMINI_API_KEY", "F:\\StoryMaker_C", "/StoryMaker_C/", "system_rules")


@dataclass
class ValidationResult:
    ok: bool
    data: Optional[dict] = None
    error_code: str = ""
    error_detail: str = ""


def _strip_code_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _find_leak(all_text: str, api_key: str) -> str:
    if api_key and api_key in all_text:
        return "api_key"
    for marker in _LEAK_MARKERS:
        if marker in all_text:
            return marker
    return ""


def validate_response(raw_text: str, api_key: str = "") -> ValidationResult:
    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_INVALID_JSON, error_detail=str(exc)[:200])

    if not isinstance(data, dict):
        return ValidationResult(ok=False, error_code=GEMINI_ERR_INVALID_JSON, error_detail="response is not a JSON object")

    for name, max_len in _REQUIRED_STRING_FIELDS.items():
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{name} missing or empty")
        if len(value) > max_len:
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{name} exceeds {max_len} chars")

    keywords = data.get("keywords")
    if (not isinstance(keywords, list) or not keywords
            or not all(isinstance(k, str) and k.strip() for k in keywords)):
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail="keywords missing or not a non-empty string list")
    if len(keywords) > _MAX_KEYWORDS:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail="keywords list too long")

    combined_text = " ".join([data[name] for name in _REQUIRED_STRING_FIELDS] + list(keywords))
    leak = _find_leak(combined_text, api_key)
    if leak:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail="response contains a disallowed internal marker")

    normalized = {
        "title": data["title"].strip(),
        "summary": data["summary"].strip(),
        "body": data["body"].strip(),
        "call_to_action": data["call_to_action"].strip(),
        "keywords": [k.strip() for k in keywords],
        "shortform_script": data["shortform_script"].strip(),
    }
    return ValidationResult(ok=True, data=normalized)


# ---------------------------------------------------------------------------
# 6B: SNS 8채널 + 숏폼 영상원고 검증
# ---------------------------------------------------------------------------
_CHANNEL_STRING_FIELDS = {"title": 120, "body": 1500, "cta": 80}
_MAX_HASHTAGS = 10
_VOICE_SCRIPT_MAX_LEN = 1200
_SCENE_SENTENCE_MAX_LEN = 200
_MAX_SCENE_SENTENCES = 20


def _forbidden_words_found(text: str, forbidden_words: str) -> str:
    for raw in re.split(r"[,\n]", forbidden_words or ""):
        word = raw.strip()
        if word and word in text:
            return word
    return ""


def _validate_channel_slot(data: Any, channel_code: str, api_key: str, forbidden_words: str) -> ValidationResult:
    if not isinstance(data, dict):
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"{channel_code}: not a JSON object")

    for name, max_len in _CHANNEL_STRING_FIELDS.items():
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.{name} missing or empty")
        if len(value) > max_len:
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.{name} exceeds {max_len} chars")

    hashtags = data.get("hashtags")
    if (not isinstance(hashtags, list) or not hashtags
            or not all(isinstance(h, str) and h.strip() for h in hashtags)):
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"{channel_code}.hashtags missing or not a non-empty string list")
    if len(hashtags) > _MAX_HASHTAGS:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"{channel_code}.hashtags list too long")

    normalized = {
        "title": data["title"].strip(),
        "body": data["body"].strip(),
        "cta": data["cta"].strip(),
        "hashtags": [h.strip() for h in hashtags],
    }

    voice_script = ""
    scene_sentences: list[str] = []
    if channel_code == CHANNEL_SHORTFORM_SCRIPT:
        voice_script = data.get("voice_script")
        if not isinstance(voice_script, str) or not voice_script.strip():
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.voice_script missing or empty")
        if len(voice_script) > _VOICE_SCRIPT_MAX_LEN:
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.voice_script exceeds {_VOICE_SCRIPT_MAX_LEN} chars")
        raw_scenes = data.get("scene_sentences")
        if (not isinstance(raw_scenes, list) or not raw_scenes
                or not all(isinstance(s, str) and s.strip() for s in raw_scenes)):
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.scene_sentences missing or not a non-empty string list")
        if len(raw_scenes) > _MAX_SCENE_SENTENCES:
            return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                     error_detail=f"{channel_code}.scene_sentences too many entries")
        for s in raw_scenes:
            if len(s) > _SCENE_SENTENCE_MAX_LEN:
                return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                         error_detail=f"{channel_code}.scene_sentences entry exceeds {_SCENE_SENTENCE_MAX_LEN} chars")
        voice_script = voice_script.strip()
        scene_sentences = [s.strip() for s in raw_scenes]
        normalized["voice_script"] = voice_script
        normalized["scene_sentences"] = scene_sentences

    combined_text = " ".join(
        [normalized["title"], normalized["body"], normalized["cta"], voice_script]
        + normalized["hashtags"] + scene_sentences
    )
    leak = _find_leak(combined_text, api_key)
    if leak:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"{channel_code}: response contains a disallowed internal marker")
    forbidden = _forbidden_words_found(combined_text, forbidden_words)
    if forbidden:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"{channel_code}: contains forbidden word")

    return ValidationResult(ok=True, data=normalized)


def validate_channels_response(raw_text: str, api_key: str = "", forbidden_words: str = "") -> ValidationResult:
    """8개 채널이 모두 존재하고 각각 유효한지 검증한다. 하나라도 실패하면 전체를 실패로 처리한다
    (부분 실패 보정은 채널별 재생성 API로 처리한다, 작업지시 5장)."""
    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_INVALID_JSON, error_detail=str(exc)[:200])

    channels = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(channels, dict):
        return ValidationResult(ok=False, error_code=GEMINI_ERR_INVALID_JSON, error_detail="missing 'channels' object")

    missing = [c for c in CHANNEL_CODES if c not in channels]
    if missing:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_SCHEMA_VALIDATION_FAILED,
                                 error_detail=f"missing channels: {missing}")

    normalized_channels: dict[str, dict] = {}
    for code in CHANNEL_CODES:
        result = _validate_channel_slot(channels[code], code, api_key, forbidden_words)
        if not result.ok:
            return result
        normalized_channels[code] = result.data

    return ValidationResult(ok=True, data={"channels": normalized_channels})


def validate_single_channel_response(raw_text: str, channel_code: str, api_key: str = "",
                                      forbidden_words: str = "") -> ValidationResult:
    cleaned = _strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, error_code=GEMINI_ERR_INVALID_JSON, error_detail=str(exc)[:200])
    return _validate_channel_slot(data, channel_code, api_key, forbidden_words)
