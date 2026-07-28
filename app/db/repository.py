# -*- coding: utf-8 -*-
"""
테이블별 CRUD 헬퍼 함수.
라우터나 스크립트는 SQL을 직접 쓰지 말고 이 모듈의 함수를 사용한다.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.connection import get_connection, get_readonly_connection
from app.constants import PROJECT_STATUS_DRAFT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
def create_user(email: str, password_hash: str, display_name: str = "", role: str = "user") -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO users (email, password_hash, display_name, role, email_verified, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 'active', ?, ?)
            """,
            (email.strip().lower(), password_hash, display_name, role, now, now),
        )
        return int(cur.lastrowid)


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def list_users(limit: int = 50, offset: int = 0) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]


def update_user_status(user_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET status=?, updated_at=? WHERE id=?", (status, _now(), user_id)
        )


def delete_user(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


# ---------------------------------------------------------------------------
# subscription_plans
# ---------------------------------------------------------------------------
def create_plan(code: str, name: str, monthly_project_limit: Optional[int],
                 archive_item_limit: Optional[int], price_krw: int = 0, sort_order: int = 0) -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO subscription_plans
                (code, name, monthly_project_limit, archive_item_limit, price_krw, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (code, name, monthly_project_limit, archive_item_limit, price_krw, sort_order, now, now),
        )
        return int(cur.lastrowid)


def list_plans(active_only: bool = True) -> list[dict]:
    with get_readonly_connection() as conn:
        sql = "SELECT * FROM subscription_plans"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY sort_order, id"
        return [dict(r) for r in conn.execute(sql).fetchall()]


# ---------------------------------------------------------------------------
# user_subscriptions
# ---------------------------------------------------------------------------
def assign_subscription(user_id: int, plan_id: int, period_started_at: str, period_ends_at: str) -> int:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE user_subscriptions SET is_active=0, updated_at=? WHERE user_id=? AND is_active=1",
            (now, user_id),
        )
        cur = conn.execute(
            """
            INSERT INTO user_subscriptions (user_id, plan_id, period_started_at, period_ends_at, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, plan_id, period_started_at, period_ends_at, now, now),
        )
        return int(cur.lastrowid)


def get_active_subscription(user_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT us.*, sp.code AS plan_code, sp.name AS plan_name,
                   sp.monthly_project_limit, sp.archive_item_limit
            FROM user_subscriptions us
            JOIN subscription_plans sp ON sp.id = us.plan_id
            WHERE us.user_id=? AND us.is_active=1
            ORDER BY us.created_at DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------
def create_project(user_id: int, title: str) -> dict:
    now = _now()
    job_uid = f"proj_{now[:10].replace('-', '')}_{secrets.token_hex(4)}"
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (job_uid, user_id, title, status, error_code, progress, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', 0, ?, ?)
            """,
            (job_uid, user_id, title, PROJECT_STATUS_DRAFT, now, now),
        )
        return {"id": int(cur.lastrowid), "job_uid": job_uid}


def get_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None


def list_projects_for_user(user_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def update_project_status(project_id: int, status: str, error_code: str = "", progress: Optional[int] = None) -> None:
    now = _now()
    with get_connection() as conn:
        if progress is None:
            conn.execute(
                "UPDATE projects SET status=?, error_code=?, updated_at=? WHERE id=?",
                (status, error_code, now, project_id),
            )
        else:
            conn.execute(
                "UPDATE projects SET status=?, error_code=?, progress=?, updated_at=? WHERE id=?",
                (status, error_code, progress, now, project_id),
            )


def delete_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


# ---------------------------------------------------------------------------
# archive_items  (실제 바이너리는 저장하지 않고, 상대경로 메타데이터만 저장)
# ---------------------------------------------------------------------------
def add_archive_item(project_id: int, user_id: int, media_type: str, relative_path: str,
                      file_size_bytes: int = 0, checksum_sha256: Optional[str] = None,
                      is_primary: bool = False) -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO archive_items
                (project_id, user_id, media_type, relative_path, file_size_bytes, checksum_sha256, is_primary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, user_id, media_type, relative_path, file_size_bytes,
             checksum_sha256, 1 if is_primary else 0, now, now),
        )
        return int(cur.lastrowid)


def list_archive_items_for_project(project_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM archive_items WHERE project_id=? ORDER BY created_at", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_archive_items_for_user(user_id: int, exclude_deleted: bool = True, limit: int = 100) -> list[dict]:
    with get_readonly_connection() as conn:
        sql = "SELECT * FROM archive_items WHERE user_id=?"
        if exclude_deleted:
            sql += " AND media_deleted_at IS NULL"
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = conn.execute(sql, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


def mark_archive_item_deleted(item_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE archive_items SET media_deleted_at=?, updated_at=? WHERE id=?",
            (_now(), _now(), item_id),
        )


# ---------------------------------------------------------------------------
# audit_logs
# ---------------------------------------------------------------------------
def write_audit_log(user_id: Optional[int], action: str, target_type: str = "",
                     target_id: Optional[int] = None, metadata_json: Optional[str] = None,
                     ip_address: str = "") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_logs (user_id, action, target_type, target_id, metadata_json, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, target_type, target_id, metadata_json, ip_address, _now()),
        )
        return int(cur.lastrowid)


def list_audit_logs(limit: int = 100) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_audit_logs() -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()
        return int(row[0])
