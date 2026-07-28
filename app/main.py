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
    {"key": "archive", "label": "보관함", "href": "/archive", "icon": "folder"},
    {"key": "mypage", "label": "마이페이지", "href": "/mypage", "icon": "user"},
    {"key": "subscription", "label": "구독 및 사용량", "href": "/subscription", "icon": "chart"},
]
ADMIN_MENU = [
    {"key": "admin_members", "label": "회원관리", "href": "/admin/members", "icon": "shield"},
    {"key": "admin_requests", "label": "요청사항 관리", "href": "/admin/requests", "icon": "inbox"},
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

SAMPLE_REQUESTS = [
    {"id": 101, "title": "썸네일 템플릿 색상 추가 요청", "importance": "보통", "status": "검토", "created_at": "2026-07-26"},
    {"id": 102, "title": "네이버 블로그 서식 복사가 안 돼요", "importance": "높음", "status": "진행", "created_at": "2026-07-27"},
    {"id": 103, "title": "보관함 검색 속도 개선 요청", "importance": "낮음", "status": "접수", "created_at": "2026-07-28"},
]


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


# ---------------------------------------------------------------------------
# 인증 전 화면
# ---------------------------------------------------------------------------
@app.get("/")
def root(request: Request):
    if get_optional_user(request):
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


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
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", _ctx(request, user, active="dashboard", recent=SAMPLE_ARCHIVE_ITEMS[:3]))


@app.get("/content/new")
def content_new_page(request: Request, error: str = ""):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
    return templates.TemplateResponse("content_job_status.html", _ctx(
        request, user, active="content_new", project=project, snapshot=snapshot,
        gemini_configured=gemini_configured, result=result, last_generation=last_generation,
        gen_error_message=gen_error_message,
    ))


@app.post("/content/job/{job_uid}/generate")
def content_job_generate(request: Request, job_uid: str):
    """6B단계: 실제 Gemini API를 호출해 SNS 8채널 + 숏폼 영상원고를 생성한다."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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

    return templates.TemplateResponse("content_job_channels.html", _ctx(
        request, user, active="content_new", project=project, channels=channels,
        video_script=video_script, scene_sentences=scene_sentences,
        channel_error_message=channel_error_message,
    ))


@app.post("/content/job/{job_uid}/channels/{channel_code}/regenerate")
def content_job_channel_regenerate(request: Request, job_uid: str, channel_code: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
    project = _get_owned_project_or_none(job_uid, user)
    if not project:
        return RedirectResponse(url="/content/new")

    from app.db import repository as repo
    sentences = repo.list_tts_sentences_for_project(project["id"])
    master = repo.get_tts_master_for_project(project["id"])
    srt = repo.get_srt_for_project(project["id"])
    video_script = repo.get_video_script_for_project(project["id"])
    return templates.TemplateResponse("content_job_tts.html", _ctx(
        request, user, active="content_new", project=project, sentences=sentences,
        master=master, srt=srt, has_script=bool(video_script),
    ))


@app.get("/content/job/{job_uid}/tts/audio/{filename}")
def content_job_tts_audio(request: Request, job_uid: str, filename: str):
    """문장별/전체 합성 WAV 스트리밍. 소유자만 접근 가능하고 파일명은 이 작업의 tts 폴더로만 해석한다."""
    from fastapi import HTTPException
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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

    return templates.TemplateResponse("content_job_mp4.html", _ctx(
        request, user, active="content_new", project=project, mp4=mp4, music_mix=music_mix,
        scenes=scenes, has_tts=has_tts, mp4_error_message=mp4_error_message,
    ))


@app.get("/content/job/{job_uid}/mp4/video")
def content_job_mp4_video(request: Request, job_uid: str):
    from fastapi import HTTPException
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("content_channels.html", _ctx(request, user, active="content_new", channels=SAMPLE_CHANNELS))


@app.get("/content/media")
def content_media_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("content_media.html", _ctx(request, user, active="content_new"))


@app.get("/content/thumbnail")
def content_thumbnail_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("content_thumbnail.html", _ctx(request, user, active="content_new", candidates=list(range(1, 9))))


@app.get("/archive")
def archive_list_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("archive_list.html", _ctx(request, user, active="archive", items=SAMPLE_ARCHIVE_ITEMS))


@app.get("/archive/{item_id}")
def archive_detail_page(request: Request, item_id: str):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    detail = SAMPLE_ARCHIVE_DETAIL.get(item_id, SAMPLE_ARCHIVE_DETAIL["job-sample-0001"])
    return templates.TemplateResponse("archive_detail.html", _ctx(request, user, active="archive", item_id=item_id, detail=detail))


@app.get("/mypage")
def mypage_page(request: Request, error: str = "", saved: int = 0, tab: str = "profile"):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
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
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("subscription.html", _ctx(request, user, active="subscription"))


@app.get("/admin/members")
def admin_members_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    if str(user.get("role")) != "admin":
        return RedirectResponse(url="/dashboard")
    from app.db import repository as repo
    members = repo.list_users(limit=200)
    return templates.TemplateResponse("admin_members.html", _ctx(request, user, active="admin_members", members=members))


@app.get("/admin/requests")
def admin_requests_page(request: Request):
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
    if str(user.get("role")) != "admin":
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("admin_requests.html", _ctx(request, user, active="admin_requests", requests=SAMPLE_REQUESTS))


@app.get("/content/music-preview/{filename}")
def music_preview(request: Request, filename: str):
    """배경음악 미리듣기. runtime/music/mp3 원본을 그대로 스트리밍한다(복사 없음)."""
    user = _require_login_or_redirect(request)
    if not user:
        return RedirectResponse(url="/login")
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
