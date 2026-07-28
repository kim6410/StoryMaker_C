# -*- coding: utf-8 -*-
"""
6A단계 서비스 계층.

라우터는 이 모듈의 generate_for_project()만 호출한다.
PromptContext 구성 -> 프롬프트 조립 -> Gemini 호출 -> 응답 검증 -> DB 저장까지
이 계층에서만 처리하고, 라우터는 요청/응답만 담당한다(작업지시 3장).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from app.ai.prompt_builder import PromptContext, build_channels_prompt, build_prompt, build_single_channel_prompt
from app.ai.schema import validate_channels_response, validate_response, validate_single_channel_response
from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.constants import (
    CHANNEL_CODES,
    CHANNEL_PROMPT_VERSION,
    CHANNEL_RESPONSE_SCHEMA_VERSION,
    CHANNEL_SHORTFORM_SCRIPT,
    GEMINI_ERR_DUPLICATE_REQUEST,
    GEMINI_ERR_UNKNOWN_PROVIDER_ERROR,
    PROJECT_STATUS_CONTENT_READY,
    PROJECT_STATUS_FAILED,
    PROJECT_STATUS_GENERATING,
    PROJECT_STATUS_PROMPTING,
    PROJECT_STATUS_VALIDATING,
    PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
)
from app.db import repository as repo
from app.db.repository import DuplicateGenerationError
from app.integrations import gemini_client

USER_ERROR_MESSAGES = {
    "api_key_missing": "AI 콘텐츠 생성 기능이 아직 설정되지 않았습니다. 관리자에게 문의해 주세요.",
    "authentication_failed": "AI 서비스 인증에 실패했습니다. 관리자에게 문의해 주세요.",
    "permission_denied": "AI 서비스 접근 권한이 없습니다. 관리자에게 문의해 주세요.",
    "timeout": "AI 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.",
    "rate_limited": "지금은 AI 요청이 몰려 있습니다(요청 한도 초과). 잠시 후 다시 시도해 주세요.",
    "provider_5xx": "AI 서비스에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
    "network_error": "네트워크 문제로 요청이 실패했습니다. 잠시 후 다시 시도해 주세요.",
    "invalid_json": "AI 응답 형식이 올바르지 않았습니다. 다시 시도해 주세요.",
    "schema_validation_failed": "AI 응답 내용이 형식을 만족하지 못했습니다. 다시 시도해 주세요.",
    "empty_response": "AI가 빈 응답을 반환했습니다. 다시 시도해 주세요.",
    "blocked_response": "안전 정책에 의해 응답이 차단되었습니다. 입력 내용을 조정해 주세요.",
    "duplicate_request": "이미 생성이 진행 중입니다. 완료 후 다시 시도해 주세요.",
    "unknown_provider_error": "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
}


@dataclass
class GenerationOutcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    generation_id: Optional[int] = None
    result: Optional[dict] = None


def _build_context(project: dict) -> PromptContext:
    snapshot = json.loads(project.get("input_snapshot_json") or "{}")
    # 제작 당시 스냅샷에 없으면(예: core_strength, forbidden_words) 마이페이지 업체 정보에서
    # 보완한다. 업체 정보 자체는 스냅샷과 별개로 계속 최신 값을 유지하는 원본이므로,
    # 금지 표현처럼 항상 지켜야 하는 가드레일은 스냅샷이 아니라 최신 업체 설정을 따르는 편이 안전하다.
    core_strength = snapshot.get("core_strength", "")
    forbidden_words = snapshot.get("forbidden_words", "")
    if (not core_strength or not forbidden_words) and project.get("company_id"):
        company = repo.get_company(project["company_id"])
        if company:
            core_strength = core_strength or company.get("core_strength", "")
            forbidden_words = forbidden_words or company.get("forbidden_words", "")
    return PromptContext(
        user_id=project["user_id"],
        project_id=project["id"],
        company_id=project.get("company_id"),
        company_name=snapshot.get("company_name", ""),
        industry=snapshot.get("industry", ""),
        region=snapshot.get("region", ""),
        main_services=snapshot.get("main_services", ""),
        target_customers=snapshot.get("target_customers", ""),
        core_strength=core_strength,
        topic=snapshot.get("topic", ""),
        keywords=snapshot.get("keywords", ""),
        tone_preference=snapshot.get("tone_preference", ""),
        forbidden_words=forbidden_words,
    )


def generate_for_project(project: dict) -> GenerationOutcome:
    """project(= repository의 프로젝트 dict)를 받아 Gemini 생성을 1회 시도한다.
    같은 프로젝트에 이미 진행 중인 요청이 있으면 Gemini를 호출하지 않고
    duplicate_request로 즉시 반환한다(중복 호출 방지, 작업지시 10장)."""
    project_id = project["id"]
    user_id = project["user_id"]
    attempt_no = repo.count_content_generation_attempts(project_id) + 1

    try:
        generation_id = repo.create_content_generation(
            project_id=project_id, user_id=user_id, provider="gemini", model=GEMINI_MODEL,
            prompt_version=PROMPT_VERSION, response_schema_version=RESPONSE_SCHEMA_VERSION,
            attempt_no=attempt_no,
        )
    except DuplicateGenerationError:
        return GenerationOutcome(
            ok=False, error_code=GEMINI_ERR_DUPLICATE_REQUEST,
            error_message=USER_ERROR_MESSAGES[GEMINI_ERR_DUPLICATE_REQUEST],
        )

    # pending 행이 만들어진 뒤부터는 어떤 예외가 나더라도 반드시 completed_content_generation을
    # 호출해서 status를 success/failed로 확정한다. 그렇지 않으면 pending 잠금이 영구히 남아
    # 이 프로젝트의 다음 생성 요청이 전부 duplicate_request로 막힌다.
    try:
        repo.update_project_status(project_id, PROJECT_STATUS_PROMPTING)
        ctx = _build_context(project)
        prompt = build_prompt(ctx)

        repo.update_project_status(project_id, PROJECT_STATUS_GENERATING)
        call = gemini_client.generate_content(prompt)

        if not call.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=call.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=call.error_code)
            return GenerationOutcome(
                ok=False, error_code=call.error_code,
                error_message=USER_ERROR_MESSAGES.get(call.error_code, "알 수 없는 오류가 발생했습니다."),
                generation_id=generation_id,
            )

        repo.update_project_status(project_id, PROJECT_STATUS_VALIDATING)
        validation = validate_response(call.text, api_key=GEMINI_API_KEY)

        if not validation.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=validation.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=validation.error_code)
            return GenerationOutcome(
                ok=False, error_code=validation.error_code,
                error_message=USER_ERROR_MESSAGES.get(validation.error_code, "AI 응답 검증에 실패했습니다."),
                generation_id=generation_id,
            )

        result = validation.data or {}
        repo.save_generation_result(generation_id, project_id, {
            **result,
            "keywords_json": json.dumps(result.get("keywords", []), ensure_ascii=False),
        })
        repo.complete_content_generation(
            generation_id, status="success", http_status=call.http_status,
            error_code="", retry_count=call.retry_count, latency_ms=call.latency_ms,
        )
        repo.update_project_status(project_id, PROJECT_STATUS_CONTENT_READY)
        return GenerationOutcome(ok=True, generation_id=generation_id, result=result)
    except Exception:
        repo.complete_content_generation(
            generation_id, status="failed", http_status=None,
            error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR, retry_count=0, latency_ms=0,
        )
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR)
        raise


def generate_channels_for_project(project: dict) -> GenerationOutcome:
    """6B단계: SNS 8채널 + 숏폼 영상원고를 한 번의 Gemini 호출로 생성하고 채널별로 저장한다.
    8개 중 하나라도 검증에 실패하면 전체를 저장하지 않고 실패로 남긴다(부분 보정은
    regenerate_channel_for_project로 채널 단위 재시도한다)."""
    project_id = project["id"]
    user_id = project["user_id"]
    attempt_no = repo.count_content_generation_attempts(project_id) + 1

    try:
        generation_id = repo.create_content_generation(
            project_id=project_id, user_id=user_id, provider="gemini", model=GEMINI_MODEL,
            prompt_version=CHANNEL_PROMPT_VERSION, response_schema_version=CHANNEL_RESPONSE_SCHEMA_VERSION,
            attempt_no=attempt_no,
        )
    except DuplicateGenerationError:
        return GenerationOutcome(
            ok=False, error_code=GEMINI_ERR_DUPLICATE_REQUEST,
            error_message=USER_ERROR_MESSAGES[GEMINI_ERR_DUPLICATE_REQUEST],
        )

    try:
        repo.update_project_status(project_id, PROJECT_STATUS_PROMPTING)
        ctx = _build_context(project)
        prompt = build_channels_prompt(ctx)

        repo.update_project_status(project_id, PROJECT_STATUS_GENERATING)
        call = gemini_client.generate_content(prompt)

        if not call.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=call.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=call.error_code)
            return GenerationOutcome(
                ok=False, error_code=call.error_code,
                error_message=USER_ERROR_MESSAGES.get(call.error_code, "알 수 없는 오류가 발생했습니다."),
                generation_id=generation_id,
            )

        repo.update_project_status(project_id, PROJECT_STATUS_VALIDATING)
        validation = validate_channels_response(call.text, api_key=GEMINI_API_KEY, forbidden_words=ctx.forbidden_words)

        if not validation.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=validation.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=validation.error_code)
            return GenerationOutcome(
                ok=False, error_code=validation.error_code,
                error_message=USER_ERROR_MESSAGES.get(validation.error_code, "AI 응답 검증에 실패했습니다."),
                generation_id=generation_id,
            )

        channels = (validation.data or {}).get("channels", {})
        for code in CHANNEL_CODES:
            slot = channels[code]
            repo.upsert_channel_result(generation_id, project_id, code, {
                "title": slot["title"], "body": slot["body"], "cta": slot["cta"],
                "hashtags_json": json.dumps(slot["hashtags"], ensure_ascii=False),
            })
        video_slot = channels[CHANNEL_SHORTFORM_SCRIPT]
        repo.upsert_video_script(
            generation_id, project_id, video_slot["voice_script"],
            json.dumps(video_slot["scene_sentences"], ensure_ascii=False),
        )

        repo.complete_content_generation(
            generation_id, status="success", http_status=call.http_status,
            error_code="", retry_count=call.retry_count, latency_ms=call.latency_ms,
        )
        repo.update_project_status(project_id, PROJECT_STATUS_CONTENT_READY)
        return GenerationOutcome(ok=True, generation_id=generation_id, result={"channels": channels})
    except Exception:
        repo.complete_content_generation(
            generation_id, status="failed", http_status=None,
            error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR, retry_count=0, latency_ms=0,
        )
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR)
        raise


def regenerate_channel_for_project(project: dict, channel_code: str) -> GenerationOutcome:
    """채널 하나만 다시 생성한다. 다른 7개 채널의 저장된 결과는 건드리지 않는다."""
    if channel_code not in CHANNEL_CODES:
        return GenerationOutcome(ok=False, error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR,
                                  error_message="알 수 없는 채널입니다.")

    project_id = project["id"]
    user_id = project["user_id"]
    attempt_no = repo.count_content_generation_attempts(project_id) + 1

    try:
        generation_id = repo.create_content_generation(
            project_id=project_id, user_id=user_id, provider="gemini", model=GEMINI_MODEL,
            prompt_version=CHANNEL_PROMPT_VERSION, response_schema_version=CHANNEL_RESPONSE_SCHEMA_VERSION,
            attempt_no=attempt_no,
        )
    except DuplicateGenerationError:
        return GenerationOutcome(
            ok=False, error_code=GEMINI_ERR_DUPLICATE_REQUEST,
            error_message=USER_ERROR_MESSAGES[GEMINI_ERR_DUPLICATE_REQUEST],
        )

    try:
        ctx = _build_context(project)
        prompt = build_single_channel_prompt(ctx, channel_code)
        call = gemini_client.generate_content(prompt)

        if not call.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=call.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            return GenerationOutcome(
                ok=False, error_code=call.error_code,
                error_message=USER_ERROR_MESSAGES.get(call.error_code, "알 수 없는 오류가 발생했습니다."),
                generation_id=generation_id,
            )

        validation = validate_single_channel_response(
            call.text, channel_code, api_key=GEMINI_API_KEY, forbidden_words=ctx.forbidden_words,
        )
        if not validation.ok:
            repo.complete_content_generation(
                generation_id, status="failed", http_status=call.http_status,
                error_code=validation.error_code, retry_count=call.retry_count, latency_ms=call.latency_ms,
            )
            return GenerationOutcome(
                ok=False, error_code=validation.error_code,
                error_message=USER_ERROR_MESSAGES.get(validation.error_code, "AI 응답 검증에 실패했습니다."),
                generation_id=generation_id,
            )

        slot = validation.data or {}
        repo.upsert_channel_result(generation_id, project_id, channel_code, {
            "title": slot["title"], "body": slot["body"], "cta": slot["cta"],
            "hashtags_json": json.dumps(slot["hashtags"], ensure_ascii=False),
        })
        if channel_code == CHANNEL_SHORTFORM_SCRIPT:
            repo.upsert_video_script(
                generation_id, project_id, slot["voice_script"],
                json.dumps(slot["scene_sentences"], ensure_ascii=False),
            )
        repo.complete_content_generation(
            generation_id, status="success", http_status=call.http_status,
            error_code="", retry_count=call.retry_count, latency_ms=call.latency_ms,
        )
        return GenerationOutcome(ok=True, generation_id=generation_id, result=slot)
    except Exception:
        repo.complete_content_generation(
            generation_id, status="failed", http_status=None,
            error_code=GEMINI_ERR_UNKNOWN_PROVIDER_ERROR, retry_count=0, latency_ms=0,
        )
        raise
