# -*- coding: utf-8 -*-
"""
StoryMaker Claude Lab - 3단계: 회원가입/로그인/세션을 자체 DB로 실제 동작시킨다.
- WordPress는 아직 실제로 연결하지 않는다(app/auth/providers.py 참고).
- AI API, 음성, MP4 렌더링 등은 여전히 연결하지 않는다.
- 기존 StoryMaker V1/Beta 소스코드는 이 프로젝트에서 참고하지 않았다.
"""
from __future__ import annotations

import os
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone

from app.db.migrations import run_migrations
from app.db.connection import integrity_check, current_journal_mode
from app.auth.routes import router as auth_router
from app.auth.dependencies import get_optional_user

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent

app = FastAPI(title="StoryMaker Claude Lab", version="0.3.0-auth")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "templates")
app.include_router(auth_router)

# 단계10A: projects.status를 화면 어디서나 같은 한글 문구로 보여주기 위한 공통 매핑.
PROJECT_STATUS_LABELS = {
    "draft": "정보 입력 중", "queued": "대기 중",
    "prompting": "원고 준비 중", "generating": "AI 원고 생성 중", "validating": "결과 확인 중",
    "content_ready": "SNS 8채널 완료", "tts_ready": "음성 생성 완료", "subtitle_ready": "자막 생성 완료",
    "media_ready": "영상 소재 준비 완료", "rendering": "영상 제작 중",
    "completed": "완료", "failed": "실패",
}
templates.env.globals["status_label"] = lambda s: PROJECT_STATUS_LABELS.get(s, s)


@app.on_event("startup")
def _startup_run_migrations() -> None:
    newly_applied = run_migrations()
    if newly_applied:
        print(f"[db] applied migrations: {newly_applied}")
    else:
        print("[db] schema already up to date")


# ---------------------------------------------------------------------------
# 사이드 메뉴 구성
# ---------------------------------------------------------------------------
USER_MENU = [
    {"key": "dashboard", "label": "대시보드", "href": "/dashboard", "icon": "grid"},
    {"key": "content_new", "label": "새 콘텐츠 제작", "href": "/content/new", "icon": "plus"},
    {"key": "in_progress", "label": "진행 중 작업", "href": "/archive?status=in_progress", "icon": "clock"},
    {"key": "archive", "label": "보관함", "href": "/archive", "icon": "folder"},
    {"key": "mypage", "label": "마이페이지", "href": "/mypage", "icon": "user"},
    {"key": "subscription", "label": "구독 및 사용량", "href": "/subscription", "icon": "chart"},
]
ADMIN_MENU = [
    {"key": "admin_dashboard", "label": "관리자 대시보드", "href": "/admin", "icon": "grid"},
    {"key": "admin_members", "label": "회원관리", "href": "/admin/members", "icon": "shield"},
    {"key": "admin_jobs", "label": "작업관리", "href": "/admin/jobs", "icon": "clock"},
    {"key": "admin_diagnostics", "label": "TTS·렌더 진단", "href": "/admin/diagnostics", "icon": "chart"},
    {"key": "admin_storage", "label": "저장공간·감사로그", "href": "/admin/storage", "icon": "folder"},
]

# 3단계에서는 콘텐츠 제작·보관함 화면을 아직 실제 DB와 연결하지 않으므로
# 화면 자체는 1단계와 동일한 샘플 데이터를 계속 사용한다(다음 단계 범위).
SAMPLE_CHANNELS = [
    {"key": "naver_blog", "name": "네이버 블로그", "title": "강북구 사장님이 추천하는 겨울철 보일러 점검 꿀팁", "body": "안녕하세요, 오박사만능설비입니다. 요즘처럼 기온이 뚝 떨어지는 시기에는 보일러 점검이 특히 중요한데요...", "hashtags": "#강북구보일러 #보일러점검 #겨울철난방"},
    {"key": "naver_place", "name": "네이버 플레이스", "title": "오박사만능설비 - 강북구 보일러 전문", "body": "강북구 전 지역 출장 가능, 당일 방문 점검 가능합니다.", "hashtags": "#출장수리 #당일방문"},
    {"key": "google_business", "name": "구글 비즈니스 프로필", "title": "Trusted Boiler Repair in Gangbuk-gu", "body": "Same-day visit available across Gangbuk-gu. 15 years of experience.", "hashtags": "#BoilerRepair #Gangbuk"},
    {"key": "instagram", "name": "인스타그램", "title": "보일러 점검, 미루지 마세요 🔥", "body": "오늘도 강북구 곳곳을 누비는 오박사만능설비입니다! 저장해두고 필요할 때 연락주세요 📌", "hashtags": "#강북구맛집아님 #보일러 #설비사장님"},
    {"key": "facebook", "name": "페이스북", "title": "겨울철 보일러 고장, 왜 갑자기 생길까요?", "body": "매년 이맘때 문의가 폭주하는 이유를 정리해봤습니다.", "hashtags": "#보일러고장 #강북구설비"},
    {"key": "danggeun", "name": "당근 비즈프로필", "title": "강북구 보일러 수리 - 오박사만능설비", "body": "동네에서 15년째 영업 중입니다. 이웃 주민분들께 특별 할인 진행해요.", "hashtags": "#동네설비 #강북구이웃"},
    {"key": "kakao_channel", "name": "카카오채널", "title": "[알림] 12월 보일러 무료 점검 이벤트", "body": "채널 추가하시면 출장비 5,000원 할인해드려요.", "hashtags": "#카카오채널이벤트"},
    {"key": "shortform", "name": "숏폼/Reels 설명문", "title": "보일러 소리가 이상하다면? 3가지만 확인하세요", "body": "영상으로 쉽게 알려드립니다. 자세한 내용은 프로필 링크 확인!", "hashtags": "#보일러꿀팁 #숏폼"},
]

