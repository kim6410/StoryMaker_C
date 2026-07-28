# -*- coding: utf-8 -*-
"""
2단계 DB 자체 검증 스크립트.
- 마이그레이션 실행
- 샘플 데이터 CRUD
- 무결성 검사
- 동시 쓰기 접근 테스트

python -m scripts.db_selftest 로 실행한다.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import repository as repo
from app.db.connection import integrity_check, foreign_key_check, current_journal_mode
from app.db.migrations import run_migrations, applied_versions
from app.constants import (
    PROJECT_STATUS_COMPLETED,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name} {detail}")


def _reset_previous_selftest_data() -> None:
    """반복 실행 가능하도록 이전 셀프테스트 잔여 데이터만 선택적으로 정리한다."""
    from app.db.connection import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM subscription_plans WHERE code IN ('free', 'starter')")
        conn.execute("DELETE FROM users WHERE email='selftest@example.com'")


def run_crud_test() -> None:
    print("\n=== 1. 마이그레이션 ===")
    applied = run_migrations()
    check("migrations_applied_or_already_current", True, f"newly_applied={applied}, all={sorted(applied_versions())}")
    _reset_previous_selftest_data()

    print("\n=== 2. 샘플 데이터 CRUD ===")
    plan_free = repo.create_plan("free", "Free", monthly_project_limit=20, archive_item_limit=10, price_krw=0, sort_order=10)
    plan_starter = repo.create_plan("starter", "Starter", monthly_project_limit=20, archive_item_limit=20, price_krw=29000, sort_order=20)
    check("create_plan", plan_free > 0 and plan_starter > 0, f"free_id={plan_free} starter_id={plan_starter}")

    plans = repo.list_plans()
    check("list_plans_count", len(plans) == 2, f"count={len(plans)}")

    user_id = repo.create_user("selftest@example.com", "argon2-placeholder-hash", "셀프테스트 사용자")
    check("create_user", user_id > 0, f"user_id={user_id}")

    fetched = repo.get_user_by_email("selftest@example.com")
    check("get_user_by_email", fetched is not None and fetched["id"] == user_id)

    repo.update_user_status(user_id, "active")
    check("update_user_status", repo.get_user_by_id(user_id)["status"] == "active")

    sub_id = repo.assign_subscription(user_id, plan_free, "2026-07-28T00:00:00+00:00", "2026-08-27T00:00:00+00:00")
    check("assign_subscription", sub_id > 0)
    active_sub = repo.get_active_subscription(user_id)
    check("get_active_subscription_plan_code", active_sub is not None and active_sub["plan_code"] == "free")

    project = repo.create_project(user_id, "셀프테스트 프로젝트")
    check("create_project", project["id"] > 0 and project["job_uid"].startswith("proj_"))

    repo.update_project_status(project["id"], PROJECT_STATUS_COMPLETED, progress=100)
    fetched_project = repo.get_project(project["id"])
    check("update_project_status", fetched_project["status"] == PROJECT_STATUS_COMPLETED and fetched_project["progress"] == 100)

    item_id = repo.add_archive_item(
        project["id"], user_id, MEDIA_TYPE_IMAGE, "data/jobs/selftest/image_01.jpg",
        file_size_bytes=12345, checksum_sha256="deadbeef" * 8,
    )
    video_item_id = repo.add_archive_item(
        project["id"], user_id, MEDIA_TYPE_VIDEO, "data/jobs/selftest/final.mp4",
        file_size_bytes=999999, is_primary=True,
    )
    check("add_archive_item", item_id > 0 and video_item_id > 0)

    items = repo.list_archive_items_for_project(project["id"])
    check("list_archive_items_for_project", len(items) == 2, f"count={len(items)}")

    repo.mark_archive_item_deleted(item_id)
    remaining = repo.list_archive_items_for_user(user_id, exclude_deleted=True)
    check("mark_archive_item_deleted_excludes_from_list", all(r["id"] != item_id for r in remaining))

    log_id = repo.write_audit_log(user_id, "selftest_action", target_type="project", target_id=project["id"])
    check("write_audit_log", log_id > 0)
    logs = repo.list_audit_logs(limit=5)
    check("list_audit_logs", len(logs) >= 1)

    # 정리: 셀프테스트로 만든 사용자를 지우면 FK CASCADE로 관련 행도 함께 정리되는지 확인
    before_count = repo.count_audit_logs()
    repo.delete_user(user_id)
    check("get_user_after_delete_is_none", repo.get_user_by_id(user_id) is None)
    after_items = repo.list_archive_items_for_project(project["id"])
    check("archive_items_cascade_deleted", len(after_items) == 0, f"remaining={len(after_items)}")
    after_project = repo.get_project(project["id"])
    check("project_cascade_deleted", after_project is None)
    after_count = repo.count_audit_logs()
    check("audit_logs_set_null_not_deleted", after_count == before_count, f"before={before_count} after={after_count}")


def run_integrity_test() -> None:
    print("\n=== 3. 무결성 검사 ===")
    result = integrity_check()
    check("integrity_check_ok", result == "ok", f"result={result}")
    fk_problems = foreign_key_check()
    check("foreign_key_check_empty", len(fk_problems) == 0, f"problems={fk_problems}")
    jm = current_journal_mode()
    check("journal_mode_is_wal", jm.lower() == "wal", f"journal_mode={jm}")


def run_concurrency_test(thread_count: int = 20) -> None:
    print(f"\n=== 4. 동시 접근 테스트 ({thread_count} 스레드 동시 쓰기) ===")
    errors: list[str] = []
    lock_events: list[str] = []

    def worker(i: int) -> None:
        try:
            repo.write_audit_log(None, f"concurrency_test_{i}", target_type="selftest")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"thread_{i}: {exc}")

    before = repo.count_audit_logs()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start
    after = repo.count_audit_logs()

    check("concurrency_no_errors", len(errors) == 0, f"errors={errors}")
    check("concurrency_all_rows_written", after - before == thread_count, f"delta={after - before} expected={thread_count}")
    print(f"     elapsed={elapsed:.3f}s")


def main() -> int:
    run_crud_test()
    run_integrity_test()
    run_concurrency_test()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n=== 결과 요약: {len(RESULTS) - len(failed)}/{len(RESULTS)} PASS ===")
    if failed:
        print("실패 항목:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
