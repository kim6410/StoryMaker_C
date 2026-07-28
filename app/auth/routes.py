# -*- coding: utf-8 -*-
"""회원가입/로그인/로그아웃/비밀번호 찾기·변경 실제 처리 라우터.
서버 렌더링 폼 제출을 그대로 처리하고 결과에 따라 리다이렉트한다.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request, Response, Form, Depends
from fastapi.responses import RedirectResponse

from app.auth import service
from app.auth.dependencies import SESSION_COOKIE_NAME, require_user

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE_MAX_AGE = service.SESSION_TTL_HOURS * 3600


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


@router.post("/register")
def do_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
):
    try:
        result = service.register(email, password, display_name)
    except service.AuthError as exc:
        return RedirectResponse(url=f"/register?error={quote(str(exc))}", status_code=303)
    # 개발 모드: 실제 SMTP가 없으므로 인증 링크를 화면에 직접 보여준다.
    verify_url = f"/auth/verify?token={result['dev_verification_token']}"
    return RedirectResponse(
        url=f"/verify-email?email={quote(email)}&dev_link={quote(verify_url)}", status_code=303
    )


@router.get("/verify")
def do_verify_email(token: str = ""):
    ok = service.verify_email(token) if token else False
    if ok:
        return RedirectResponse(url="/login?verified=1", status_code=303)
    return RedirectResponse(url="/login?verify_failed=1", status_code=303)


@router.post("/resend-verification")
def do_resend_verification(email: str = Form(...)):
    token = service.resend_verification_email(email)
    if token:
        verify_url = f"/auth/verify?token={token}"
        return RedirectResponse(
            url=f"/verify-email?email={quote(email)}&dev_link={quote(verify_url)}", status_code=303
        )
    return RedirectResponse(url=f"/verify-email?email={quote(email)}", status_code=303)


@router.post("/login")
def do_login(request: Request, response: Response, email: str = Form(...), password: str = Form(...)):
    try:
        result = service.login(email, password, _client_ip(request), request.headers.get("user-agent", ""))
    except service.AuthError as exc:
        return RedirectResponse(url=f"/login?error={quote(str(exc))}", status_code=303)

    redirect = RedirectResponse(url="/dashboard", status_code=303)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=result.session_token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_COOKIE_MAX_AGE,
        path="/",
    )
    return redirect


@router.post("/logout")
def do_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    service.logout(token or "")
    redirect = RedirectResponse(url="/login?logged_out=1", status_code=303)
    redirect.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return redirect


@router.post("/forgot-password")
def do_forgot_password(request: Request, email: str = Form(...)):
    try:
        token = service.request_password_reset(email, _client_ip(request))
    except service.AuthError as exc:
        return RedirectResponse(url=f"/forgot-password?error={quote(str(exc))}", status_code=303)
    # 계정 존재 여부를 노출하지 않도록 항상 같은 성공 화면으로 이동한다.
    dev_link = f"/auth/reset-password?token={token}" if token else ""
    return RedirectResponse(url=f"/forgot-password?sent=1&dev_link={quote(dev_link)}", status_code=303)


@router.get("/reset-password")
def show_reset_password(request: Request, token: str = "", error: str = ""):
    return _templates().TemplateResponse(
        "reset_password.html",
        {"request": request, "app_name": "StoryMaker Claude Lab", "token": token, "error": error},
    )


def _templates():
    from fastapi.templating import Jinja2Templates
    from pathlib import Path
    return Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.post("/reset-password")
def do_reset_password(token: str = Form(...), new_password: str = Form(...)):
    try:
        ok = service.confirm_password_reset(token, new_password)
    except service.AuthError as exc:
        return RedirectResponse(url=f"/auth/reset-password?token={token}&error={quote(str(exc))}", status_code=303)
    if not ok:
        return RedirectResponse(url="/forgot-password?expired=1", status_code=303)
    return RedirectResponse(url="/login?reset=1", status_code=303)


@router.post("/change-password")
def do_change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: dict = Depends(require_user),
):
    try:
        service.change_password(user["id"], current_password, new_password)
    except service.AuthError as exc:
        return RedirectResponse(url=f"/mypage?tab=account&error={quote(str(exc))}", status_code=303)
    redirect = RedirectResponse(url="/login?password_changed=1", status_code=303)
    redirect.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return redirect