SAMPLE_ARCHIVE_ITEMS = [
    {"id": "job-sample-0001", "title": "겨울철 보일러 점검 콘텐츠", "company": "오박사만능설비", "created_at": "2026-07-27 14:20", "status": "완료", "media": ["이미지 4장", "음성", "자막", "MP4", "썸네일"], "size": "38.2MB"},
    {"id": "job-sample-0002", "title": "여름철 에어컨 청소 안내", "company": "오박사만능설비", "created_at": "2026-07-25 09:05", "status": "완료", "media": ["이미지 3장", "음성", "자막", "MP4", "썸네일"], "size": "29.7MB"},
    {"id": "job-sample-0003", "title": "강북구 배관 누수 출장 후기", "company": "오박사만능설비", "created_at": "2026-07-20 18:41", "status": "완료", "media": ["이미지 5장", "음성", "자막", "MP4", "썸네일"], "size": "41.0MB"},
]

SAMPLE_ARCHIVE_DETAIL = {
    "job-sample-0001": {
        "title": "겨울철 보일러 점검 콘텐츠",
        "company": "오박사만능설비",
        "created_at": "2026-07-27 14:20",
        "channels": SAMPLE_CHANNELS,
        "assets": {
            "images": ["원본 4장", "워터마크 4장"],
            "audio": "voice.mp3 (2:14)",
            "subtitle": "subtitle.srt",
            "video": "final.mp4 (9:16, 0:38)",
            "thumbnail": "thumbnail_03.png",
        },
    }
}

def _ctx(request: Request, user: dict, *, active: str = "", **extra) -> dict:
    admin_menu = ADMIN_MENU if str(user.get("role")) == "admin" else []
    return {
        "request": request,
        "app_name": "StoryMaker Claude Lab",
        "user": user,
        "user_menu": USER_MENU,
        "admin_menu": admin_menu,  # 관리자가 아니면 서버에서부터 빈 리스트 -> DOM 자체가 생성되지 않음
        "active": active,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **extra,
    }


def _require_login_or_redirect(request: Request):
    """로그인 안 됐으면 /login으로 보낸다. 로그인 됐으면 사용자 dict를 반환한다."""
    user = get_optional_user(request)
    if not user:
        return None
    return user


def _require_admin_or_none(request: Request):
    """로그인했고 role=admin인 사용자만 반환한다. 아니면 None(호출부에서 리다이렉트)."""
    user = _require_login_or_redirect(request)
    if not user or str(user.get("role")) != "admin":
        return None
    return user


# ---------------------------------------------------------------------------
# 인증 전 화면
# ---------------------------------------------------------------------------
@app.get("/")
def root(request: Request):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login")
def login_page(request: Request, error: str = "", verified: int = 0, verify_failed: int = 0,
               reset: int = 0, logged_out: int = 0, password_changed: int = 0):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {
        "request": request, "app_name": "StoryMaker Claude Lab",
        "error": error, "verified": verified, "verify_failed": verify_failed,
        "reset": reset, "logged_out": logged_out, "password_changed": password_changed,
    })


@app.get("/register")
def register_page(request: Request, error: str = ""):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("register.html", {"request": request, "app_name": "StoryMaker Claude Lab", "error": error})


@app.get("/verify-email")
def verify_email_page(request: Request, email: str = "", dev_link: str = ""):
    return templates.TemplateResponse("verify_email.html", {
        "request": request, "app_name": "StoryMaker Claude Lab", "email": email, "dev_link": dev_link,
    })


@app.get("/forgot-password")
def forgot_password_page(request: Request, error: str = "", sent: int = 0, dev_link: str = "", expired: int = 0):
    return templates.TemplateResponse("forgot_password.html", {
        "request": request, "app_name": "StoryMaker Claude Lab",
        "error": error, "sent": sent, "dev_link": dev_link, "expired": expired,
    })


# ---------------------------------------------------------------------------
# 인증 후 화면 (실제 세션 필요, 없으면 로그인으로 리다이렉트)
# ---------------------------------------------------------------------------
@app.get("/dashboard")
def dashboard_page(request: Request):
    import json as _json
    from datetime import datetime, timezone

    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    from app.db import repository as repo
    recent_projects = repo.list_projects_for_user(user["id"], limit=5)
    recent = []
    for p in recent_projects:
        snapshot = _json.loads(p.get("input_snapshot_json") or "{}")
        recent.append({
            "job_uid": p["job_uid"], "title": p["title"],
            "company": snapshot.get("company_name", "-"),
            "created_at": p["created_at"][:16].replace("T", " "),
            "status": p["status"], "error_code": p.get("error_code", ""),
        })

    counts = repo.count_projects_by_status_for_user(user["id"])
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00")
    monthly_count = repo.count_projects_for_user_since(user["id"], month_start)

    plan = repo.get_active_subscription(user["id"])
    monthly_limit = plan["monthly_project_limit"] if plan else 20  # Free 플랜 기본값(참고용, 강제 차단 아님)

    company = repo.get_default_company_for_user(user["id"])

    latest_completed_mp4 = None
    for p in recent_projects:
        if p["status"] == "completed":
            mp4 = repo.get_mp4_for_project(p["id"])
            if mp4 and mp4["status"] == "success":
                latest_completed_mp4 = {"job_uid": p["job_uid"], "title": p["title"]}
                break

    from app.content.steps import STEP_DEFS, build_step_states
    for r, p in zip(recent, recent_projects):
        states = build_step_states(p)
        current = next((s for s in states if s["state"] in ("current", "failed")), states[-1])
        r["step_label"] = current["label"]

    return templates.TemplateResponse("dashboard.html", _ctx(
        request, user, active="dashboard", recent=recent, counts=counts,
        monthly_count=monthly_count, monthly_limit=monthly_limit, company=company,
        latest_completed_mp4=latest_completed_mp4,
    ))


