# -*- coding: utf-8 -*-
"""
테이블별 CRUD 헬퍼 함수.
라우터나 스크립트는 SQL을 직접 쓰지 말고 이 모듈의 함수를 사용한다.
"""
from __future__ import annotations

import secrets
import sqlite3
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


def search_users(q: str = "", status: str = "", plan: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    """관리자 회원관리 검색. plan='paid'는 활성 구독이 있는 회원, 'free'는 없는 회원."""
    where = ["1=1"]
    params: list[Any] = []
    if q:
        where.append("(u.email LIKE ? OR u.display_name LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    if status in ("active", "inactive"):
        where.append("u.status=?")
        params.append(status)
    plan_join = ""
    if plan == "paid":
        plan_join = "JOIN user_subscriptions us ON us.user_id=u.id AND us.is_active=1"
    elif plan == "free":
        plan_join = "LEFT JOIN user_subscriptions us ON us.user_id=u.id AND us.is_active=1"
        where.append("us.id IS NULL")
    sql = f"""
        SELECT u.* FROM users u {plan_join}
        WHERE {' AND '.join(where)}
        ORDER BY u.created_at DESC LIMIT ? OFFSET ?
    """
    params += [limit, offset]
    with get_readonly_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def count_users_total() -> int:
    with get_readonly_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def count_users_active() -> int:
    with get_readonly_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0])


def count_users_paid() -> int:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM user_subscriptions WHERE is_active=1"
        ).fetchone()
        return int(row[0])


def count_users_created_since(since_iso: str) -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (since_iso,)).fetchone()
        return int(row[0])


