# -*- coding: utf-8 -*-
"""
인증 원장 Provider 추상화.

StoryMaker_C는 기본적으로 자체 로컬 계정(LocalAuthProvider)을 인증 원장으로 쓴다.
WordPressAuthProvider는 이 프로젝트가 회원 시스템으로 재사용하는 기존 WordPress
사이트(mystorymaker.net)에 연결한다. config/.env의 WORDPRESS_BASE_URL /
WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD 세 값이 모두 설정된 경우에만 활성화된다.

주의: 이 Provider는 실제 운영 WordPress 회원 원장에 연결되므로, 실제 신규 계정을
생성하거나 실제 회원 비밀번호로 로그인 시도하는 것은 운영 서비스에 영향을 줄 수 있다.
연결 확인(test_connection)은 읽기 전용 GET만 사용하고, authenticate()는 사용자가
명시적으로 실행을 요청한 경우에만 호출한다.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import PROJECT_ROOT  # noqa: F401  (import 시 config/.env 로드 부작용 보장)


@dataclass
class ExternalAuthResult:
    external_user_id: str
    username: str
    email: str
    roles: list[str]


class AuthProvider(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """실제 외부 시스템에 연결할 준비가 됐는지."""

    @abstractmethod
    def authenticate(self, identifier: str, password: str) -> Optional[ExternalAuthResult]:
        """성공하면 외부 사용자 정보를, 실패하면 None을 반환한다."""


class LocalAuthProvider(AuthProvider):
    """StoryMaker_C 자체 DB를 원장으로 쓰는 기본 Provider. 항상 사용 가능."""

    name = "local"

    def is_configured(self) -> bool:
        return True

    def authenticate(self, identifier: str, password: str) -> Optional[ExternalAuthResult]:
        # 실제 인증 로직은 app.auth.service에서 로컬 users 테이블로 직접 처리한다.
        raise NotImplementedError("LocalAuthProvider.authenticate는 app.auth.service를 사용하세요.")


class WordPressAuthProvider(AuthProvider):
    """mystorymaker.net WordPress를 회원 원장으로 사용하는 Provider."""

    name = "wordpress"

    def __init__(self) -> None:
        self.base_url = os.getenv("WORDPRESS_BASE_URL", "").strip().rstrip("/")
        self.username = os.getenv("WORDPRESS_USERNAME", "").strip()
        self.app_password = os.getenv("WORDPRESS_APP_PASSWORD", "").strip()
        self.api_namespace = os.getenv("WORDPRESS_API_NAMESPACE", "wp-json/wp/v2").strip().strip("/")
        self.timeout = float(os.getenv("WORDPRESS_TIMEOUT_SECONDS", "10") or 10)

    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.app_password)

    def test_connection(self) -> dict:
        """읽기 전용 GET으로 Application Password가 유효한지만 확인한다. 상태 변경 없음."""
        if not self.is_configured():
            return {"ok": False, "reason": "not_configured"}
        url = f"{self.base_url}/{self.api_namespace}/users/me?context=edit"
        try:
            resp = httpx.get(url, auth=(self.username, self.app_password), timeout=self.timeout)
            return {"ok": resp.status_code == 200, "status_code": resp.status_code}
        except httpx.RequestError as exc:
            return {"ok": False, "reason": "request_error", "detail": str(exc)[:200]}

    def authenticate(self, identifier: str, password: str) -> Optional[ExternalAuthResult]:
        if not self.is_configured():
            raise RuntimeError(
                "WordPress Provider가 설정되지 않았습니다. config/.env의 WORDPRESS_BASE_URL / "
                "WORDPRESS_USERNAME / WORDPRESS_APP_PASSWORD를 확인하세요."
            )
        login_url = f"{self.base_url}/wp-json/storymaker/v1/login"
        try:
            resp = httpx.post(login_url, json={"username": identifier, "password": password}, timeout=self.timeout)
        except httpx.RequestError as exc:
            raise RuntimeError(f"WordPress 인증 서버와 통신할 수 없습니다: {exc}") from exc
        if resp.status_code != 200:
            return None
        data = resp.json()
        wp_user_id = data.get("user_id")
        if not wp_user_id:
            return None
        return ExternalAuthResult(
            external_user_id=str(wp_user_id),
            username=str(data.get("username") or identifier),
            email=str(data.get("email") or ""),
            roles=list(data.get("roles") or []),
        )


def get_local_provider() -> LocalAuthProvider:
    return LocalAuthProvider()


def get_wordpress_provider() -> WordPressAuthProvider:
    return WordPressAuthProvider()