@app.get("/content/new")
def content_new_page(request: Request, error: str = ""):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    from app.content.music import list_music_files
    company = repo.get_default_company_for_user(user["id"])
    music_items = list_music_files()
    return templates.TemplateResponse("content_new.html", _ctx(
        request, user, active="content_new", company=company, music_items=music_items, error=error,
    ))


@app.post("/content/new")
def create_content_job(
    request: Request,
    topic: str = Form(...),
    keywords: str = Form(""),
    tone_preference: str = Form(""),
    content_length: str = Form("medium"),
    music_relative_path: str = Form(""),
    voice_preference: str = Form("female"),
    company_name: str = Form(""),
    owner_name: str = Form(""),
    phone_number: str = Form(""),
    industry: str = Form(""),
    region: str = Form(""),
    main_services: str = Form(""),
    target_customers: str = Form(""),
):
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not topic.strip():
        return RedirectResponse(url="/content/new?error=제작+주제를+입력해+주세요.", status_code=303)

    from app.db import repository as repo
    from app.content.music import resolve_music_path

    company = repo.get_default_company_for_user(user["id"])
    if music_relative_path and not resolve_music_path(music_relative_path):
        music_relative_path = ""

    # 마이페이지 업체 정보와 별개로, 이번 제작 요청 당시 값을 스냅샷으로 고정한다.
    # (나중에 마이페이지 업체 정보가 바뀌어도 이 작업의 과거 결과는 변하지 않는다.)
    snapshot = {
        "company_name": company_name.strip() or (company["company_name"] if company else ""),
        "owner_name": owner_name.strip() or (company["owner_name"] if company else ""),
        "phone_number": phone_number.strip() or (company["phone_number"] if company else ""),
        "industry": industry.strip() or (company["industry"] if company else ""),
        "region": region.strip() or (company["region"] if company else ""),
        "main_services": main_services.strip() or (company["main_services"] if company else ""),
        "target_customers": target_customers.strip() or (company["target_customers"] if company else ""),
        "topic": topic.strip(),
        "keywords": keywords.strip(),
        "tone_preference": tone_preference.strip(),
        "content_length": content_length.strip() or "medium",
    }
    project = repo.create_content_project(
        user_id=user["id"],
        title=topic.strip(),
        company_id=(company["id"] if company else None),
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        music_relative_path=music_relative_path,
        voice_preference=voice_preference.strip() or "female",
    )
    repo.write_audit_log(user["id"], "content_job_created", target_type="project", target_id=project["id"])
    return RedirectResponse(url=f"/content/job/{project['job_uid']}", status_code=303)


def _get_owned_project_or_none(job_uid: str, user: dict):
    """job_uid로 프로젝트를 찾되, 본인 소유이거나 관리자일 때만 반환한다.
    다른 사용자의 작업 ID로는 URL을 알아도 접근할 수 없어야 한다(계획서 14장)."""
    from app.db import repository as repo
    project = repo.get_project_by_uid(job_uid)
    if not project:
        return None
    if project["user_id"] != user["id"] and str(user.get("role")) != "admin":
        return None
    return project


@app.get("/content/job/{job_uid}")
def content_job_status(request: Request, job_uid: str, gen_error: str = ""):
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    from app.constants import GEMINI_ERROR_CODES
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")
    snapshot = json.loads(project["input_snapshot_json"] or "{}")
    gemini_configured = bool((os.getenv("GEMINI_API_KEY") or "").strip())
    result = repo.get_latest_generation_result_for_project(project["id"])
    if result and result.get("keywords_json"):
        result = {**result, "keywords": json.loads(result["keywords_json"])}
    generations = repo.list_content_generations_for_project(project["id"])
    last_generation = generations[-1] if generations else None
    gen_error_message = ""
    if gen_error and gen_error in GEMINI_ERROR_CODES:
        from app.ai.service import USER_ERROR_MESSAGES
        gen_error_message = USER_ERROR_MESSAGES.get(gen_error, "")
    from app.content.steps import build_step_states
    return templates.TemplateResponse("content_job_status.html", _ctx(
        request, user, active="content_new", project=project, snapshot=snapshot,
        gemini_configured=gemini_configured, result=result, last_generation=last_generation,
        gen_error_message=gen_error_message, steps=build_step_states(project),
    ))


