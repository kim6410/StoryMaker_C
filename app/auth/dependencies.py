# -*- coding: utf-8 -*-
"""FastAPI 인증 의존성. 세션 쿠키 기반."""
from __future__ import annotations

from fastapi import Request, HTTPException, status

from app.auth.service import get_current_user

SESSION_COOKIE_NAME = "sc_session"


def get_optional_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return get_current_user(token)


def require_user(request: Request) -> dict:
    user = get_optional_user(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if str(user.get("role")) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
    return user
