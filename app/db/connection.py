# -*- coding: utf-8 -*-
"""
StoryMaker Claude Lab 중앙 SQLite 연결 모듈.

다른 파일에서 sqlite3.connect()를 직접 호출하지 않는다.
모든 DB 접근은 get_connection() / get_readonly_connection()을 통한다.

공통 정책:
- journal_mode=WAL
- synchronous=NORMAL
- foreign_keys=ON
- busy_timeout=5000
- 쓰기 연결은 context manager 종료 시 자동 commit, 예외 발생 시 자동 rollback
- 읽기 전용 연결은 URI mode=ro 로 열어 쓰기 가능한 핸들을 아예 만들지 않는다
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from app.config import DB_PATH

BUSY_TIMEOUT_MS = 5000

# SQLite는 파일 하나에 여러 프로세스가 붙을 수 있지만, 이 프로젝트는 단일 프로세스로
# 운영하므로 프로세스 내부 다중 스레드 쓰기 경합을 완화하기 위한 보조 락을 둔다.
# (WAL + busy_timeout으로도 처리되지만, 이중 방어로 명시적 락을 추가한다.)
_WRITE_LOCK = threading.Lock()


def _apply_common_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")


def _apply_write_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _apply_common_pragmas(conn)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """쓰기 가능한 연결. 성공 시 commit, 예외 시 rollback, 항상 close."""
    with _WRITE_LOCK:
        conn = sqlite3.connect(str(DB_PATH), timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        _apply_write_pragmas(conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def get_readonly_connection() -> Iterator[sqlite3.Connection]:
    """읽기 전용 연결. 쓰기 가능한 핸들을 아예 열지 않는다."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    _apply_common_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()


def integrity_check() -> str:
    with get_readonly_connection() as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"


def foreign_key_check() -> list[dict]:
    with get_readonly_connection() as conn:
        rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        return [dict(r) for r in rows]


def current_journal_mode() -> str:
    with get_readonly_connection() as conn:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row else "unknown"