def update_user_admin_notes(user_id: int, notes: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE users SET admin_notes=?, updated_at=? WHERE id=?", (notes, _now(), user_id))


def update_user_usage_override(user_id: int, override: Optional[int]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET usage_limit_override=?, updated_at=? WHERE id=?", (override, _now(), user_id)
        )


def get_user_admin_detail(user_id: int) -> Optional[dict]:
    """관리자 회원 상세: 회원 기본정보 + 업체목록 + 프로젝트/보관함 집계 + 구독정보."""
    user = get_user_by_id(user_id)
    if not user:
        return None
    with get_readonly_connection() as conn:
        companies = [dict(r) for r in conn.execute(
            "SELECT * FROM companies WHERE user_id=? ORDER BY is_default DESC, created_at DESC", (user_id,)
        ).fetchall()]
        project_counts = conn.execute(
            "SELECT status, COUNT(*) n FROM projects WHERE user_id=? GROUP BY status", (user_id,)
        ).fetchall()
    total_projects = sum(r["n"] for r in project_counts)
    completed_projects = sum(r["n"] for r in project_counts if r["status"] == "completed")
    subscription = get_active_subscription(user_id)
    return {
        "user": user,
        "companies": companies,
        "total_projects": total_projects,
        "completed_projects": completed_projects,
        "subscription": subscription,
    }


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


def create_content_project(user_id: int, title: str, company_id: Optional[int],
                            input_snapshot_json: str, music_relative_path: str = "",
                            voice_preference: str = "") -> dict:
    """5단계: 제작 요청 당시 업체 정보 스냅샷을 포함해 작업을 생성한다."""
    now = _now()
    job_uid = f"proj_{now[:10].replace('-', '')}_{secrets.token_hex(4)}"
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects
                (job_uid, user_id, title, status, error_code, progress, company_id,
                 input_snapshot_json, music_relative_path, voice_preference, created_at, updated_at)
            VALUES (?, ?, ?, ?, '', 0, ?, ?, ?, ?, ?, ?)
            """,
            (job_uid, user_id, title, PROJECT_STATUS_DRAFT, company_id,
             input_snapshot_json, music_relative_path, voice_preference, now, now),
        )
        return {"id": int(cur.lastrowid), "job_uid": job_uid}


def get_project_by_uid(job_uid: str) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE job_uid=?", (job_uid,)).fetchone()
        return dict(row) if row else None


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


def count_projects_for_user_since(user_id: int, since_iso: str) -> int:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE user_id=? AND created_at >= ?", (user_id, since_iso)
        ).fetchone()
        return int(row[0])


def count_projects_by_status_for_user(user_id: int) -> dict:
    """대시보드/보관함 카운트용: 진행중/실패/완료로 묶어서 센다."""
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM projects WHERE user_id=? GROUP BY status", (user_id,)
        ).fetchall()
    counts = {"in_progress": 0, "failed": 0, "completed": 0, "total": 0}
    for r in rows:
        counts["total"] += r["n"]
        if r["status"] == "completed":
            counts["completed"] += r["n"]
        elif r["status"] == "failed":
            counts["failed"] += r["n"]
        else:
            counts["in_progress"] += r["n"]
    return counts


def count_projects_created_since(since_iso: str) -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM projects WHERE created_at >= ?", (since_iso,)).fetchone()
        return int(row[0])


def count_projects_by_status_global() -> dict:
    with get_readonly_connection() as conn:
        rows = conn.execute("SELECT status, COUNT(*) n FROM projects GROUP BY status").fetchall()
    counts = {"in_progress": 0, "failed": 0, "completed": 0, "total": 0}
    for r in rows:
        counts["total"] += r["n"]
        if r["status"] == "completed":
            counts["completed"] += r["n"]
        elif r["status"] == "failed":
            counts["failed"] += r["n"]
        else:
            counts["in_progress"] += r["n"]
    return counts


def list_all_projects_admin(q: str = "", status: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
    """관리자 작업관리 목록: 사용자 이메일·업체명을 함께 반환한다."""
    where = ["1=1"]
    params: list[Any] = []
    if status and status != "all":
        where.append("p.status=?")
        params.append(status)
    if q:
        where.append("(u.email LIKE ? OR p.title LIKE ? OR p.job_uid LIKE ? OR c.company_name LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    sql = f"""
        SELECT p.*, u.email AS user_email, c.company_name AS company_name
        FROM projects p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN companies c ON c.id = p.company_id
        WHERE {' AND '.join(where)}
        ORDER BY p.updated_at DESC LIMIT ? OFFSET ?
    """
    params += [limit, offset]
    with get_readonly_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def list_recent_failed_projects(limit: int = 10) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*, u.email AS user_email
            FROM projects p JOIN users u ON u.id = p.user_id
            WHERE p.status='failed'
            ORDER BY p.updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


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


def create_company(user_id: int, fields: dict) -> int:
    now = _now()
    with get_connection() as conn:
        existing_default = conn.execute(
            "SELECT id FROM companies WHERE user_id=? AND is_default=1", (user_id,)
        ).fetchone()
        is_default = 0 if existing_default else 1
        cur = conn.execute(
            """
            INSERT INTO companies
                (user_id, company_name, owner_name, phone_number, industry, region, address,
                 main_services, target_customers, core_strength, tone_preference, forbidden_words,
                 website_url, free_request, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                fields.get("company_name", ""), fields.get("owner_name", ""),
                fields.get("phone_number", ""), fields.get("industry", ""),
                fields.get("region", ""), fields.get("address", ""),
                fields.get("main_services", ""), fields.get("target_customers", ""),
                fields.get("core_strength", ""), fields.get("tone_preference", ""),
                fields.get("forbidden_words", ""), fields.get("website_url", ""),
                fields.get("free_request", ""), is_default, now, now,
            ),
        )
        return int(cur.lastrowid)


