# -*- coding: utf-8 -*-
"""로그인 실패·비밀번호 재설정 요청용 인메모리 슬라이딩 윈도우 Rate Limit.
단일 프로세스 기준. 다중 워커로 확장하면 Redis 등 공유 저장소로 교체해야 한다.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limited, retry after {retry_after_seconds}s")


_EVENTS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def _prune(events: deque[float], now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    while events and events[0] <= cutoff:
        events.popleft()


def check(scope: str, keys: list[str], limit: int, window_seconds: int) -> None:
    now = time.time()
    with _LOCK:
        for key in keys:
            events = _EVENTS[(scope, key)]
            _prune(events, now, window_seconds)
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])))
                raise RateLimitExceeded(retry_after)


def record(scope: str, keys: list[str], window_seconds: int) -> None:
    now = time.time()
    with _LOCK:
        for key in keys:
            events = _EVENTS[(scope, key)]
            _prune(events, now, window_seconds)
            events.append(now)


def clear(scope: str, keys: list[str]) -> None:
    with _LOCK:
        for key in keys:
            _EVENTS.pop((scope, key), None)
