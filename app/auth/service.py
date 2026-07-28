# -*- coding: utf-8 -*-
"""
인증 비즈니스 로직. 라우터는 이 모듈의 함수만 호출한다.

현재는 LocalAuthProvider(자체 DB)만 실제로 동작한다.
이메일 발송은 SMTP 자격증명이 없으므로 실제 메일을 보내지 않고,
개발 모드로 인증/재설정 링크를 화면에 직접 표시한다(운영 전환 시 교체 지점 명시).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.auth.security import hash_password, verify_password, new_token, hash_token
from app.auth.rate_limit import check as rl_check, record as rl_record, clear as rl_clear, RateLimitExceeded
from app.db import repository as repo
from app.constants import USER_ROLE_USER

SESSION_TTL_HOURS = 24
EMAIL_VERIFY_TTL_MINUTES = 30
PASSWORD_RESET_TTL_MINUTES = 30
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 5 * 60
PASSWORD_RESET_REQUEST_LIMIT = 3
PASSWORD_RESET_REQUEST_WINDOW_SECONDS = 15 * 60


class AuthError(Exception):
    """사용자에게 그대로 보여줄 수 있는 안전한 인증 오류 메시지."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 회원가입 + 이메일 인증
# ---------------------------------------------------------------------------
def register(email: str, password: str, display_name: str) -> dict:
    email = email.strip().lower()
    if len(password) < 8:
        raise AuthError("비밀번호는 8자 이상이어야 합니다.")
    if repo.get_user_by_email(email):
        # 계정 존재 여부를 노출하지 않기 위해 회원가입 화면에서도 동일한 안내를 쓰지만,
        # 서버 내부적으로는 명확히 구분해 로그로 남긴다.
        raise AuthError("입력한 정보로 가입을 완료할 수 없습니다. 이미 가입된 이메일일 수 있습니다.")

    user_id = repo.create_user(email, hash_password(password), display_name, role=USER_ROLE_USER)
    token = _issue_email_verification_token(user_id)
    repo.write_audit_log(user_id, "user_register", target_type="user", target_id=user_id)
    return {"user_id": user_id, "dev_verification_token": token}


def _issue_email_verification_token(user_id: int) -> str:
    token = new_token()
    expires_at = _iso(_now() + timedelta(minutes=EMAIL_VERIFY_TTL_MINUTES))
    repo.create_email_verification_token(user_id, hash_token(token), expires_at)
    return token


def resend_verification_email(email: str) -> Optional[str]:
    user = repo.get_user_by_email(email)
    if not user or user["email_verified"]:
        return None
    return _issue_email_verification_token(user["id"])


def verify_email(token: str) -> bool:
    user_id = repo.consume_email_verification_token(hash_token(token))
    if not user_id:
        return False
    repo.mark_user_email_verified(user_id)
    repo.write_audit_log(user_id, "email_verified", target_type="user", target_id=user_id)
    return True


# ---------------------------------------------------------------------------
# 로그인 / 로그아웃 / 세션
# ---------------------------------------------------------------------------
@dataclass
class LoginResult:
    session_token: str
    user: dict


def login(email: str, password: str, ip_address: str, user_agent: str) -> LoginResult:
    email_norm = email.strip().lower()
    rate_keys = [f"ip:{ip_address}", f"account:{email_norm}"]
    try:
        rl_check("login_failure", rate_keys, LOGIN_FAILURE_LIMIT, LOGIN_FAILURE_WINDOW_SECONDS)
    except RateLimitExceeded as exc:
        raise AuthError(f"로그인 시도가 너무 많습니다. {exc.retry_after_seconds}초 후 다시 시도해 주세요.") from exc

    user = repo.get_user_by_email(email_norm)
    if not user or not verify_password(password, user["password_hash"]):
        rl_record("login_failure", rate_keys, LOGIN_FAILURE_WINDOW_SECONDS)
        raise AuthError("이메일 또는 비밀번호가 일치하지 않습니다.")
    if user["status"] != "active":
        raise AuthError("비활성화된 계정입니다. 관리자에게 문의하세요.")
    if not user["email_verified"]:
        raise AuthError("이메일 인증이 완료되지 않았습니다. 인증 메일을 먼저 확인해 주세요.")

    rl_clear("login_failure", rate_keys)
    token = new_token()
    expires_at = _iso(_now() + timedelta(hours=SESSION_TTL_HOURS))
    repo.create_session(user["id"], hash_token(token), expires_at, ip_address, user_agent)
    repo.update_user_last_login(user["id"])
    repo.write_audit_log(user["id"], "login", target_type="user", target_id=user["id"], ip_address=ip_address)
    return LoginResult(session_token=token, user=user)


def logout(session_token: str) -> None:
    if not session_token:
        return
    repo.revoke_session(hash_token(session_token))


def get_current_user(session_token: Optional[str]) -> Optional[dict]:
    if not session_token:
        return None
    session = repo.get_active_session_by_token_hash(hash_token(session_token))
    if not session:
        return None
    user = repo.get_user_by_id(session["user_id"])
    if not user or user["status"] != "active":
        return None
    repo.touch_session(session["id"])
    return user


# ---------------------------------------------------------------------------
# 비밀번호 찾기 / 변경
# ---------------------------------------------------------------------------
def request_password_reset(email: str, ip_address: str) -> Optional[str]:
    email_norm = email.strip().lower()
    rate_keys = [f"ip:{ip_address}", f"account:{email_norm}"]
    try:
        rl_check("password_reset", rate_keys, PASSWORD_RESET_REQUEST_LIMIT, PASSWORD_RESET_REQUEST_WINDOW_SECONDS)
    except RateLimitExceeded as exc:
        raise AuthError(f"요청이 너무 많습니다. {exc.retry_after_seconds}초 후 다시 시도해 주세요.") from exc
    rl_record("password_reset", rate_keys, PASSWORD_RESET_REQUEST_WINDOW_SECONDS)

    user = repo.get_user_by_email(email_norm)
    if not user:
        # 계정 존재 여부를 노출하지 않는다: 호출자는 항상 동일한 성공 메시지를 보여준다.
        return None
    token = new_token()
    expires_at = _iso(_now() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES))
    repo.create_password_reset_token(user["id"], hash_token(token), expires_at)
    repo.write_audit_log(user["id"], "password_reset_requested", target_type="user", target_id=user["id"], ip_address=ip_address)
    return token


def confirm_password_reset(token: str, new_password: str) -> bool:
    if len(new_password) < 8:
        raise AuthError("새 비밀번호는 8자 이상이어야 합니다.")
    user_id = repo.consume_password_reset_token(hash_token(token))
    if not user_id:
        return False
    repo.update_user_password(user_id, hash_password(new_password))
    repo.revoke_all_sessions_for_user(user_id)  # 재설정 후 기존 세션 전체 무효화
    repo.write_audit_log(user_id, "password_reset_confirmed", target_type="user", target_id=user_id)
    return True


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    user = repo.get_user_by_id(user_id)
    if not user or not verify_password(current_password, user["password_hash"]):
        raise AuthError("현재 비밀번호가 일치하지 않습니다.")
    if len(new_password) < 8:
        raise AuthError("새 비밀번호는 8자 이상이어야 합니다.")
    if current_password == new_password:
        raise AuthError("새 비밀번호는 현재 비밀번호와 다르게 입력해 주세요.")
    repo.update_user_password(user_id, hash_password(new_password))
    repo.revoke_all_sessions_for_user(user_id)
    repo.write_audit_log(user_id, "password_changed", target_type="user", target_id=user_id)