@app.post("/content/job/{job_uid}/generate")
def content_job_generate(request: Request, job_uid: str):
    """6B단계: 실제 Gemini API를 호출해 SNS 8채널 + 숏폼 영상원고를 생성한다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.ai.service import generate_channels_for_project
    from app.db import repository as repo
    try:
        outcome = generate_channels_for_project(project)
    except Exception:
        return RedirectResponse(url=f"/content/job/{job_uid}?gen_error=unknown_provider_error", status_code=303)

    repo.write_audit_log(
        user["id"], "content_generation_attempted", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}/channels", status_code=303)
    return RedirectResponse(url=f"/content/job/{job_uid}?gen_error={outcome.error_code}", status_code=303)


@app.get("/content/job/{job_uid}/channels")
def content_job_channels_page(request: Request, job_uid: str, channel_error: str = ""):
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    from app.constants import CHANNEL_CODES, CHANNEL_LABELS, GEMINI_ERROR_CODES

    rows_by_code = {r["channel_code"]: r for r in repo.list_channel_results_for_project(project["id"])}
    channels = []
    for code in CHANNEL_CODES:
        row = rows_by_code.get(code)
        channels.append({
            "code": code,
            "label": CHANNEL_LABELS[code],
            "row": row,
            "hashtags": json.loads(row["hashtags_json"]) if row else [],
        })
    video_script = repo.get_video_script_for_project(project["id"])
    scene_sentences = json.loads(video_script["scene_sentences_json"]) if video_script else []

    channel_error_message = ""
    if channel_error and channel_error in GEMINI_ERROR_CODES:
        from app.ai.service import USER_ERROR_MESSAGES
        channel_error_message = USER_ERROR_MESSAGES.get(channel_error, "")

    from app.content.steps import build_step_states
    return templates.TemplateResponse("content_job_channels.html", _ctx(
        request, user, active="content_new", project=project, channels=channels,
        video_script=video_script, scene_sentences=scene_sentences,
        channel_error_message=channel_error_message, steps=build_step_states(project),
    ))


@app.post("/content/job/{job_uid}/channels/{channel_code}/regenerate")
def content_job_channel_regenerate(request: Request, job_uid: str, channel_code: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.ai.service import regenerate_channel_for_project
    from app.db import repository as repo
    try:
        outcome = regenerate_channel_for_project(project, channel_code)
    except Exception:
        return RedirectResponse(
            url=f"/content/job/{job_uid}/channels?channel_error=unknown_provider_error", status_code=303
        )
    repo.write_audit_log(
        user["id"], "channel_regenerated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"channel": "{channel_code}", "ok": {str(outcome.ok).lower()}}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}/channels", status_code=303)
    return RedirectResponse(
        url=f"/content/job/{job_uid}/channels?channel_error={outcome.error_code}", status_code=303
    )


@app.post("/content/job/{job_uid}/channels/{channel_code}/edit")
def content_job_channel_edit(
    request: Request, job_uid: str, channel_code: str,
    title: str = Form(""), body: str = Form(""), cta: str = Form(""), hashtags: str = Form(""),
):
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    from app.constants import CHANNEL_CODES
    if channel_code not in CHANNEL_CODES:
        return RedirectResponse(url=f"/content/job/{job_uid}/channels", status_code=303)

    hashtag_list = [h.strip() for h in hashtags.split(",") if h.strip()]
    repo.update_channel_result_manual_edit(
        project["id"], channel_code, title.strip(), body.strip(),
        json.dumps(hashtag_list, ensure_ascii=False), cta.strip(),
    )
    repo.write_audit_log(user["id"], "channel_manual_edit", target_type="project", target_id=project["id"])
    return RedirectResponse(url=f"/content/job/{job_uid}/channels", status_code=303)


@app.post("/content/job/{job_uid}/channels/{channel_code}/revert")
def content_job_channel_revert(request: Request, job_uid: str, channel_code: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    repo.revert_channel_result(project["id"], channel_code)
    repo.write_audit_log(user["id"], "channel_reverted", target_type="project", target_id=project["id"])
    return RedirectResponse(url=f"/content/job/{job_uid}/channels", status_code=303)


@app.post("/content/job/{job_uid}/tts/generate")
def content_job_tts_generate(request: Request, job_uid: str):
    """단계7: 영상원고 문장을 정규화해 Supertonic으로 TTS를 생성하고, 성공하면 SRT까지 만든다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.tts.service import generate_tts_for_project
    from app.db import repository as repo
    outcome = generate_tts_for_project(project)
    repo.write_audit_log(
        user["id"], "tts_generated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "success": {outcome.success_sentences}, "failed": {outcome.failed_sentences}}}',
    )
    if outcome.ok:
        from app.subtitle.srt_builder import build_srt_for_project
        build_srt_for_project(project)
    return RedirectResponse(url=f"/content/job/{job_uid}/tts", status_code=303)


@app.post("/content/job/{job_uid}/tts/sentence/{sentence_index}/regenerate")
def content_job_tts_sentence_regenerate(request: Request, job_uid: str, sentence_index: int):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.tts.service import regenerate_tts_sentence
    from app.db import repository as repo
    outcome = regenerate_tts_sentence(project, sentence_index)
    repo.write_audit_log(user["id"], "tts_sentence_regenerated", target_type="project", target_id=project["id"])
    if outcome.ok and outcome.failed_sentences == 0:
        from app.subtitle.srt_builder import build_srt_for_project
        build_srt_for_project(project)
    return RedirectResponse(url=f"/content/job/{job_uid}/tts", status_code=303)