def update_company(company_id: int, user_id: int, fields: dict) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE companies SET
                company_name=?, owner_name=?, phone_number=?, industry=?, region=?, address=?,
                main_services=?, target_customers=?, core_strength=?, tone_preference=?,
                forbidden_words=?, website_url=?, free_request=?, updated_at=?
            WHERE id=? AND user_id=?
            """,
            (
                fields.get("company_name", ""), fields.get("owner_name", ""),
                fields.get("phone_number", ""), fields.get("industry", ""),
                fields.get("region", ""), fields.get("address", ""),
                fields.get("main_services", ""), fields.get("target_customers", ""),
                fields.get("core_strength", ""), fields.get("tone_preference", ""),
                fields.get("forbidden_words", ""), fields.get("website_url", ""),
                fields.get("free_request", ""), _now(), company_id, user_id,
            ),
        )
        return cur.rowcount > 0


def get_company(company_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        return dict(row) if row else None


def get_default_company_for_user(user_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE user_id=? AND is_default=1 LIMIT 1", (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            "SELECT * FROM companies WHERE user_id=? ORDER BY created_at LIMIT 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def list_companies_for_user(user_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM companies WHERE user_id=? ORDER BY is_default DESC, created_at", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_music_by_relative_path(relative_path: str) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT * FROM music_catalog WHERE relative_path=?", (relative_path,)
        ).fetchone()
        return dict(row) if row else None


def get_music_id_by_sha256(sha256: str) -> Optional[int]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT id FROM music_catalog WHERE sha256=? ORDER BY id LIMIT 1", (sha256,)
        ).fetchone()
        return int(row["id"]) if row else None


def upsert_music_catalog_entry(fields: dict) -> int:
    """relative_path 기준으로 있으면 갱신, 없으면 새로 만든다."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM music_catalog WHERE relative_path=?", (fields["relative_path"],)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE music_catalog SET
                    filename=?, size_bytes=?, sha256=?, duration_seconds=?, codec=?,
                    bitrate=?, sample_rate=?, duplicate_of_id=?, scanned_at=?
                WHERE id=?
                """,
                (
                    fields["filename"], fields["size_bytes"], fields["sha256"],
                    fields["duration_seconds"], fields["codec"], fields["bitrate"],
                    fields["sample_rate"], fields.get("duplicate_of_id"), fields["scanned_at"],
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO music_catalog
                (filename, relative_path, size_bytes, sha256, duration_seconds, codec,
                 bitrate, sample_rate, duplicate_of_id, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["filename"], fields["relative_path"], fields["size_bytes"],
                fields["sha256"], fields["duration_seconds"], fields["codec"],
                fields["bitrate"], fields["sample_rate"], fields.get("duplicate_of_id"),
                fields["scanned_at"],
            ),
        )
        return int(cur.lastrowid)


def list_music_catalog(exclude_duplicates: bool = True) -> list[dict]:
    with get_readonly_connection() as conn:
        sql = "SELECT * FROM music_catalog"
        if exclude_duplicates:
            sql += " WHERE duplicate_of_id IS NULL"
        sql += " ORDER BY filename"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def count_music_catalog() -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM music_catalog").fetchone()
        return int(row[0])


def count_audit_logs() -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()
        return int(row[0])


def update_user_password(user_id: int, password_hash: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (password_hash, _now(), user_id),
        )


def mark_user_email_verified(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET email_verified=1, updated_at=? WHERE id=?", (_now(), user_id)
        )


def update_user_last_login(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (_now(), _now(), user_id)
        )


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
def create_session(user_id: int, token_hash: str, expires_at: str,
                    ip_address: str = "", user_agent: str = "") -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO sessions (session_token_hash, user_id, created_at, expires_at, last_seen_at, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (token_hash, user_id, now, expires_at, now, ip_address, user_agent),
        )
        return int(cur.lastrowid)


def get_active_session_by_token_hash(token_hash: str) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM sessions
            WHERE session_token_hash=? AND revoked_at IS NULL AND expires_at > ?
            """,
            (token_hash, _now()),
        ).fetchone()
        return dict(row) if row else None


def touch_session(session_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (_now(), session_id))


def revoke_session(token_hash: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at=? WHERE session_token_hash=? AND revoked_at IS NULL",
            (_now(), token_hash),
        )


def revoke_all_sessions_for_user(user_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (_now(), user_id),
        )


# ---------------------------------------------------------------------------
# email_verification_tokens / password_reset_tokens
# ---------------------------------------------------------------------------
def create_email_verification_token(user_id: int, token_hash: str, expires_at: str) -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO email_verification_tokens (user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token_hash, expires_at, now),
        )
        return int(cur.lastrowid)


def consume_email_verification_token(token_hash: str) -> Optional[int]:
    """유효하면 소비 처리하고 user_id를 반환, 아니면 None."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, user_id FROM email_verification_tokens
            WHERE token_hash=? AND consumed_at IS NULL AND expires_at > ?
            """,
            (token_hash, _now()),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE email_verification_tokens SET consumed_at=? WHERE id=?", (_now(), row["id"])
        )
        return int(row["user_id"])


def create_password_reset_token(user_id: int, token_hash: str, expires_at: str) -> int:
    now = _now()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token_hash, expires_at, now),
        )
        return int(cur.lastrowid)


