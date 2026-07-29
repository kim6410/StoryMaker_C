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

app = FastAPI(title="StoryMaker", version="0.3.0-auth")
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
    {"key": "companies", "label": "업체 관리", "href": "/companies", "icon": "building"},
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

def _ctx(request: Request, user: dict, *, active: str = "", **extra) -> dict:
    admin_menu = ADMIN_MENU if str(user.get("role")) == "admin" else []
    return {
        "request": request,
        "app_name": "StoryMaker",
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
def root(request: Request, logged_out: int = 0):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("landing.html", {
        "request": request, "app_name": "StoryMaker", "logged_out": logged_out,
    })


@app.get("/login")
def login_page(request: Request, error: str = "", verified: int = 0, verify_failed: int = 0,
               reset: int = 0, logged_out: int = 0, password_changed: int = 0):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {
        "request": request, "app_name": "StoryMaker",
        "error": error, "verified": verified, "verify_failed": verify_failed,
        "reset": reset, "logged_out": logged_out, "password_changed": password_changed,
    })


@app.get("/register")
def register_page(request: Request, error: str = ""):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("register.html", {"request": request, "app_name": "StoryMaker", "error": error})


@app.get("/verify-email")
def verify_email_page(request: Request, email: str = "", dev_link: str = ""):
    return templates.TemplateResponse("verify_email.html", {
        "request": request, "app_name": "StoryMaker", "email": email, "dev_link": dev_link,
    })