@app.get("/content/job/{job_uid}/tts")
def content_job_tts_page(request: Request, job_uid: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    sentences = repo.list_tts_sentences_for_project(project["id"])
    master = repo.get_tts_master_for_project(project["id"])
    srt = repo.get_srt_for_project(project["id"])
    video_script = repo.get_video_script_for_project(project["id"])
    from app.content.steps import build_step_states
    import json as _json
    snapshot = _json.loads(project.get("input_snapshot_json") or "{}")
    phone_number = snapshot.get("phone_number", "")
    phone_tts_preview = ""
    if phone_number:
        from app.tts.normalizer import normalize_for_tts
        phone_tts_preview = normalize_for_tts(phone_number)
    return templates.TemplateResponse("content_job_tts.html", _ctx(
        request, user, active="content_new", project=project, sentences=sentences,
        master=master, srt=srt, has_script=bool(video_script), video_script=video_script,
        steps=build_step_states(project), phone_number=phone_number, phone_tts_preview=phone_tts_preview,
    ))


@app.get("/content/job/{job_uid}/tts/audio/{filename}")
def content_job_tts_audio(request: Request, job_uid: str, filename: str):
    """문장별/전체 합성 WAV 스트리밍. 소유자만 접근 가능하고 파일명은 이 작업의 tts 폴더로만 해석한다."""
    from fastapi import HTTPException
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.config import JOBS_DIR
    from app.media.range_response import range_file_response
    safe_name = Path(filename).name
    path = JOBS_DIR / job_uid / "tts" / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다.")
    return range_file_response(request, path, "audio/wav")


@app.get("/content/job/{job_uid}/subtitle/download")
def content_job_subtitle_download(request: Request, job_uid: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    from app.config import PathEscapeError, to_absolute_path
    srt = repo.get_srt_for_project(project["id"])
    if not srt or srt["status"] != "success":
        raise HTTPException(status_code=404, detail="SRT가 아직 없습니다.")
    try:
        path = to_absolute_path(srt["relative_srt_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="SRT 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="SRT 파일을 찾을 수 없습니다.")
    return FileResponse(path, media_type="application/x-subrip", filename="subtitle.srt")


@app.post("/content/job/{job_uid}/mp4/generate")
def content_job_mp4_generate(request: Request, job_uid: str):
    """단계8: 배경음악 혼합 + 장면 구성 + FFmpeg 렌더로 최종 MP4를 만든다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.media.service import generate_mp4_for_project
    from app.db import repository as repo
    outcome = generate_mp4_for_project(project)
    repo.write_audit_log(
        user["id"], "mp4_generated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}/mp4", status_code=303)
    return RedirectResponse(url=f"/content/job/{job_uid}/mp4?mp4_error={outcome.error_code}", status_code=303)


@app.get("/content/job/{job_uid}/mp4")
def content_job_mp4_page(request: Request, job_uid: str, mp4_error: str = ""):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    mp4 = repo.get_mp4_for_project(project["id"])
    music_mix = repo.get_music_mix_for_project(project["id"])
    scenes = repo.list_scenes_for_project(project["id"])
    master = repo.get_tts_master_for_project(project["id"])
    srt = repo.get_srt_for_project(project["id"])
    has_tts = bool(master and master["status"] == "success" and srt and srt["status"] == "success")

    mp4_error_message = ""
    if mp4_error:
        from app.media.service import USER_MP4_ERROR_MESSAGES
        mp4_error_message = USER_MP4_ERROR_MESSAGES.get(mp4_error, "")

    from app.content.steps import build_step_states
    zoom_labels = {"zoom_in": "천천히 확대", "zoom_out": "천천히 축소", "static": "고정 화면"}
    return templates.TemplateResponse("content_job_mp4.html", _ctx(
        request, user, active="content_new", project=project, mp4=mp4, music_mix=music_mix,
        scenes=scenes, has_tts=has_tts, mp4_error_message=mp4_error_message,
        steps=build_step_states(project), zoom_labels=zoom_labels,
    ))


@app.get("/content/job/{job_uid}/mp4/video")
def content_job_mp4_video(request: Request, job_uid: str):
    from fastapi import HTTPException
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    from app.config import PathEscapeError, to_absolute_path
    from app.media.range_response import range_file_response
    mp4 = repo.get_mp4_for_project(project["id"])
    if not mp4 or mp4["status"] != "success":
        raise HTTPException(status_code=404, detail="MP4가 아직 없습니다.")
    try:
        path = to_absolute_path(mp4["relative_mp4_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="MP4 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="MP4 파일을 찾을 수 없습니다.")
    return range_file_response(request, path, "video/mp4", filename="content.mp4")


@app.get("/content/job/{job_uid}/render-manifest.json")
def content_job_render_manifest(request: Request, job_uid: str):
    """단계9: 브라우저 로컬 렌더가 사용할 검증된 작업 명세. 소유자만 접근 가능하다."""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.media.service import build_render_manifest
    manifest = build_render_manifest(project)
    if not manifest:
        raise HTTPException(status_code=409, detail="TTS·SRT가 아직 준비되지 않았습니다.")
    return JSONResponse(manifest)


@app.post("/content/job/{job_uid}/mp4/upload-local")
async def content_job_mp4_upload_local(request: Request, job_uid: str, file: UploadFile = File(...)):
    """단계9: 브라우저(WebGPU/WASM/WebCodecs)가 만든 MP4를 업로드받아 서버가 재검증 후 저장한다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.config import JOBS_DIR
    from app.media.service import accept_local_render_upload
    from app.db import repository as repo

    upload_dir = JOBS_DIR / job_uid / "media"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = upload_dir / "upload_local_tmp.mp4"
    max_bytes = 200 * 1024 * 1024
    written = 0
    with open(tmp_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                f.close()
                tmp_path.unlink(missing_ok=True)
                return {"ok": False, "error_code": "file_too_large"}
            f.write(chunk)

    outcome = accept_local_render_upload(project, tmp_path)
    repo.write_audit_log(
        user["id"], "mp4_local_upload", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    return {"ok": outcome.ok, "error_code": outcome.error_code, "error_message": outcome.error_message,
            "duration_seconds": outcome.duration_seconds, "file_size_bytes": outcome.file_size_bytes}


@app.post("/content/job/{job_uid}/mp4/render-diagnostics")
async def content_job_mp4_render_diagnostics(request: Request, job_uid: str):
    """단계9: 로컬 가속 진단 정보(관리자 분석용)만 저장한다. 개인정보·과도한 장치 지문은 남기지 않는다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    body = await request.json()
    from app.db import repository as repo
    repo.save_render_diagnostics(project["id"], user["id"], {
        "render_method": str(body.get("render_method", ""))[:20],
        "webgpu_ready": bool(body.get("webgpu_ready")),
        "webcodecs_ready": bool(body.get("webcodecs_ready")),
        "memory_mb": body.get("memory_mb"),
        "outcome": str(body.get("outcome", ""))[:20],
        "fallback_reason": str(body.get("fallback_reason", ""))[:100],
        "total_ms": int(body.get("total_ms") or 0),
        "user_agent": str(body.get("user_agent", "")),
    })
    return {"ok": True}


@app.get("/content/channels")
def content_channels_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("content_channels.html", _ctx(request, user, active="content_new", channels=SAMPLE_CHANNELS))


@app.get("/content/media")
def content_media_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("content_media.html", _ctx(request, user, active="content_new"))


@app.get("/content/thumbnail")
def content_thumbnail_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("content_thumbnail.html", _ctx(request, user, active="content_new", candidates=list(range(1, 9))))


@app.get("/archive")
def archive_list_page(request: Request, status: str = "all"):
    import json as _json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    from app.db import repository as repo
    all_projects = repo.list_projects_for_user(user["id"], limit=200)

    def _bucket(p_status: str) -> str:
        if p_status == "completed":
            return "completed"
        if p_status == "failed":
            return "failed"
        return "in_progress"

    items = []
    for p in all_projects:
        bucket = _bucket(p["status"])
        if status != "all" and status != bucket:
            continue
        snapshot = _json.loads(p.get("input_snapshot_json") or "{}")
        mp4 = repo.get_mp4_for_project(p["id"]) if bucket == "completed" else None
        items.append({
            "job_uid": p["job_uid"], "title": p["title"],
            "company": snapshot.get("company_name", "-"),
            "created_at": p["created_at"][:16].replace("T", " "),
            "status": p["status"], "bucket": bucket,
            "duration": f"{mp4['duration_seconds']:.0f}초" if mp4 and mp4["status"] == "success" else "-",
            "size_mb": round(mp4["file_size_bytes"] / 1024 / 1024, 1) if mp4 and mp4["status"] == "success" else None,
        })

    return templates.TemplateResponse("archive_list.html", _ctx(
        request, user, active="archive", items=items, status_filter=status,
    ))


@app.get("/archive/{job_uid}")
def archive_detail_page(request: Request, job_uid: str):
    import json as _json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/archive")

    from app.db import repository as repo
    from app.constants import CHANNEL_CODES, CHANNEL_LABELS

    snapshot = _json.loads(project.get("input_snapshot_json") or "{}")
    rows_by_code = {r["channel_code"]: r for r in repo.list_channel_results_for_project(project["id"])}
    channels = [
        {"code": c, "label": CHANNEL_LABELS[c], "row": rows_by_code.get(c)}
        for c in CHANNEL_CODES
    ]
    master = repo.get_tts_master_for_project(project["id"])
    srt = repo.get_srt_for_project(project["id"])
    mp4 = repo.get_mp4_for_project(project["id"])
    music_mix = repo.get_music_mix_for_project(project["id"])

    return templates.TemplateResponse("archive_detail.html", _ctx(
        request, user, active="archive", project=project, snapshot=snapshot, channels=channels,
        master=master, srt=srt, mp4=mp4, music_mix=music_mix,
    ))


@app.post("/archive/{job_uid}/delete")
def archive_delete(request: Request, job_uid: str):
    """프로젝트와 연결된 모든 결과(채널·TTS·SRT·MP4 등)를 완전히 삭제한다(복구 불가).
    DB는 FK CASCADE로 한 번에 정리되고, 실제 산출물 폴더도 함께 지운다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/archive")

    from app.db import repository as repo
    from app.config import JOBS_DIR
    import shutil

    repo.write_audit_log(user["id"], "project_deleted", target_type="project", target_id=project["id"])
    repo.delete_project(project["id"])
    job_dir = JOBS_DIR / job_uid
    if job_dir.is_dir():
        import time
        # Windows에서는 방금까지 재생/다운로드하던 영상 파일의 핸들이 즉시 풀리지
        # 않는 경우가 있어(파일 잠금), 짧은 재시도로 정리한다.
        for _attempt in range(5):
            shutil.rmtree(job_dir, ignore_errors=True)
            if not job_dir.is_dir():
                break
            time.sleep(0.5)
    return RedirectResponse(url="/archive", status_code=303)


@app.get("/mypage")
def mypage_page(request: Request, error: str = "", saved: int = 0, tab: str = "profile"):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    company = repo.get_default_company_for_user(user["id"])
    return templates.TemplateResponse("mypage.html", _ctx(
        request, user, active="mypage", error=error, saved=saved, tab=tab, company=company,
    ))


@app.post("/mypage/company")
def save_company(
    request: Request,
    company_name: str = Form(""),
    owner_name: str = Form(""),
    phone_number: str = Form(""),
    industry: str = Form(""),
    region: str = Form(""),
    address: str = Form(""),
    main_services: str = Form(""),
    target_customers: str = Form(""),
    core_strength: str = Form(""),
    tone_preference: str = Form(""),
    forbidden_words: str = Form(""),
    website_url: str = Form(""),
    free_request: str = Form(""),
):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not company_name.strip():
        return RedirectResponse(url="/mypage?error=업체명은+필수입니다.", status_code=303)
    from app.db import repository as repo
    fields = {
        "company_name": company_name.strip(), "owner_name": owner_name.strip(),
        "phone_number": phone_number.strip(), "industry": industry.strip(),
        "region": region.strip(), "address": address.strip(),
        "main_services": main_services.strip(), "target_customers": target_customers.strip(),
        "core_strength": core_strength.strip(), "tone_preference": tone_preference.strip(),
        "forbidden_words": forbidden_words.strip(), "website_url": website_url.strip(),
        "free_request": free_request.strip(),
    }
    existing = repo.get_default_company_for_user(user["id"])
    if existing:
        repo.update_company(existing["id"], user["id"], fields)
    else:
        repo.create_company(user["id"], fields)
    repo.write_audit_log(user["id"], "company_saved", target_type="company")
    return RedirectResponse(url="/mypage?saved=1", status_code=303)


@app.get("/subscription")
def subscription_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("subscription.html", _ctx(request, user, active="subscription"))


def _dir_size_bytes(path: Path) -> int:
    """폴더 전체 실제 사용량(바이트). 존재하지 않으면 0. 심볼릭 링크는 크기에 포함하지 않는다."""
    if not path.is_dir():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            fp = Path(dirpath) / name
            if fp.is_symlink():
                continue
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


@app.get("/admin")
def admin_dashboard_page(request: Request):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    from app.config import DATA_DIR, JOBS_DIR, LOGS_DIR
    import app.config as _cfg

    today_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00")

    total_users = repo.count_users_total()
    paid_users = repo.count_users_paid()
    job_counts = repo.count_projects_by_status_global()
    mp4_stats = repo.count_mp4_by_render_method()
    storage_bytes = _dir_size_bytes(DATA_DIR) + _dir_size_bytes(LOGS_DIR)

    recent_errors = []
    for p in repo.list_recent_failed_projects(5):
        recent_errors.append({
            "job_uid": p["job_uid"], "title": p["title"], "user_email": p["user_email"],
            "error_code": p.get("error_code", ""), "updated_at": p["updated_at"][:16].replace("T", " "),
        })

    return templates.TemplateResponse("admin_dashboard.html", _ctx(
        request, user, active="admin_dashboard",
        stats={
            "total_users": total_users,
            "active_users": repo.count_users_active(),
            "paid_users": paid_users,
            "free_users": max(total_users - paid_users, 0),
            "today_signups": repo.count_users_created_since(today_start),
            "month_signups": repo.count_users_created_since(month_start),
            "today_jobs": repo.count_projects_created_since(today_start),
            "month_jobs": repo.count_projects_created_since(month_start),
            "job_counts": job_counts,
            "ai_calls": repo.count_content_generation_calls(),
            "tts_success": repo.count_tts_master_success(),
            "mp4_local": mp4_stats["local"], "mp4_server": mp4_stats["server"], "mp4_fallback": mp4_stats["fallback"],
            "storage_mb": round(storage_bytes / 1024 / 1024, 1),
            "gemini_configured": bool(_cfg.GEMINI_API_KEY),
        },
        recent_errors=recent_errors,
    ))


@app.get("/admin/members")
def admin_members_page(request: Request, q: str = "", status: str = "", plan: str = ""):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    members = repo.search_users(q=q.strip(), status=status, plan=plan, limit=200)
    return templates.TemplateResponse("admin_members.html", _ctx(
        request, user, active="admin_members", members=members, q=q, status_filter=status, plan_filter=plan,
    ))


@app.get("/admin/members/{member_id}")
def admin_member_detail_page(request: Request, member_id: int, saved: int = 0):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    detail = repo.get_user_admin_detail(member_id)
    if not detail:
        return RedirectResponse(url="/admin/members")
    plans = repo.list_plans()
    return templates.TemplateResponse("admin_member_detail.html", _ctx(
        request, user, active="admin_members", detail=detail, plans=plans, saved=saved,
    ))


@app.post("/admin/members/{member_id}/status")
def admin_member_toggle_status(request: Request, member_id: int, new_status: str = Form(...)):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
    if new_status not in ("active", "inactive"):
        return RedirectResponse(url=f"/admin/members/{member_id}")
    from app.db import repository as repo
    target = repo.get_user_by_id(member_id)
    if target:
        repo.update_user_status(member_id, new_status)
        repo.write_audit_log(
            user["id"], "admin_member_status_changed", target_type="user", target_id=member_id,
            metadata_json=f'{{"from":"{target.get("status")}","to":"{new_status}"}}',
        )
    return RedirectResponse(url=f"/admin/members/{member_id}?saved=1", status_code=303)


@app.post("/admin/members/{member_id}/notes")
def admin_member_save_notes(request: Request, member_id: int, admin_notes: str = Form("")):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
    from app.db import repository as repo
    if repo.get_user_by_id(member_id):
        repo.update_user_admin_notes(member_id, admin_notes.strip()[:2000])
        repo.write_audit_log(user["id"], "admin_member_note_saved", target_type="user", target_id=member_id)
    return RedirectResponse(url=f"/admin/members/{member_id}?saved=1", status_code=303)


@app.post("/admin/members/{member_id}/usage")
def admin_member_set_usage(request: Request, member_id: int, usage_limit_override: str = Form("")):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
    from app.db import repository as repo
    if repo.get_user_by_id(member_id):
        value = int(usage_limit_override) if usage_limit_override.strip().isdigit() else None
        repo.update_user_usage_override(member_id, value)
        repo.write_audit_log(
            user["id"], "admin_member_usage_adjusted", target_type="user", target_id=member_id,
            metadata_json=f'{{"usage_limit_override":{value if value is not None else "null"}}}',
        )
    return RedirectResponse(url=f"/admin/members/{member_id}?saved=1", status_code=303)


@app.post("/admin/members/{member_id}/plan")
def admin_member_change_plan(request: Request, member_id: int, plan_id: int = Form(...)):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
    from app.db import repository as repo
    if repo.get_user_by_id(member_id):
        now = datetime.now(timezone.utc)
        started = now.strftime("%Y-%m-%dT%H:%M:%S")
        ends = now.replace(year=now.year + 1).strftime("%Y-%m-%dT%H:%M:%S")
        repo.assign_subscription(member_id, plan_id, started, ends)
        repo.write_audit_log(
            user["id"], "admin_member_plan_changed", target_type="user", target_id=member_id,
            metadata_json=f'{{"plan_id":{plan_id}}}',
        )
    return RedirectResponse(url=f"/admin/members/{member_id}?saved=1", status_code=303)


@app.get("/admin/jobs")
def admin_jobs_page(request: Request, q: str = "", status: str = "all"):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    rows = repo.list_all_projects_admin(q=q.strip(), status=status, limit=200)
    jobs = [{
        "job_uid": p["job_uid"], "title": p["title"], "user_email": p["user_email"],
        "company_name": p.get("company_name") or "-", "status": p["status"],
        "error_code": p.get("error_code", ""),
        "created_at": p["created_at"][:16].replace("T", " "),
        "updated_at": p["updated_at"][:16].replace("T", " "),
    } for p in rows]
    return templates.TemplateResponse("admin_jobs.html", _ctx(
        request, user, active="admin_jobs", jobs=jobs, q=q, status_filter=status,
    ))


@app.get("/admin/storage")
def admin_storage_page(request: Request, q: str = "", action: str = ""):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    from app.config import DATA_DIR, JOBS_DIR, MEDIA_DIR, LOGS_DIR, BACKUPS_DIR

    def _mb(p: Path) -> float:
        return round(_dir_size_bytes(p) / 1024 / 1024, 2)

    folders = [
        {"label": "DB", "path": "data/storymaker_claude.db",
         "mb": round((DATA_DIR / "storymaker_claude.db").stat().st_size / 1024 / 1024, 2)
         if (DATA_DIR / "storymaker_claude.db").is_file() else 0},
        {"label": "작업 산출물(음성·SRT·MP4·썸네일)", "path": "data/jobs", "mb": _mb(JOBS_DIR)},
        {"label": "미디어 임시", "path": "data/media", "mb": _mb(MEDIA_DIR)},
        {"label": "로그", "path": "logs", "mb": _mb(LOGS_DIR)},
        {"label": "백업", "path": "backups", "mb": _mb(BACKUPS_DIR)},
    ]

    logs = repo.search_audit_logs(q=q.strip(), action=action, limit=100)
    audit_rows = [{
        "created_at": r["created_at"][:19].replace("T", " "),
        "user_email": r.get("user_email") or "-",
        "action": r["action"], "target_type": r.get("target_type") or "-",
        "target_id": r.get("target_id"),
    } for r in logs]

    return templates.TemplateResponse("admin_storage.html", _ctx(
        request, user, active="admin_storage", folders=folders, audit_rows=audit_rows,
        actions=repo.list_distinct_audit_actions(), q=q, action_filter=action,
    ))


def _run_version_check(exe_path: Path) -> dict:
    """실행파일 존재 여부만이 아니라 실제로 기동해 버전 문자열을 얻는다(살아있는 실행 파일인지 검사)."""
    if not exe_path.is_file():
        return {"ready": False, "detail": "실행 파일 없음"}
    import subprocess
    try:
        proc = subprocess.run(
            [str(exe_path), "-version"], capture_output=True, text=True, timeout=5,
        )
        first_line = (proc.stdout or proc.stderr or "").splitlines()[0] if (proc.stdout or proc.stderr) else ""
        return {"ready": proc.returncode == 0, "detail": first_line[:120] or f"exit code {proc.returncode}"}
    except Exception as exc:  # 실행 자체가 실패한 경우도 진단 대상이므로 그대로 노출
        return {"ready": False, "detail": f"실행 실패: {exc}"}


@app.get("/admin/diagnostics")
def admin_diagnostics_page(request: Request):
    user = _require_admin_or_none(request)
    if not user:
        return RedirectResponse(url="/dashboard", status_code=303)
    from app.db import repository as repo
    from app.config import SUPERTONIC_MODEL_DIR, FFMPEG_PATH, FFPROBE_PATH

    tts_counts = repo.count_tts_master_by_status()
    voice_stats = []
    for v in repo.count_tts_sentences_by_voice():
        voice_stats.append({
            "voice": v["voice"], "total": v["total"], "success": v["success_n"] or 0,
            "failed": v["failed_n"] or 0,
            "avg_duration": round(v["avg_duration"], 2) if v["avg_duration"] else 0,
            "avg_gen_seconds": round(v["avg_gen_seconds"], 2) if v["avg_gen_seconds"] else None,
        })

    recent_tts_failures = []
    for f in repo.list_recent_tts_failures(10):
        recent_tts_failures.append({
            "job_uid": f["job_uid"], "title": f["title"], "user_email": f["user_email"],
            "sentence_index": f["sentence_index"], "error_code": f["error_code"] or "미기록",
            "updated_at": f["updated_at"][:16].replace("T", " "),
        })

    render_rates = repo.get_render_success_rates()
    fallback_reasons = repo.count_fallback_reasons()
    browser_summary = repo.get_browser_feature_detection_summary()
    recent_mp4_rows = repo.list_recent_mp4_with_meta(15)
    recent_mp4 = []
    sample_video_job_uid = ""
    for m in recent_mp4_rows:
        if not sample_video_job_uid and m["status"] == "success":
            sample_video_job_uid = m["job_uid"]
        recent_mp4.append({
            "job_uid": m["job_uid"], "title": m["title"], "user_email": m["user_email"],
            "render_method": "내 PC" if m["render_method"] == "local" else "서버",
            "status": m["status"], "width": m["width"], "height": m["height"],
            "duration_seconds": m["duration_seconds"], "fallback_reason": m.get("fallback_reason") or "",
            "updated_at": m["updated_at"][:16].replace("T", " "),
        })

    ffmpeg_check = _run_version_check(FFMPEG_PATH)
    ffprobe_check = _run_version_check(FFPROBE_PATH)

    return templates.TemplateResponse("admin_diagnostics.html", _ctx(
        request, user, active="admin_diagnostics",
        tts_counts=tts_counts, voice_stats=voice_stats, recent_tts_failures=recent_tts_failures,
        render_rates=render_rates, fallback_reasons=fallback_reasons, browser_summary=browser_summary,
        recent_mp4=recent_mp4, sample_video_job_uid=sample_video_job_uid,
        supertonic_ready=SUPERTONIC_MODEL_DIR.is_dir() and any(SUPERTONIC_MODEL_DIR.iterdir()) if SUPERTONIC_MODEL_DIR.is_dir() else False,
        ffmpeg_check=ffmpeg_check, ffprobe_check=ffprobe_check,
        checked_at=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    ))


@app.get("/content/music-preview/{filename}")
def music_preview(request: Request, filename: str):
    """배경음악 미리듣기. runtime/music/mp3 원본을 그대로 스트리밍한다(복사 없음)."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.content.music import resolve_music_path
    from app.media.range_response import range_file_response
    # 파일명만 받아 MUSIC_LIBRARY_DIR 안에서만 해석하므로 경로 이탈이 불가능하다.
    safe_name = Path(filename).name
    path = resolve_music_path(f"runtime/music/mp3/{safe_name}")
    if not path:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="음악 파일을 찾을 수 없습니다.")
    return range_file_response(request, path, "audio/mpeg")


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "stage": "3-auth",
        "time": datetime.now(timezone.utc).isoformat(),
        "db_integrity": integrity_check(),
        "db_journal_mode": current_journal_mode(),
    }