def consume_password_reset_token(token_hash: str) -> Optional[int]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, user_id FROM password_reset_tokens
            WHERE token_hash=? AND consumed_at IS NULL AND expires_at > ?
            """,
            (token_hash, _now()),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE password_reset_tokens SET consumed_at=? WHERE id=?", (_now(), row["id"])
        )
        return int(row["user_id"])


class DuplicateGenerationError(Exception):
    """같은 프로젝트에 이미 진행 중(pending)인 생성 요청이 있을 때 발생시킨다."""


# ---------------------------------------------------------------------------
# content_generations / content_generation_results (6A단계: Gemini 프롬프트 생성)
# ---------------------------------------------------------------------------
def create_content_generation(project_id: int, user_id: int, provider: str, model: str,
                               prompt_version: str, response_schema_version: str,
                               attempt_no: int = 1) -> int:
    """status='pending' 행을 만든다. 같은 project_id에 이미 pending 행이 있으면
    idx_content_generations_pending_lock 유니크 인덱스 위반으로 DuplicateGenerationError를 낸다."""
    now = _now()
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO content_generations
                    (project_id, user_id, attempt_no, provider, model, prompt_version,
                     response_schema_version, status, request_started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (project_id, user_id, attempt_no, provider, model, prompt_version,
                 response_schema_version, now),
            )
            return int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        # content_generations에는 이 부분 유니크 인덱스(프로젝트당 pending 1개) 외에
        # 다른 유니크 제약이 없으므로, 이 INSERT에서 나는 IntegrityError는 전부
        # 중복 생성 요청으로 간주한다. SQLite 버전에 따라 오류 메시지가 인덱스 이름이
        # 아니라 컬럼 이름만 담기도 해서(e.g. "UNIQUE constraint failed:
        # content_generations.project_id") 메시지 문자열로 판별하지 않는다.
        raise DuplicateGenerationError(str(exc)) from exc


def complete_content_generation(generation_id: int, status: str, http_status: Optional[int] = None,
                                 error_code: str = "", retry_count: int = 0,
                                 latency_ms: int = 0) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE content_generations SET
                status=?, http_status=?, error_code=?, retry_count=?, latency_ms=?, completed_at=?
            WHERE id=?
            """,
            (status, http_status, error_code, retry_count, latency_ms, _now(), generation_id),
        )


def get_content_generation(generation_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM content_generations WHERE id=?", (generation_id,)).fetchone()
        return dict(row) if row else None


def count_content_generation_attempts(project_id: int) -> int:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM content_generations WHERE project_id=?", (project_id,)
        ).fetchone()
        return int(row[0])


def list_content_generations_for_project(project_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM content_generations WHERE project_id=? ORDER BY attempt_no", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_generation_result(generation_id: int, project_id: int, fields: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO content_generation_results
                (generation_id, project_id, title, summary, body, call_to_action,
                 keywords_json, shortform_script, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id, project_id, fields.get("title", ""), fields.get("summary", ""),
                fields.get("body", ""), fields.get("call_to_action", ""),
                fields.get("keywords_json", "[]"), fields.get("shortform_script", ""), _now(),
            ),
        )
        return int(cur.lastrowid)


def get_latest_generation_result_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM content_generation_results
            WHERE project_id=? ORDER BY id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# content_channel_results / content_video_scripts (6B단계: SNS 8채널)
# ---------------------------------------------------------------------------
def upsert_channel_result(generation_id: int, project_id: int, channel_code: str, fields: dict) -> int:
    """채널 하나의 결과를 저장한다. 이미 있으면 갱신(재생성 시 다른 7개 채널은 건드리지 않는다).
    새로 생성/재생성할 때는 항상 original_* 도 같은 값으로 갱신하고 is_edited를 0으로 되돌린다
    (재생성은 새 AI 결과가 곧 새 원본이 되므로)."""
    now = _now()
    hashtags_json = fields.get("hashtags_json", "[]")
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM content_channel_results WHERE project_id=? AND channel_code=?",
            (project_id, channel_code),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_channel_results SET
                    generation_id=?, title=?, body=?, hashtags_json=?, cta=?,
                    original_title=?, original_body=?, original_hashtags_json=?, original_cta=?,
                    is_edited=0, status='ready', updated_at=?
                WHERE id=?
                """,
                (
                    generation_id, fields.get("title", ""), fields.get("body", ""), hashtags_json,
                    fields.get("cta", ""), fields.get("title", ""), fields.get("body", ""),
                    hashtags_json, fields.get("cta", ""), now, existing["id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO content_channel_results
                (generation_id, project_id, channel_code, title, body, hashtags_json, cta,
                 original_title, original_body, original_hashtags_json, original_cta,
                 is_edited, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ready', ?, ?)
            """,
            (
                generation_id, project_id, channel_code, fields.get("title", ""), fields.get("body", ""),
                hashtags_json, fields.get("cta", ""), fields.get("title", ""), fields.get("body", ""),
                hashtags_json, fields.get("cta", ""), now, now,
            ),
        )
        return int(cur.lastrowid)