@app.get("/forgot-password")
def forgot_password_page(request: Request, error: str = "", sent: int = 0, dev_link: str = "", expired: int = 0):
    return templates.TemplateResponse("forgot_password.html", {
        "request": request, "app_name": "StoryMaker",
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
def content_new_page(request: Request, error: str = "", company_id: int = 0):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    from app.content.music import list_music_files

    companies = [c for c in repo.list_companies_for_user(user["id"]) if c["is_active"]]
    company = None
    if company_id:
        company = next((c for c in companies if c["id"] == company_id), None)
    if not company:
        company = repo.get_default_company_for_user(user["id"])
        company = company if (company and company["is_active"]) else (companies[0] if companies else None)
    media = repo.list_company_media(company["id"]) if company else []
    music_items = list_music_files()
    return templates.TemplateResponse("content_new.html", _ctx(
        request, user, active="content_new", company=company, companies=companies, media=media,
        music_items=music_items, error=error,
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
    company_id: int = Form(0),
    media_ids: list[int] = Form([]),
    new_media_files: list[UploadFile] = File([]),
):
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not topic.strip():
        return RedirectResponse(
            url=f"/content/new?company_id={company_id}&error=제작+주제를+입력해+주세요.", status_code=303
        )

    from app.db import repository as repo
    from app.content.music import resolve_music_path

    company = repo.get_company_owned(company_id, user["id"]) if company_id else None
    if not company:
        company = repo.get_default_company_for_user(user["id"])
    if not company:
        return RedirectResponse(url="/content/new?error=먼저+업체를+등록해+주세요.", status_code=303)
    if music_relative_path and not resolve_music_path(music_relative_path):
        music_relative_path = ""

    # 이 화면에서 바로 새로 업로드한 파일이 있으면 먼저 업체 미디어로 저장한다(마이페이지
    # 업체관리를 먼저 들르지 않아도 바로 사진을 올릴 수 있게).
    new_media_ids, _saved, _skipped = _save_company_media_files(company, new_media_files)

    # 선택한 미디어가 실제로 이 업체 소유인지 다시 확인한다(다른 업체 미디어 ID를
    # 임의로 붙여넣는 것을 방지). 아직 영상 제작 파이프라인이 실제 사진을 장면
    # 배경으로 쓰지는 않으므로(그라디언트 장면 유지, 단계8 계약 보존), 여기서는
    # 스냅샷에 참조만 남겨 다음 단계 확장에 대비한다(미완료 항목 - 업무일지에 기록).
    owned_media_ids = {m["id"] for m in repo.list_company_media(company["id"])}
    selected_media_ids = [mid for mid in media_ids if mid in owned_media_ids] + new_media_ids
    if not selected_media_ids:
        return RedirectResponse(
            url=f"/content/new?company_id={company['id']}&error=사진%2F영상을+1개+이상+선택하거나+업로드해+주세요.",
            status_code=303,
        )

    # 마이페이지 업체 정보와 별개로, 이번 제작 요청 당시 값을 스냅샷으로 고정한다.
    # (나중에 업체 정보가 바뀌어도 이 작업의 과거 결과는 변하지 않는다.)
    snapshot = {
        "company_name": company["company_name"], "owner_name": company["owner_name"],
        "phone_number": company["phone_number"], "industry": company["industry"],
        "region": company["region"], "main_services": company["main_services"],
        "target_customers": company["target_customers"],
        "topic": topic.strip(),
        "keywords": keywords.strip(),
        "tone_preference": tone_preference.strip(),
        "content_length": content_length.strip() or "medium",
        "selected_media_ids": selected_media_ids,
    }
    project = repo.create_content_project(
        user_id=user["id"],
        title=topic.strip(),
        company_id=company["id"],
        input_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        music_relative_path=music_relative_path,
        voice_preference=voice_preference.strip() or "female",
    )
    repo.write_audit_log(user["id"], "content_job_created", target_type="project", target_id=project["id"])

    # 딸깍 제작: 입력→사진선택 제출 한 번으로 AI 원고 생성까지 이어서 시도한다(Dell Beta
    # UX 참고). 상태 페이지에서 별도로 "생성하기"를 다시 누르는 중간 클릭을 없앤다.
    # 실패해도 프로젝트 자체는 이미 저장돼 있으므로, 상태 페이지의 기존 재시도 버튼으로
    # 그대로 이어서 재시도할 수 있다(복구 가능성 우선, 별도 롤백 불필요).
    from app.ai.service import generate_channels_for_project
    try:
        outcome = generate_channels_for_project(project)
    except Exception:
        return RedirectResponse(
            url=f"/content/job/{project['job_uid']}?gen_error=unknown_provider_error", status_code=303
        )
    repo.write_audit_log(
        user["id"], "content_generation_attempted", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{project['job_uid']}#section-channels", status_code=303)
    return RedirectResponse(
        url=f"/content/job/{project['job_uid']}?gen_error={outcome.error_code}", status_code=303
    )


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
def content_job_status(
    request: Request, job_uid: str, gen_error: str = "", channel_error: str = "",
    mp4_error: str = "", thumb_error: str = "", thumb_saved: int = 0, selected_index: int = -1,
):
    """단계11 보완: 입력→SNS8채널→음성자막→MP4→썸네일까지 예전에는 페이지 5개로 나뉘어
    있었지만(Dell Beta의 "딸깍 제작" 한 페이지 UX 참고), 이제 이 한 라우트가 전부 모아서
    한 화면에 위→아래로 이어서 보여준다. 각 하위 기능(채널 재생성, TTS 문장별 재생성,
    MP4 로컬/서버 렌더, 썸네일 후보·선택)의 실제 처리 로직과 라우트는 전혀 바꾸지 않고,
    그 라우트들이 끝나면 이 허브 URL로 돌아오도록 리다이렉트 대상만 바꿨다(기존 정상
    기능 보존 우선)."""
    import json
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    from app.constants import CHANNEL_CODES, CHANNEL_LABELS, GEMINI_ERROR_CODES
    from app.content.steps import build_step_states

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

    # SNS 8채널
    rows_by_code = {r["channel_code"]: r for r in repo.list_channel_results_for_project(project["id"])}
    channels = []
    for code in CHANNEL_CODES:
        row = rows_by_code.get(code)
        channels.append({
            "code": code, "label": CHANNEL_LABELS[code], "row": row,
            "hashtags": json.loads(row["hashtags_json"]) if row else [],
        })
    video_script = repo.get_video_script_for_project(project["id"])
    scene_sentences = json.loads(video_script["scene_sentences_json"]) if video_script else []
    channel_error_message = ""
    if channel_error and channel_error in GEMINI_ERROR_CODES:
        from app.ai.service import USER_ERROR_MESSAGES
        channel_error_message = USER_ERROR_MESSAGES.get(channel_error, "")

    # 음성·자막(TTS/SRT)
    sentences = repo.list_tts_sentences_for_project(project["id"])
    master = repo.get_tts_master_for_project(project["id"])
    srt = repo.get_srt_for_project(project["id"])
    phone_number = snapshot.get("phone_number", "")
    phone_tts_preview = ""
    if phone_number:
        from app.tts.normalizer import normalize_for_tts
        phone_tts_preview = normalize_for_tts(phone_number)

    # 영상(MP4)
    mp4 = repo.get_mp4_for_project(project["id"])
    music_mix = repo.get_music_mix_for_project(project["id"])
    scenes = repo.list_scenes_for_project(project["id"])
    has_tts = bool(master and master["status"] == "success" and srt and srt["status"] == "success")
    mp4_error_message = ""
    if mp4_error:
        from app.media.service import USER_MP4_ERROR_MESSAGES
        mp4_error_message = USER_MP4_ERROR_MESSAGES.get(mp4_error, "")
    zoom_labels = {"zoom_in": "천천히 확대", "zoom_out": "천천히 축소", "static": "고정 화면"}

    # 대표 썸네일
    from app.media import thumbnail_service as thumbsvc
    primary = repo.get_primary_thumbnail_for_project(project["id"])
    has_candidates = thumbsvc.candidates_ready(job_uid)
    thumb_error_message = thumbsvc.USER_THUMBNAIL_ERROR_MESSAGES.get(thumb_error, "")

    return templates.TemplateResponse("content_job_status.html", _ctx(
        request, user, active="content_new", project=project, snapshot=snapshot,
        gemini_configured=gemini_configured, result=result, last_generation=last_generation,
        gen_error_message=gen_error_message, steps=build_step_states(project),
        channels=channels, video_script=video_script, scene_sentences=scene_sentences,
        channel_error_message=channel_error_message,
        sentences=sentences, master=master, srt=srt, has_script=bool(video_script),
        phone_number=phone_number, phone_tts_preview=phone_tts_preview,
        mp4=mp4, music_mix=music_mix, scenes=scenes, has_tts=has_tts,
        mp4_error_message=mp4_error_message, zoom_labels=zoom_labels,
        primary=primary, has_candidates=has_candidates,
        candidate_indexes=list(range(thumbsvc.CANDIDATE_COUNT)),
        thumb_error_message=thumb_error_message, thumb_saved=thumb_saved, selected_index=selected_index,
    ))


@app.post("/content/job/{job_uid}/generate")
def content_job_generate(request: Request, job_uid: str):
    """6B단계: 실제 Gemini API를 호출해 SNS 8채널 + 숏폼 영상원고를 생성한다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

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
        return RedirectResponse(url=f"/content/job/{job_uid}#section-channels", status_code=303)
    return RedirectResponse(url=f"/content/job/{job_uid}?gen_error={outcome.error_code}", status_code=303)


@app.get("/content/job/{job_uid}/channels")
def content_job_channels_page(request: Request, job_uid: str, channel_error: str = ""):
    """예전 개별 페이지 URL. 단계11부터 /content/job/{job_uid} 한 페이지로 합쳐졌으므로
    같은 정보가 담긴 허브 URL로 그대로 이어준다(기존 북마크·링크 호환)."""
    suffix = f"?channel_error={channel_error}" if channel_error else ""
    return RedirectResponse(url=f"/content/job/{job_uid}{suffix}#section-channels", status_code=303)


@app.post("/content/job/{job_uid}/channels/{channel_code}/regenerate")
def content_job_channel_regenerate(request: Request, job_uid: str, channel_code: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

    from app.ai.service import regenerate_channel_for_project
    from app.db import repository as repo
    try:
        outcome = regenerate_channel_for_project(project, channel_code)
    except Exception:
        return RedirectResponse(
            url=f"/content/job/{job_uid}?channel_error=unknown_provider_error#section-channels", status_code=303
        )
    repo.write_audit_log(
        user["id"], "channel_regenerated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"channel": "{channel_code}", "ok": {str(outcome.ok).lower()}}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}#section-channels", status_code=303)
    return RedirectResponse(
        url=f"/content/job/{job_uid}?channel_error={outcome.error_code}#section-channels", status_code=303
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
        return RedirectResponse(url="/content/new", status_code=303)

    from app.db import repository as repo
    from app.constants import CHANNEL_CODES
    if channel_code not in CHANNEL_CODES:
        return RedirectResponse(url=f"/content/job/{job_uid}#section-channels", status_code=303)

    hashtag_list = [h.strip() for h in hashtags.split(",") if h.strip()]
    repo.update_channel_result_manual_edit(
        project["id"], channel_code, title.strip(), body.strip(),
        json.dumps(hashtag_list, ensure_ascii=False), cta.strip(),
    )
    repo.write_audit_log(user["id"], "channel_manual_edit", target_type="project", target_id=project["id"])
    return RedirectResponse(url=f"/content/job/{job_uid}#section-channels", status_code=303)


@app.post("/content/job/{job_uid}/channels/{channel_code}/revert")
def content_job_channel_revert(request: Request, job_uid: str, channel_code: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

    from app.db import repository as repo
    repo.revert_channel_result(project["id"], channel_code)
    repo.write_audit_log(user["id"], "channel_reverted", target_type="project", target_id=project["id"])
    return RedirectResponse(url=f"/content/job/{job_uid}#section-channels", status_code=303)


@app.post("/content/job/{job_uid}/tts/generate")
def content_job_tts_generate(request: Request, job_uid: str):
    """단계7: 영상원고 문장을 정규화해 Supertonic으로 TTS를 생성하고, 성공하면 SRT까지 만든다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

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
    return RedirectResponse(url=f"/content/job/{job_uid}#section-tts", status_code=303)


@app.post("/content/job/{job_uid}/tts/sentence/{sentence_index}/regenerate")
def content_job_tts_sentence_regenerate(request: Request, job_uid: str, sentence_index: int):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

    from app.tts.service import regenerate_tts_sentence
    from app.db import repository as repo
    outcome = regenerate_tts_sentence(project, sentence_index)
    repo.write_audit_log(user["id"], "tts_sentence_regenerated", target_type="project", target_id=project["id"])
    if outcome.ok and outcome.failed_sentences == 0:
        from app.subtitle.srt_builder import build_srt_for_project
        build_srt_for_project(project)
    return RedirectResponse(url=f"/content/job/{job_uid}#section-tts", status_code=303)


@app.get("/content/job/{job_uid}/tts")
def content_job_tts_page(request: Request, job_uid: str):
    """예전 개별 페이지 URL. 단계11부터 허브 페이지로 합쳐졌으므로 그대로 이어준다."""
    return RedirectResponse(url=f"/content/job/{job_uid}#section-tts", status_code=303)


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
        return RedirectResponse(url="/content/new", status_code=303)

    from app.media.service import generate_mp4_for_project
    from app.db import repository as repo
    outcome = generate_mp4_for_project(project)
    repo.write_audit_log(
        user["id"], "mp4_generated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}#section-mp4", status_code=303)
    return RedirectResponse(url=f"/content/job/{job_uid}?mp4_error={outcome.error_code}#section-mp4", status_code=303)


@app.get("/content/job/{job_uid}/mp4")
def content_job_mp4_page(request: Request, job_uid: str, mp4_error: str = ""):
    """예전 개별 페이지 URL. 단계11부터 허브 페이지로 합쳐졌으므로 그대로 이어준다."""
    suffix = f"?mp4_error={mp4_error}" if mp4_error else ""
    return RedirectResponse(url=f"/content/job/{job_uid}{suffix}#section-mp4", status_code=303)


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


@app.get("/content/job/{job_uid}/mp4/scene-image/{scene_index}")
def content_job_scene_image(request: Request, job_uid: str, scene_index: int):
    """단계11 보완: 로컬(WebCodecs) 렌더가 render-manifest.json의 image_url로 이 장면의
    배경 사진을 받아오는 경로. 이 작업 소유의 장면에 배정된 파일만 내려준다(임의 경로 접근 금지)."""
    from fastapi import HTTPException
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    from app.db import repository as repo
    from app.config import PathEscapeError, to_absolute_path
    from fastapi.responses import FileResponse
    scenes = repo.list_scenes_for_project(project["id"])
    scene = next((s for s in scenes if s["scene_index"] == scene_index), None)
    if not scene or not scene["image_relative_path"]:
        raise HTTPException(status_code=404, detail="이 장면에는 이미지가 없습니다.")
    try:
        path = to_absolute_path(scene["image_relative_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
    return FileResponse(path)


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
        return RedirectResponse(url="/content/new", status_code=303)

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
        return RedirectResponse(url="/content/new", status_code=303)

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


@app.get("/content/job/{job_uid}/thumbnail")
def content_job_thumbnail_page(request: Request, job_uid: str, thumb_error: str = "", saved: int = 0,
                                selected_index: int = -1):
    """예전 개별 페이지 URL. 단계11부터 허브 페이지로 합쳐졌으므로 그대로 이어준다."""
    params = []
    if thumb_error:
        params.append(f"thumb_error={thumb_error}")
    if saved:
        params.append("thumb_saved=1")
    if selected_index >= 0:
        params.append(f"selected_index={selected_index}")
    suffix = ("?" + "&".join(params)) if params else ""
    return RedirectResponse(url=f"/content/job/{job_uid}{suffix}#section-thumbnail", status_code=303)


@app.post("/content/job/{job_uid}/thumbnail/generate")
def content_job_thumbnail_generate(request: Request, job_uid: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

    from app.media import thumbnail_service as thumbsvc
    from app.db import repository as repo
    outcome = thumbsvc.ensure_candidates(project)
    repo.write_audit_log(
        user["id"], "thumbnail_candidates_generated", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "error_code": "{outcome.error_code}"}}',
    )
    if outcome.ok:
        return RedirectResponse(url=f"/content/job/{job_uid}#section-thumbnail", status_code=303)
    return RedirectResponse(
        url=f"/content/job/{job_uid}?thumb_error={outcome.error_code}#section-thumbnail", status_code=303
    )


@app.post("/content/job/{job_uid}/thumbnail/select")
def content_job_thumbnail_select(request: Request, job_uid: str, candidate_index: int = Form(...)):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new", status_code=303)

    from app.media import thumbnail_service as thumbsvc
    from app.db import repository as repo
    outcome = thumbsvc.select_candidate(project, user["id"], candidate_index)
    repo.write_audit_log(
        user["id"], "thumbnail_selected", target_type="project", target_id=project["id"],
        metadata_json=f'{{"ok": {str(outcome.ok).lower()}, "candidate_index": {candidate_index}}}',
    )
    if outcome.ok:
        return RedirectResponse(
            url=f"/content/job/{job_uid}?thumb_saved=1&selected_index={candidate_index}#section-thumbnail",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/content/job/{job_uid}?thumb_error={outcome.error_code}#section-thumbnail", status_code=303
    )


@app.get("/content/job/{job_uid}/thumbnail/candidate/{index}")
def content_job_thumbnail_candidate_image(request: Request, job_uid: str, index: int):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    from app.media import thumbnail_service as thumbsvc
    path = thumbsvc.candidate_path(job_uid, index)
    if not path:
        raise HTTPException(status_code=404, detail="썸네일 후보를 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/content/job/{job_uid}/thumbnail/image")
def content_job_thumbnail_image(request: Request, job_uid: str):
    """대표 썸네일 이미지(보관함 카드·상세·다운로드에서 공통으로 사용)."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    from app.db import repository as repo
    from app.config import PathEscapeError, to_absolute_path
    thumb = repo.get_primary_thumbnail_for_project(project["id"])
    if not thumb:
        raise HTTPException(status_code=404, detail="대표 썸네일이 아직 없습니다.")
    try:
        path = to_absolute_path(thumb["relative_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="썸네일 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="썸네일 파일을 찾을 수 없습니다.")
    return FileResponse(path, media_type="image/jpeg", filename="thumbnail.jpg")


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
        thumb = repo.get_primary_thumbnail_for_project(p["id"]) if bucket == "completed" else None
        items.append({
            "job_uid": p["job_uid"], "title": p["title"],
            "company": snapshot.get("company_name", "-"),
            "created_at": p["created_at"][:16].replace("T", " "),
            "status": p["status"], "bucket": bucket,
            "duration": f"{mp4['duration_seconds']:.0f}초" if mp4 and mp4["status"] == "success" else "-",
            "size_mb": round(mp4["file_size_bytes"] / 1024 / 1024, 1) if mp4 and mp4["status"] == "success" else None,
            "has_thumbnail": bool(thumb),
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
    thumbnail = repo.get_primary_thumbnail_for_project(project["id"])

    return templates.TemplateResponse("archive_detail.html", _ctx(
        request, user, active="archive", project=project, snapshot=snapshot, channels=channels,
        master=master, srt=srt, mp4=mp4, music_mix=music_mix, thumbnail=thumbnail,
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
        return RedirectResponse(url="/archive", status_code=303)

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


def _get_owned_company_or_none(company_id: int, user: dict):
    """company_id로 업체를 찾되, 본인 소유이거나 관리자일 때만 반환한다."""
    from app.db import repository as repo
    if str(user.get("role")) == "admin":
        return repo.get_company(company_id)
    return repo.get_company_owned(company_id, user["id"])


def _company_form_fields(
    company_name: str, owner_name: str, phone_number: str, industry: str, industry_detail: str,
    region_metro: str, region_district: str, region_dong: str, road_address: str, detail_address: str,
    main_services: str, target_customers: str, description: str, core_strength: str, keywords: str,
    must_include: str, forbidden_words: str, business_hours: str, website_url: str,
    naver_place_url: str, google_business_url: str, tone_preference: str, free_request: str,
) -> dict:
    return {
        "company_name": company_name.strip(), "owner_name": owner_name.strip(),
        "phone_number": phone_number.strip(), "industry": industry.strip(),
        "industry_detail": industry_detail.strip(),
        "region": " ".join(p for p in [region_metro.strip(), region_district.strip(), region_dong.strip()] if p),
        "region_metro": region_metro.strip(), "region_district": region_district.strip(),
        "region_dong": region_dong.strip(),
        "address": road_address.strip(), "road_address": road_address.strip(),
        "detail_address": detail_address.strip(),
        "main_services": main_services.strip(), "target_customers": target_customers.strip(),
        "description": description.strip(), "core_strength": core_strength.strip(),
        "keywords": keywords.strip(), "must_include": must_include.strip(),
        "forbidden_words": forbidden_words.strip(), "business_hours": business_hours.strip(),
        "website_url": website_url.strip(), "naver_place_url": naver_place_url.strip(),
        "google_business_url": google_business_url.strip(),
        "tone_preference": tone_preference.strip(), "free_request": free_request.strip(),
    }


def _validate_company_fields(fields: dict) -> str:
    """서버 쪽 최소 검증. 문제 있으면 한글 오류 문구, 없으면 빈 문자열."""
    import re
    if not fields["company_name"]:
        return "업체명은 필수입니다."
    phone = fields["phone_number"]
    if phone and not re.fullmatch(r"[0-9\-]{7,20}", phone):
        return "전화번호 형식이 올바르지 않습니다(숫자와 하이픈만 입력해 주세요)."
    for label, key in (("홈페이지", "website_url"), ("네이버 플레이스", "naver_place_url"), ("구글 비즈니스", "google_business_url")):
        val = fields.get(key, "")
        if val and not re.match(r"^https?://", val):
            return f"{label} 주소는 http:// 또는 https://로 시작해야 합니다."
    return ""


@app.get("/companies")
def companies_list_page(request: Request, saved: int = 0):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    companies = repo.list_companies_for_user(user["id"])
    return templates.TemplateResponse("companies_list.html", _ctx(
        request, user, active="companies", companies=companies, saved=saved,
    ))


@app.get("/companies/new")
def companies_new_page(request: Request, error: str = ""):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("company_form.html", _ctx(
        request, user, active="companies", company=None, media=[], error=error, mode="new",
    ))


@app.post("/companies")
def companies_create(
    request: Request,
    company_name: str = Form(""), owner_name: str = Form(""), phone_number: str = Form(""),
    industry: str = Form(""), industry_detail: str = Form(""),
    region_metro: str = Form(""), region_district: str = Form(""), region_dong: str = Form(""),
    road_address: str = Form(""), detail_address: str = Form(""),
    main_services: str = Form(""), target_customers: str = Form(""),
    description: str = Form(""), core_strength: str = Form(""), keywords: str = Form(""),
    must_include: str = Form(""), forbidden_words: str = Form(""), business_hours: str = Form(""),
    website_url: str = Form(""), naver_place_url: str = Form(""), google_business_url: str = Form(""),
    tone_tags: list[str] = Form([]), free_request: str = Form(""),
):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    tone_preference = ",".join(t.strip() for t in tone_tags if t.strip())
    fields = _company_form_fields(
        company_name, owner_name, phone_number, industry, industry_detail,
        region_metro, region_district, region_dong, road_address, detail_address,
        main_services, target_customers, description, core_strength, keywords,
        must_include, forbidden_words, business_hours, website_url,
        naver_place_url, google_business_url, tone_preference, free_request,
    )
    err = _validate_company_fields(fields)
    if err:
        from urllib.parse import quote
        return RedirectResponse(url=f"/companies/new?error={quote(err)}", status_code=303)
    company_id = repo.create_company(user["id"], fields)
    repo.write_audit_log(user["id"], "company_created", target_type="company", target_id=company_id)
    return RedirectResponse(url=f"/companies/{company_id}?saved=1", status_code=303)


@app.get("/companies/{company_id}")
def company_detail_page(request: Request, company_id: int, error: str = "", saved: int = 0):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies")
    from app.db import repository as repo
    media = repo.list_company_media(company_id)
    return templates.TemplateResponse("company_form.html", _ctx(
        request, user, active="companies", company=company, media=media, error=error,
        saved=saved, mode="edit",
    ))


@app.post("/companies/{company_id}")
def companies_update(
    request: Request, company_id: int,
    company_name: str = Form(""), owner_name: str = Form(""), phone_number: str = Form(""),
    industry: str = Form(""), industry_detail: str = Form(""),
    region_metro: str = Form(""), region_district: str = Form(""), region_dong: str = Form(""),
    road_address: str = Form(""), detail_address: str = Form(""),
    main_services: str = Form(""), target_customers: str = Form(""),
    description: str = Form(""), core_strength: str = Form(""), keywords: str = Form(""),
    must_include: str = Form(""), forbidden_words: str = Form(""), business_hours: str = Form(""),
    website_url: str = Form(""), naver_place_url: str = Form(""), google_business_url: str = Form(""),
    tone_tags: list[str] = Form([]), free_request: str = Form(""),
):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)
    from app.db import repository as repo
    tone_preference = ",".join(t.strip() for t in tone_tags if t.strip())
    fields = _company_form_fields(
        company_name, owner_name, phone_number, industry, industry_detail,
        region_metro, region_district, region_dong, road_address, detail_address,
        main_services, target_customers, description, core_strength, keywords,
        must_include, forbidden_words, business_hours, website_url,
        naver_place_url, google_business_url, tone_preference, free_request,
    )
    err = _validate_company_fields(fields)
    if err:
        from urllib.parse import quote
        return RedirectResponse(url=f"/companies/{company_id}?error={quote(err)}", status_code=303)
    repo.update_company(company_id, company["user_id"], fields)
    repo.write_audit_log(user["id"], "company_updated", target_type="company", target_id=company_id)
    return RedirectResponse(url=f"/companies/{company_id}?saved=1", status_code=303)


@app.post("/companies/{company_id}/default")
def companies_set_default(request: Request, company_id: int):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)
    from app.db import repository as repo
    ok = repo.set_default_company(company_id, company["user_id"])
    if ok:
        repo.write_audit_log(user["id"], "company_default_changed", target_type="company", target_id=company_id)
    return RedirectResponse(url="/companies?saved=1", status_code=303)


@app.post("/companies/{company_id}/active")
def companies_set_active(request: Request, company_id: int, is_active: str = Form(...)):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)
    from app.db import repository as repo
    repo.set_company_active(company_id, company["user_id"], is_active == "1")
    repo.write_audit_log(
        user["id"], "company_active_changed", target_type="company", target_id=company_id,
        metadata_json=f'{{"is_active":{is_active == "1"}}}',
    )
    return RedirectResponse(url="/companies?saved=1", status_code=303)


def _save_upload_stream(file, dest_path, max_bytes: int):
    """청크 단위로 저장하며 크기 제한을 넘으면 즉시 중단하고 삭제한다."""
    written = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                f.close()
                dest_path.unlink(missing_ok=True)
                return False, written
            f.write(chunk)
    return True, written


@app.post("/companies/{company_id}/cover-image")
def companies_upload_cover_image(request: Request, company_id: int, file: UploadFile = File(...)):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)

    import secrets
    from pathlib import Path
    from app.config import UPLOADS_DIR, COMPANY_IMAGE_EXTENSIONS, COMPANY_IMAGE_MAX_BYTES, to_relative_path
    from app.db import repository as repo

    ext = Path(file.filename or "").suffix.lower()
    if ext not in COMPANY_IMAGE_EXTENSIONS:
        return RedirectResponse(url=f"/companies/{company_id}?error=지원하지+않는+이미지+형식입니다.", status_code=303)

    company_dir = UPLOADS_DIR / str(company["user_id"]) / str(company_id) / "cover"
    company_dir.mkdir(parents=True, exist_ok=True)
    dest = company_dir / f"cover_{secrets.token_hex(6)}{ext}"
    ok, _size = _save_upload_stream(file, dest, COMPANY_IMAGE_MAX_BYTES)
    if not ok:
        return RedirectResponse(url=f"/companies/{company_id}?error=이미지+용량이+너무+큽니다(최대+10MB).", status_code=303)

    old_path = company.get("cover_image_relative_path")
    repo.set_company_cover_image(company_id, company["user_id"], to_relative_path(dest))
    if old_path:
        from app.config import to_absolute_path
        try:
            to_absolute_path(old_path).unlink(missing_ok=True)
        except Exception:
            pass
    repo.write_audit_log(user["id"], "company_cover_image_uploaded", target_type="company", target_id=company_id)
    return RedirectResponse(url=f"/companies/{company_id}?saved=1", status_code=303)


def _save_company_media_files(company: dict, files: list) -> tuple[list[int], int, int]:
    """업로드된 파일들을 이 업체의 미디어로 저장하고 (새로 생긴 media_id 목록, 저장 성공 수,
    건너뛴 수)를 돌려준다. /companies/{id}/media와 /content/new(새 콘텐츠 제작 화면에서
    바로 업로드) 양쪽에서 공유한다."""
    import secrets
    from pathlib import Path
    from app.config import (
        UPLOADS_DIR, COMPANY_IMAGE_EXTENSIONS, COMPANY_VIDEO_EXTENSIONS,
        COMPANY_IMAGE_MAX_BYTES, COMPANY_VIDEO_MAX_BYTES, to_relative_path,
    )
    from app.db import repository as repo

    company_id = company["id"]
    media_dir = UPLOADS_DIR / str(company["user_id"]) / str(company_id) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    existing_count = len(repo.list_company_media(company_id))
    new_media_ids: list[int] = []
    saved = 0
    skipped = 0
    for i, file in enumerate(files):
        if not (file and file.filename):
            continue
        ext = Path(file.filename or "").suffix.lower()
        if ext in COMPANY_IMAGE_EXTENSIONS:
            media_type, max_bytes = "image", COMPANY_IMAGE_MAX_BYTES
        elif ext in COMPANY_VIDEO_EXTENSIONS:
            media_type, max_bytes = "video", COMPANY_VIDEO_MAX_BYTES
        else:
            skipped += 1
            continue
        dest = media_dir / f"{media_type}_{secrets.token_hex(6)}{ext}"
        ok, _size = _save_upload_stream(file, dest, max_bytes)
        if not ok:
            skipped += 1
            continue
        media_id = repo.add_company_media(
            company_id, company["user_id"], media_type, to_relative_path(dest),
            original_filename=(file.filename or "")[:255], file_size_bytes=dest.stat().st_size,
            sort_order=existing_count + i,
        )
        new_media_ids.append(media_id)
        saved += 1
    return new_media_ids, saved, skipped


@app.post("/companies/{company_id}/media")
def companies_upload_media(request: Request, company_id: int, files: list[UploadFile] = File(...)):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)

    from app.db import repository as repo
    _new_ids, saved, skipped = _save_company_media_files(company, files)
    repo.write_audit_log(
        user["id"], "company_media_uploaded", target_type="company", target_id=company_id,
        metadata_json=f'{{"saved":{saved},"skipped":{skipped}}}',
    )
    if skipped:
        return RedirectResponse(
            url=f"/companies/{company_id}?saved=1&error=일부+파일은+지원하지+않는+형식이거나+용량+초과로+건너뛰었습니다({skipped}건).",
            status_code=303,
        )
    return RedirectResponse(url=f"/companies/{company_id}?saved=1", status_code=303)


@app.post("/companies/{company_id}/media/{media_id}/delete")
def companies_delete_media(request: Request, company_id: int, media_id: int):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        return RedirectResponse(url="/companies", status_code=303)
    from app.db import repository as repo
    from app.config import to_absolute_path
    relative_path = repo.delete_company_media(media_id, company["user_id"])
    if relative_path:
        try:
            to_absolute_path(relative_path).unlink(missing_ok=True)
        except Exception:
            pass
        repo.write_audit_log(user["id"], "company_media_deleted", target_type="company", target_id=company_id)
    return RedirectResponse(url=f"/companies/{company_id}?saved=1", status_code=303)


@app.get("/companies/{company_id}/cover-image")
def companies_cover_image(request: Request, company_id: int):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company or not company.get("cover_image_relative_path"):
        raise HTTPException(status_code=404, detail="대표 이미지가 없습니다.")
    from app.config import PathEscapeError, to_absolute_path
    try:
        path = to_absolute_path(company["cover_image_relative_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="이미지 파일을 찾을 수 없습니다.")
    return FileResponse(path)


@app.get("/companies/{company_id}/media/{media_id}")
def companies_media_file(request: Request, company_id: int, media_id: int):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    company = _get_owned_company_or_none(company_id, user)
    if not company:
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    from app.db import repository as repo
    from app.config import PathEscapeError, to_absolute_path
    media = repo.get_company_media_owned(media_id, company["user_id"]) if str(user.get("role")) != "admin" else None
    if not media:
        # 관리자는 소유자 무관 열람 가능 - company_id로만 재확인한다.
        candidates = [m for m in repo.list_company_media(company_id) if m["id"] == media_id]
        media = candidates[0] if candidates else None
    if not media:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    try:
        path = to_absolute_path(media["relative_path"])
    except PathEscapeError:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    media_type = "video/mp4" if media["media_type"] == "video" else None
    return FileResponse(path, media_type=media_type)


@app.get("/subscription")
def subscription_page(request: Request, requested: int = 0):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo

    subscription = repo.get_active_subscription(user["id"])
    plan_code = subscription["plan_code"] if subscription else "free"
    monthly_limit = subscription["monthly_project_limit"] if subscription else 20
    archive_limit = subscription["archive_item_limit"] if subscription else 10
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00")
    monthly_count = repo.count_projects_for_user_since(user["id"], month_start)
    archive_count = repo.count_projects_by_status_for_user(user["id"])["completed"]
    plans = repo.list_plans()
    return templates.TemplateResponse("subscription.html", _ctx(
        request, user, active="subscription", plan_code=plan_code, monthly_limit=monthly_limit,
        monthly_count=monthly_count, archive_limit=archive_limit, archive_count=archive_count,
        plans=plans, subscription=subscription, requested=requested,
    ))


@app.post("/subscription/upgrade-request")
def subscription_upgrade_request(request: Request, plan_id: int = Form(...)):
    """실제 결제는 아직 연결하지 않는다(외부 결제 연동은 이번 범위 밖). 대신 요청
    자체는 감사로그에 실제로 남겨 관리자가 확인할 수 있게 한다(가짜 토스트만
    보여주고 끝나는 mock 버튼으로 남겨두지 않기 위함)."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    from app.db import repository as repo
    repo.write_audit_log(
        user["id"], "subscription_upgrade_requested", target_type="subscription_plan", target_id=plan_id,
    )
    return RedirectResponse(url="/subscription?requested=1", status_code=303)


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
        return RedirectResponse(url=f"/admin/members/{member_id}", status_code=303)
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
