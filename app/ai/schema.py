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
from typing import Optional

from app.constants import GEMINI_ERR_INVALID_JSON, GEMINI_ERR_SCHEMA_VALIDATION_FAILED

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