def list_channel_results_for_project(project_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM content_channel_results WHERE project_id=?", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_channel_result(project_id: int, channel_code: str) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT * FROM content_channel_results WHERE project_id=? AND channel_code=?",
            (project_id, channel_code),
        ).fetchone()
        return dict(row) if row else None


def update_channel_result_manual_edit(project_id: int, channel_code: str, title: str, body: str,
                                       hashtags_json: str, cta: str) -> bool:
    """소유권 확인은 라우터가 project 조회 시 이미 끝낸 뒤 호출한다(project_id로 스코프됨)."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE content_channel_results SET
                title=?, body=?, hashtags_json=?, cta=?, is_edited=1, updated_at=?
            WHERE project_id=? AND channel_code=?
            """,
            (title, body, hashtags_json, cta, _now(), project_id, channel_code),
        )
        return cur.rowcount > 0


def revert_channel_result(project_id: int, channel_code: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE content_channel_results SET
                title=original_title, body=original_body, hashtags_json=original_hashtags_json,
                cta=original_cta, is_edited=0, updated_at=?
            WHERE project_id=? AND channel_code=?
            """,
            (_now(), project_id, channel_code),
        )
        return cur.rowcount > 0


def upsert_video_script(generation_id: int, project_id: int, voice_script: str,
                         scene_sentences_json: str) -> int:
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM content_video_scripts WHERE project_id=?", (project_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_video_scripts SET
                    generation_id=?, voice_script=?, scene_sentences_json=?, updated_at=?
                WHERE id=?
                """,
                (generation_id, voice_script, scene_sentences_json, now, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO content_video_scripts
                (generation_id, project_id, voice_script, scene_sentences_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (generation_id, project_id, voice_script, scene_sentences_json, now, now),
        )
        return int(cur.lastrowid)


def get_video_script_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT * FROM content_video_scripts WHERE project_id=?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# content_tts_sentences / content_tts_master / content_srt (단계7)
# ---------------------------------------------------------------------------
def replace_tts_sentences(project_id: int, sentences: list[dict]) -> None:
    """한 프로젝트의 문장별 TTS 계획을 통째로 다시 쓴다(최초 생성 시에만 사용).
    이미 생성된 실제 wav 파일이 있는 뒤에는 이 함수를 다시 호출하지 않고
    upsert_tts_sentence_result()로 문장별 결과만 갱신한다."""
    now = _now()
    with get_connection() as conn:
        conn.execute("DELETE FROM content_tts_sentences WHERE project_id=?", (project_id,))
        conn.executemany(
            """
            INSERT INTO content_tts_sentences
                (project_id, sentence_index, scene_index, original_text, normalized_text,
                 voice, speed, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            [
                (project_id, s["sentence_index"], s["scene_index"], s["original_text"],
                 s["normalized_text"], s["voice"], s["speed"], now, now)
                for s in sentences
            ],
        )


def upsert_tts_sentence_result(project_id: int, sentence_index: int, status: str,
                                relative_wav_path: str = "", duration_seconds: float = 0.0,
                                error_code: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE content_tts_sentences SET
                status=?, relative_wav_path=?, duration_seconds=?, error_code=?, updated_at=?
            WHERE project_id=? AND sentence_index=?
            """,
            (status, relative_wav_path, duration_seconds, error_code, _now(), project_id, sentence_index),
        )


def list_tts_sentences_for_project(project_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM content_tts_sentences WHERE project_id=? ORDER BY sentence_index",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_tts_master(project_id: int, status: str, relative_wav_path: str = "",
                       total_duration_seconds: float = 0.0, sentence_gap_seconds: float = 0.0,
                       voice: str = "", error_code: str = "") -> None:
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM content_tts_master WHERE project_id=?", (project_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_tts_master SET
                    status=?, relative_wav_path=?, total_duration_seconds=?, sentence_gap_seconds=?,
                    voice=?, error_code=?, updated_at=?
                WHERE id=?
                """,
                (status, relative_wav_path, total_duration_seconds, sentence_gap_seconds,
                 voice, error_code, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO content_tts_master
                    (project_id, relative_wav_path, total_duration_seconds, sentence_gap_seconds,
                     voice, status, error_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, relative_wav_path, total_duration_seconds, sentence_gap_seconds,
                 voice, status, error_code, now, now),
            )


def get_tts_master_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            "SELECT * FROM content_tts_master WHERE project_id=?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_srt_result(project_id: int, status: str, relative_srt_path: str = "", cue_count: int = 0,
                       last_cue_end_seconds: float = 0.0, audio_duration_seconds: float = 0.0,
                       drift_seconds: float = 0.0, error_code: str = "") -> None:
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM content_srt WHERE project_id=?", (project_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_srt SET
                    status=?, relative_srt_path=?, cue_count=?, last_cue_end_seconds=?,
                    audio_duration_seconds=?, drift_seconds=?, error_code=?, updated_at=?
                WHERE id=?
                """,
                (status, relative_srt_path, cue_count, last_cue_end_seconds,
                 audio_duration_seconds, drift_seconds, error_code, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO content_srt
                    (project_id, relative_srt_path, cue_count, last_cue_end_seconds,
                     audio_duration_seconds, drift_seconds, status, error_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, relative_srt_path, cue_count, last_cue_end_seconds,
                 audio_duration_seconds, drift_seconds, status, error_code, now, now),
            )


def get_srt_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM content_srt WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# content_scenes / content_music_mix / content_mp4 (단계8)
# ---------------------------------------------------------------------------
def replace_scenes(project_id: int, scenes: list[dict]) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute("DELETE FROM content_scenes WHERE project_id=?", (project_id,))
        conn.executemany(
            """
            INSERT INTO content_scenes
                (project_id, scene_index, sentence_index, start_seconds, duration_seconds,
                 zoom_type, zoom_start, zoom_end, transition_in_seconds, color0, color1,
                 relative_clip_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (project_id, s["scene_index"], s["sentence_index"], s["start_seconds"],
                 s["duration_seconds"], s["zoom_type"], s["zoom_start"], s["zoom_end"],
                 s["transition_in_seconds"], s["color0"], s["color1"], s.get("relative_clip_path", ""), now)
                for s in scenes
            ],
        )


def list_scenes_for_project(project_id: int) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM content_scenes WHERE project_id=? ORDER BY scene_index", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_music_mix(project_id: int, status: str, source_relative_path: str = "",
                      volume_level: str = "normal", relative_mixed_audio_path: str = "",
                      total_duration_seconds: float = 0.0, error_code: str = "") -> None:
    now = _now()
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM content_music_mix WHERE project_id=?", (project_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_music_mix SET
                    status=?, source_relative_path=?, volume_level=?, relative_mixed_audio_path=?,
                    total_duration_seconds=?, error_code=?, updated_at=?
                WHERE id=?
                """,
                (status, source_relative_path, volume_level, relative_mixed_audio_path,
                 total_duration_seconds, error_code, now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO content_music_mix
                    (project_id, source_relative_path, volume_level, relative_mixed_audio_path,
                     total_duration_seconds, status, error_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, source_relative_path, volume_level, relative_mixed_audio_path,
                 total_duration_seconds, status, error_code, now, now),
            )


def get_music_mix_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM content_music_mix WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None


def upsert_mp4_result(project_id: int, status: str, relative_mp4_path: str = "", width: int = 0,
                       height: int = 0, fps: float = 0.0, video_codec: str = "", audio_codec: str = "",
                       duration_seconds: float = 0.0, file_size_bytes: int = 0, error_code: str = "",
                       render_method: str = "server", fallback_reason: str = "") -> None:
    now = _now()
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM content_mp4 WHERE project_id=?", (project_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE content_mp4 SET
                    status=?, relative_mp4_path=?, width=?, height=?, fps=?, video_codec=?, audio_codec=?,
                    duration_seconds=?, file_size_bytes=?, error_code=?, render_method=?, fallback_reason=?,
                    updated_at=?
                WHERE id=?
                """,
                (status, relative_mp4_path, width, height, fps, video_codec, audio_codec,
                 duration_seconds, file_size_bytes, error_code, render_method, fallback_reason,
                 now, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO content_mp4
                    (project_id, relative_mp4_path, width, height, fps, video_codec, audio_codec,
                     duration_seconds, file_size_bytes, status, error_code, render_method, fallback_reason,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, relative_mp4_path, width, height, fps, video_codec, audio_codec,
                 duration_seconds, file_size_bytes, status, error_code, render_method, fallback_reason,
                 now, now),
            )


def get_mp4_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT * FROM content_mp4 WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None


def try_start_mp4_render(project_id: int) -> bool:
    """작업 ID별 렌더 잠금. 이미 status='rendering'이면 획득 실패(중복 렌더 방지, 작업지시 31-10장).
    성공하면 즉시 status='rendering'으로 표시해 잠근다."""
    now = _now()
    with get_connection() as conn:
        existing = conn.execute("SELECT status FROM content_mp4 WHERE project_id=?", (project_id,)).fetchone()
        if existing and existing["status"] == "rendering":
            return False
        if existing:
            conn.execute(
                "UPDATE content_mp4 SET status='rendering', error_code='', updated_at=? WHERE project_id=?",
                (now, project_id),
            )
        else:
            conn.execute(
                "INSERT INTO content_mp4 (project_id, status, created_at, updated_at) VALUES (?, 'rendering', ?, ?)",
                (project_id, now, now),
            )
        return True


def save_render_diagnostics(project_id: int, user_id: int, fields: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO content_render_diagnostics
                (project_id, user_id, render_method, webgpu_ready, webcodecs_ready, memory_mb,
                 outcome, fallback_reason, total_ms, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, user_id, fields.get("render_method", ""),
                1 if fields.get("webgpu_ready") else 0, 1 if fields.get("webcodecs_ready") else 0,
                fields.get("memory_mb"), fields.get("outcome", ""), fields.get("fallback_reason", ""),
                fields.get("total_ms", 0), (fields.get("user_agent", "") or "")[:300], _now(),
            ),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# 관리자 대시보드/진단 집계
# ---------------------------------------------------------------------------
def count_content_generation_calls() -> int:
    with get_readonly_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM content_generations").fetchone()[0])


def count_tts_master_success() -> int:
    with get_readonly_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM content_tts_master WHERE status='success'").fetchone()
        return int(row[0])


def count_mp4_by_render_method() -> dict:
    """로컬(webgpu/webcodecs)·서버 렌더 성공 건수와 폴백 발생 건수."""
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT render_method, COUNT(*) n FROM content_mp4 WHERE status='success' GROUP BY render_method"
        ).fetchall()
        fallback_n = conn.execute(
            "SELECT COUNT(*) FROM content_mp4 WHERE fallback_reason != ''"
        ).fetchone()[0]
    result = {"local": 0, "server": 0, "fallback": int(fallback_n)}
    for r in rows:
        if r["render_method"] == "server":
            result["server"] += r["n"]
        else:
            result["local"] += r["n"]
    return result


def list_render_diagnostics(limit: int = 50) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.*, u.email AS user_email
            FROM content_render_diagnostics d JOIN users u ON u.id = d.user_id
            ORDER BY d.created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_audit_logs(q: str = "", action: str = "", limit: int = 100, offset: int = 0) -> list[dict]:
    where = ["1=1"]
    params: list[Any] = []
    if action:
        where.append("a.action=?")
        params.append(action)
    if q:
        where.append("(u.email LIKE ? OR a.target_type LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    sql = f"""
        SELECT a.*, u.email AS user_email
        FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
        WHERE {' AND '.join(where)}
        ORDER BY a.created_at DESC LIMIT ? OFFSET ?
    """
    params += [limit, offset]
    with get_readonly_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def list_distinct_audit_actions() -> list[str]:
    with get_readonly_connection() as conn:
        rows = conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action").fetchall()
        return [r["action"] for r in rows]


# ---------------------------------------------------------------------------
# TTS·렌더 진단 (관리자)
# ---------------------------------------------------------------------------
def count_tts_master_by_status() -> dict:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) n FROM content_tts_master GROUP BY status"
        ).fetchall()
    counts = {"success": 0, "failed": 0, "pending": 0}
    for r in rows:
        counts[r["status"]] = r["n"]
    return counts


def count_tts_sentences_by_voice() -> list[dict]:
    """음성별 문장 성공/실패 건수, 평균 오디오 길이(초), 평균 생성 소요시간(초).
    생성 소요시간은 별도로 계측하는 컬럼이 없으므로, 같은 프로젝트 안에서 문장이
    순서대로 합성되는 실제 흐름(replace_tts_sentences가 모든 문장을 batch 시작
    시각으로 created_at=updated_at을 세팅하고, upsert_tts_sentence_result가 해당
    문장 합성이 끝난 실제 시각으로 updated_at을 갱신하는 구조)을 이용해 이전 문장
    완료 시각과의 실제 시간차로 추정한다. 이는 근사값이며 화면에도 '추정'으로
    표기한다(작업지시 13번: 추측을 사실처럼 기록하지 않는다)."""
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            WITH ordered AS (
                SELECT project_id, sentence_index, voice, status, duration_seconds, updated_at,
                       COALESCE(
                           LAG(updated_at) OVER (PARTITION BY project_id ORDER BY sentence_index),
                           created_at
                       ) AS prev_time
                FROM content_tts_sentences
            )
            SELECT voice,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_n,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_n,
                   AVG(CASE WHEN status='success' THEN duration_seconds END) AS avg_duration,
                   AVG(CASE WHEN status='success'
                            THEN (julianday(updated_at) - julianday(prev_time)) * 86400.0 END) AS avg_gen_seconds
            FROM ordered
            WHERE voice != ''
            GROUP BY voice
            """
        ).fetchall()
        return [dict(r) for r in rows]


def list_recent_tts_failures(limit: int = 10) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            SELECT s.project_id, s.sentence_index, s.error_code, s.updated_at,
                   p.job_uid, p.title, u.email AS user_email
            FROM content_tts_sentences s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.user_id
            WHERE s.status='failed'
            ORDER BY s.updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_render_success_rates() -> dict:
    """렌더 방식(local/server)별 성공률."""
    with get_readonly_connection() as conn:
        rows = conn.execute(
            "SELECT render_method, status, COUNT(*) n FROM content_mp4 GROUP BY render_method, status"
        ).fetchall()
    result: dict = {}
    for r in rows:
        m = result.setdefault(r["render_method"] or "server", {"total": 0, "success": 0})
        m["total"] += r["n"]
        if r["status"] == "success":
            m["success"] += r["n"]
    for m in result.values():
        m["rate_pct"] = round(m["success"] / m["total"] * 100, 1) if m["total"] else 0.0
    return result


def count_fallback_reasons() -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            SELECT fallback_reason, COUNT(*) n FROM content_mp4
            WHERE fallback_reason != '' GROUP BY fallback_reason ORDER BY n DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_browser_feature_detection_summary() -> dict:
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(webgpu_ready) AS webgpu_ready_n,
                   SUM(webcodecs_ready) AS webcodecs_ready_n
            FROM content_render_diagnostics
            """
        ).fetchone()
    total = row["total"] or 0
    return {
        "total": total,
        "webgpu_ready_n": row["webgpu_ready_n"] or 0,
        "webcodecs_ready_n": row["webcodecs_ready_n"] or 0,
    }


def list_recent_mp4_with_meta(limit: int = 15) -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.*, p.job_uid, p.title, u.email AS user_email
            FROM content_mp4 m
            JOIN projects p ON p.id = m.project_id
            JOIN users u ON u.id = p.user_id
            ORDER BY m.updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 대표 썸네일 (archive_items를 media_type='thumbnail'로 재사용)
# ---------------------------------------------------------------------------
def get_primary_thumbnail_for_project(project_id: int) -> Optional[dict]:
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM archive_items
            WHERE project_id=? AND media_type='thumbnail' AND media_deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return dict(row) if row else None


def save_primary_thumbnail(project_id: int, user_id: int, relative_path: str, file_size_bytes: int) -> list[str]:
    """대표 썸네일을 저장한다. 기존 활성 항목이 있으면 같은 트랜잭션에서 소프트 삭제하고
    새 항목 1개만 삽입해 항상 활성 항목이 최대 1개로 수렴하도록 보장한다(동시 요청·이중
    클릭에도 안전 - get_connection()의 전역 쓰기 락이 이 블록 전체를 직렬화한다).
    실제 파일 삭제는 호출부(서비스 계층)가 반환된 옛 경로 목록으로 트랜잭션 밖에서 수행한다."""
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, relative_path FROM archive_items
            WHERE project_id=? AND media_type='thumbnail' AND media_deleted_at IS NULL
            """,
            (project_id,),
        ).fetchall()
        old_paths = [r["relative_path"] for r in existing]
        for r in existing:
            conn.execute(
                "UPDATE archive_items SET media_deleted_at=?, updated_at=? WHERE id=?",
                (now, now, r["id"]),
            )
        conn.execute(
            """
            INSERT INTO archive_items
                (project_id, user_id, media_type, relative_path, file_size_bytes, is_primary, created_at, updated_at)
            VALUES (?, ?, 'thumbnail', ?, ?, 1, ?, ?)
            """,
            (project_id, user_id, relative_path, file_size_bytes, now, now),
        )
    return old_paths


def count_active_thumbnails_for_project(project_id: int) -> int:
    """검증용: 현재 활성(소프트 삭제되지 않은) 대표 썸네일 행 수."""
    with get_readonly_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM archive_items
            WHERE project_id=? AND media_type='thumbnail' AND media_deleted_at IS NULL
            """,
            (project_id,),
        ).fetchone()
        return int(row[0])
