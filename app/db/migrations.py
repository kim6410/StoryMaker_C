# -*- coding: utf-8 -*-
"""
스키마 버전 관리 및 마이그레이션 실행기.

schema_migrations 테이블에 적용된 버전을 기록하고, 아직 적용되지 않은
마이그레이션만 순서대로 실행한다. 각 마이그레이션은 하나의 트랜잭션으로 처리된다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable

from app.db.connection import get_connection

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
            email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0,1)),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        );

        CREATE TABLE subscription_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            monthly_project_limit INTEGER,
            archive_item_limit INTEGER,
            price_krw INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_id INTEGER NOT NULL REFERENCES subscription_plans(id) ON DELETE RESTRICT,
            period_started_at TEXT,
            period_ends_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_uid TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            error_code TEXT NOT NULL DEFAULT '',
            progress INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE archive_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL CHECK (media_type IN ('image','audio','subtitle','video','thumbnail')),
            relative_path TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            checksum_sha256 TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
            media_deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            metadata_json TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_projects_user_status ON projects(user_id, status);
        CREATE INDEX idx_archive_items_project ON archive_items(project_id);
        CREATE INDEX idx_archive_items_user_created ON archive_items(user_id, created_at);
        CREATE INDEX idx_user_subscriptions_user ON user_subscriptions(user_id);
        CREATE INDEX idx_audit_logs_user_created ON audit_logs(user_id, created_at);
        """
    )


def _migration_002_auth_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            revoked_at TEXT,
            ip_address TEXT,
            user_agent TEXT
        );

        CREATE TABLE email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_sessions_user ON sessions(user_id);
        CREATE INDEX idx_sessions_expires ON sessions(expires_at);
        CREATE INDEX idx_email_verif_user ON email_verification_tokens(user_id);
        CREATE INDEX idx_pw_reset_user ON password_reset_tokens(user_id);
        """
    )


def _migration_003_companies(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company_name TEXT NOT NULL,
            owner_name TEXT NOT NULL DEFAULT '',
            phone_number TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            region TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            main_services TEXT NOT NULL DEFAULT '',
            target_customers TEXT NOT NULL DEFAULT '',
            core_strength TEXT NOT NULL DEFAULT '',
            tone_preference TEXT NOT NULL DEFAULT '',
            forbidden_words TEXT NOT NULL DEFAULT '',
            website_url TEXT NOT NULL DEFAULT '',
            free_request TEXT NOT NULL DEFAULT '',
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_companies_user ON companies(user_id);
        """
    )


# 순서대로 등록. 이미 적용된 번호는 다시 실행하지 않는다.
MIGRATIONS: list[Migration] = [
    (1, "initial_schema", _migration_001_initial_schema),
    (2, "auth_tables", _migration_002_auth_tables),
    (3, "companies", _migration_003_companies),
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def applied_versions() -> set[int]:
    with get_connection() as conn:
        _ensure_migrations_table(conn)
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(r[0]) for r in rows}


def run_migrations() -> list[int]:
    """아직 적용되지 않은 마이그레이션만 순서대로 실행하고, 새로 적용된 버전 목록을 반환한다."""
    newly_applied: list[int] = []
    with get_connection() as conn:
        _ensure_migrations_table(conn)
        done = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for version, name, func in MIGRATIONS:
            if version in done:
                continue
            func(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _now()),
            )
            newly_applied.append(version)
    return newly_applied
