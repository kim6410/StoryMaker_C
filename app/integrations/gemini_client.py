# -*- coding: utf-8 -*-
"""
Gemini generateContent API용 최소 Integration Adapter.

- 외부 API 호출은 이 모듈만 담당한다. 라우터·서비스는 여기를 통해서만 Gemini를 부른다.
- API 키, 전체 프롬프트, 전체 응답 본문은 이 모듈에서도 로그로 남기지 않는다.
- 예외를 호출자에게 그대로 던지지 않고, 항상 분류된 오류코드(app.constants의
  GEMINI_ERR_* 13종)로 변환해서 반환한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import (
    GEMINI_API_BASE,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
)
from app.constants import (
    GEMINI_ERR_API_KEY_MISSING,
    GEMINI_ERR_AUTHENTICATION_FAILED,
    GEMINI_ERR_BLOCKED_RESPONSE,
    GEMINI_ERR_EMPTY_RESPONSE,
    GEMINI_ERR_NETWORK_ERROR,
    GEMINI_ERR_PERMISSION_DENIED,
    GEMINI_ERR_PROVIDER_5XX,
    GEMINI_ERR_RATE_LIMITED,
    GEMINI_ERR_TIMEOUT,
    GEMINI_ERR_UNKNOWN_PROVIDER_ERROR,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_BASE_DELAY_SECONDS,
    GEMINI_RETRYABLE_ERROR_CODES,
)


@dataclass
class GeminiCallResult:
    ok: bool
    text: str = ""
    http_status: Optional[int] = None
    error_code: str = ""
    retry_count: int = 0
    latency_ms: int = 0


def _single_request(prompt: str) -> tuple[bool, str, Optional[int], str]:
    """HTTP 요청 1회. (ok, text, http_status, error_code)를 반환하고 예외를 던지지 않는다."""
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent"
    try:
        resp = httpx.post(
            url,
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return False, "", None, GEMINI_ERR_TIMEOUT
    except httpx.RequestError:
        return False, "", None, GEMINI_ERR_NETWORK_ERROR

    status = resp.status_code
    if status == 401:
        return False, "", status, GEMINI_ERR_AUTHENTICATION_FAILED
    if status == 403:
        return False, "", status, GEMINI_ERR_PERMISSION_DENIED
    if status == 429:
        return False, "", status, GEMINI_ERR_RATE_LIMITED
    if 500 <= status < 600:
        return False, "", status, GEMINI_ERR_PROVIDER_5XX
    if status != 200:
        return False, "", status, GEMINI_ERR_UNKNOWN_PROVIDER_ERROR

    try:
        data = resp.json()
    except ValueError:
        return False, "", status, GEMINI_ERR_UNKNOWN_PROVIDER_ERROR

    candidates = data.get("candidates") or []
    if not candidates:
        prompt_feedback = data.get("promptFeedback") or {}
        if prompt_feedback.get("blockReason"):
            return False, "", status, GEMINI_ERR_BLOCKED_RESPONSE
        return False, "", status, GEMINI_ERR_EMPTY_RESPONSE

    first = candidates[0]
    if first.get("finishReason") == "SAFETY":
        return False, "", status, GEMINI_ERR_BLOCKED_RESPONSE

    parts = (first.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        return False, "", status, GEMINI_ERR_EMPTY_RESPONSE

    return True, text, status, ""


def generate_content(prompt: str) -> GeminiCallResult:
    """prompt를 Gemini에 보내고 결과를 반환한다.
    timeout/429/5xx/일시적 network_error만 제한적으로 재시도하고,
    인증·권한 오류는 재시도하지 않는다(작업지시 10장)."""
    started = time.monotonic()

    if not GEMINI_API_KEY:
        return GeminiCallResult(ok=False, error_code=GEMINI_ERR_API_KEY_MISSING, latency_ms=0)

    retry_count = 0
    last_status: Optional[int] = None
    last_error_code = GEMINI_ERR_UNKNOWN_PROVIDER_ERROR

    while True:
        ok, text, status, error_code = _single_request(prompt)
        last_status, last_error_code = status, error_code
        if ok:
            return GeminiCallResult(
                ok=True, text=text, http_status=status, retry_count=retry_count,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        if error_code not in GEMINI_RETRYABLE_ERROR_CODES or retry_count >= GEMINI_MAX_RETRIES:
            break
        time.sleep(GEMINI_RETRY_BASE_DELAY_SECONDS * (2 ** retry_count))
        retry_count += 1

    return GeminiCallResult(
        ok=False, http_status=last_status, error_code=last_error_code, retry_count=retry_count,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
