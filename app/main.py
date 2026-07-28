# -*- coding: utf-8 -*-
"""
StoryMaker Claude Lab - 1단계: 클릭 가능한 웹앱 껍데기
- 실제 DB, AI API, 음성, MP4 렌더링은 아직 연결하지 않는다.
- 모든 데이터는 샘플 데이터이며 새로고침해도 항상 같은 값을 보여준다.
- 기존 StoryMaker V1/Beta 소스코드는 이 프로젝트에서 참고하지 않았다.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent

app = FastAPI(title="StoryMaker Claude Lab", version="0.1.0-shell")
app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "templates")

# ---------------------------------------------------------------------------
# 사이드 메뉴 구성 (일반 사용자 / 관리자 분리)
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
    {
        "id": "job-sample-0001",
        "title": "겨울철 보일러 점검 콘텐츠",
        "company": "오박사만능설비",
        "created_at": "2026-07-27 14:20",
        "status": "완료",
        "media": ["이미지 4장", "음성", "자막", "MP4", "썸네일"],
        "size": "38.2MB",
    },
    {
        "id": "job-sample-0002",
        "title": "여름철 에어컨 청소 안내",
        "company": "오박사만능설비",
        "created_at": "2026-07-25 09:05",
        "status": "완료",
        "media": ["이미지 3장", "음성", "자막", "MP4", "썸네일"],
        "size": "29.7MB",
    },
    {
        "id": "job-sample-0003",
        "title": "강북구 배관 누수 출장 후기",
        "company": "오박사만능설비",
        "created_at": "2026-07-20 18:41",
        "status": "완료",
        "media": ["이미지 5장", "음성", "자막", "MP4", "썸네일"],
        "size": "41.0MB",
    },
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

SAMPLE_MEMBERS = [
    {"id": 1, "name": "김사장", "email": "kim***@example.com", "company": "오박사만능설비", "role": "user", "plan": "무료", "period": "-", "usage": "3 / 20", "last_login": "2026-07-28 09:12", "status": "활성"},
    {"id": 2, "name": "박대표", "email": "park***@example.com", "company": "청솔카페", "role": "user", "plan": "Starter", "period": "2026-07-01 ~ 2026-07-31", "usage": "14 / 20", "last_login": "2026-07-28 08:03", "status": "활성"},
    {"id": 3, "name": "이관리자", "email": "admin***@example.com", "company": "-", "role": "admin", "plan": "관리자", "period": "-", "usage": "무제한", "last_login": "2026-07-28 10:40", "status": "활성"},
]

SAMPLE_REQUESTS = [
    {"id": 101, "title": "썸네일 템플릿 색상 추가 요청", "importance": "보통", "status": "검토", "created_at": "2026-07-26"},
    {"id": 102, "title": "네이버 블로그 서식 복사가 안 돼요", "importance": "높음", "status": "진행", "created_at": "2026-07-27"},
    {"id": 103, "title": "보관함 검색 속도 개선 요청", "importance": "낮음", "status": "접수", "created_at": "2026-07-28"},
]


def _sample_user(role: str) -> dict:
    if role == "admin":
        return {"name": "이관리자", "email": "admin@example.com", "role": "admin", "company": "-"}
    return {"name": "김사장", "email": "kim@example.com", "role": "user", "company": "오박사만능설비"}


def _ctx(request: Request, *, active: str = "", role: str = "user", **extra) -> dict:
    """모든 인증 후 화면에서 공통으로 쓰는 템플릿 컨텍스트."""
    user = _sample_user(role)
    admin_menu = ADMIN_MENU if user["role"] == "admin" else []
    return {
        "request": request,
        "app_name": "StoryMaker Claude Lab",
        "user": user,
        "user_menu": USER_MENU,
        "admin_menu": admin_menu,  # 관리자가 아니면 서버에서부터 빈 리스트 -> DOM 자체가 생성되지 않음
        "active": active,
        "role_switch": role,
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **extra,
    }


# ---------------------------------------------------------------------------
# 인증 전 화면 (레이아웃 별도, 사이드 메뉴 없음)
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse(url="/login")


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "app_name": "StoryMaker Claude Lab"})


@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "app_name": "StoryMaker Claude Lab"})


@app.get("/verify-email")
def verify_email_page(request: Request):
    return templates.TemplateResponse("verify_email.html", {"request": request, "app_name": "StoryMaker Claude Lab", "sample_email": "kim***@example.com"})


@app.get("/forgot-password")
def forgot_password_page(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request, "app_name": "StoryMaker Claude Lab"})


# ---------------------------------------------------------------------------
# 인증 후 화면 (공통 레이아웃 + 사이드 메뉴)
# role 쿼리 파라미터는 이번 껍데기 단계에서만 데모용으로 존재한다.
# 실제 권한 분기는 3단계에서 서버 세션 기반으로 다시 구현한다.
# ---------------------------------------------------------------------------
@app.get("/dashboard")
def dashboard_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("dashboard.html", _ctx(request, active="dashboard", role=role, recent=SAMPLE_ARCHIVE_ITEMS[:3]))


@app.get("/content/new")
def content_new_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("content_new.html", _ctx(request, active="content_new", role=role))


@app.get("/content/channels")
def content_channels_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("content_channels.html", _ctx(request, active="content_new", role=role, channels=SAMPLE_CHANNELS))


@app.get("/content/media")
def content_media_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("content_media.html", _ctx(request, active="content_new", role=role))


@app.get("/content/thumbnail")
def content_thumbnail_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("content_thumbnail.html", _ctx(request, active="content_new", role=role, candidates=list(range(1, 9))))


@app.get("/archive")
def archive_list_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("archive_list.html", _ctx(request, active="archive", role=role, items=SAMPLE_ARCHIVE_ITEMS))


@app.get("/archive/{item_id}")
def archive_detail_page(request: Request, item_id: str, role: str = "user"):
    detail = SAMPLE_ARCHIVE_DETAIL.get(item_id, SAMPLE_ARCHIVE_DETAIL["job-sample-0001"])
    return templates.TemplateResponse("archive_detail.html", _ctx(request, active="archive", role=role, item_id=item_id, detail=detail))


@app.get("/mypage")
def mypage_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("mypage.html", _ctx(request, active="mypage", role=role))


@app.get("/subscription")
def subscription_page(request: Request, role: str = "user"):
    return templates.TemplateResponse("subscription.html", _ctx(request, active="subscription", role=role))


@app.get("/admin/members")
def admin_members_page(request: Request, role: str = "admin"):
    if role != "admin":
        return RedirectResponse(url="/dashboard?role=user")
    return templates.TemplateResponse("admin_members.html", _ctx(request, active="admin_members", role=role, members=SAMPLE_MEMBERS))


@app.get("/admin/requests")
def admin_requests_page(request: Request, role: str = "admin"):
    if role != "admin":
        return RedirectResponse(url="/dashboard?role=user")
    return templates.TemplateResponse("admin_requests.html", _ctx(request, active="admin_requests", role=role, requests=SAMPLE_REQUESTS))


@app.get("/healthz")
def healthz():
    """단계 15에서 정식 상태 API로 확장 예정. 지금은 최소 응답만 제공한다."""
    return {"ok": True, "stage": "1-shell", "time": datetime.now(timezone.utc).isoformat()}
