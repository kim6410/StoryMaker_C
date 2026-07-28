# -*- coding: utf-8 -*-
"""비밀번호 해시(Argon2id)와 토큰 생성/해시 유틸리티."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError, InvalidHashError

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(_HASHER.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False


def new_token() -> str:
    """세션·이메일 인증·비밀번호 재설정에 쓰는 URL-safe 랜덤 토큰(원문)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """DB에는 토큰 원문이 아니라 이 해시만 저장한다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
