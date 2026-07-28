# -*- coding: utf-8 -*-
"""계획서 21번: runtime/music/mp3 배경음악을 스캔해 music_catalog에 메타데이터를 채운다.

- 파일을 옮기거나 이름을 바꾸지 않는다.
- 같은 SHA-256은 중복 후보로만 표시하고 삭제하지 않는다.
- ffprobe는 프로젝트 전용 경로(runtime/ffmpeg/bin/ffprobe.exe)만 사용한다(전역 PATH 의존 금지).
- ffprobe 실패는 duration=0으로 조용히 넘기지 않고, 실패 사유별로 구분해 최종 결과에 보고한다.
- DB 접근은 app.db.repository를 통해서만 한다(이 스크립트에서 SQL을 직접 실행하지 않는다).

python -m scripts.scan_music_catalog 로 실행한다.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import FFPROBE_PATH, MUSIC_LIBRARY_DIR, PROJECT_ROOT
from app.db import repository as repo
from app.db.migrations import run_migrations

PROBE_TIMEOUT_SECONDS = 30


@dataclass
class ProbeResult:
    status: str  # "ok" | "ffprobe_missing" | "timeout" | "process_error" | "parse_failed" | "invalid_media"
    duration_seconds: float = 0.0
    codec: str = ""
    bitrate: int = 0
    sample_rate: int = 0
    detail: str = ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> ProbeResult:
    if not FFPROBE_PATH.is_file():
        return ProbeResult(status="ffprobe_missing", detail=str(FFPROBE_PATH))

    try:
        result = subprocess.run(
            [str(FFPROBE_PATH), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,bit_rate,sample_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(status="timeout", detail=f">{PROBE_TIMEOUT_SECONDS}s")
    except OSError as exc:
        return ProbeResult(status="ffprobe_missing", detail=str(exc)[:200])

    if result.returncode != 0:
        return ProbeResult(status="process_error", detail=(result.stderr or "")[:300])

    try:
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        if not streams:
            return ProbeResult(status="invalid_media", detail="no audio stream")
        stream = streams[0]
        duration = float(fmt.get("duration") or 0)
        codec = str(stream.get("codec_name") or "")
    except (ValueError, json.JSONDecodeError) as exc:
        return ProbeResult(status="parse_failed", detail=str(exc)[:200])

    if duration <= 0 or not codec:
        return ProbeResult(status="invalid_media", detail=f"duration={duration} codec={codec}")

    return ProbeResult(
        status="ok",
        duration_seconds=round(duration, 2),
        codec=codec,
        bitrate=int(stream.get("bit_rate") or 0),
        sample_rate=int(stream.get("sample_rate") or 0),
    )


def main() -> int:
    run_migrations()
    if not MUSIC_LIBRARY_DIR.is_dir():
        print("music library dir not found:", MUSIC_LIBRARY_DIR)
        return 1
    if not FFPROBE_PATH.is_file():
        print("WARNING: ffprobe not found at project path:", FFPROBE_PATH)

    files = sorted(MUSIC_LIBRARY_DIR.glob("*.mp3"))
    print(f"found {len(files)} mp3 files")

    now = datetime.now(timezone.utc).isoformat()
    ok_count = 0
    failed: list[tuple[str, str, str]] = []  # (filename, status, detail)
    duration_zero_count = 0
    duplicate_count = 0
    codec_counter: Counter[str] = Counter()

    for path in files:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        size_bytes = path.stat().st_size
        sha256 = _sha256(path)
        probe = _probe(path)

        if probe.status != "ok":
            failed.append((path.name, probe.status, probe.detail))

        if probe.duration_seconds <= 0:
            duration_zero_count += 1
        if probe.codec:
            codec_counter[probe.codec] += 1

        duplicate_of_id = repo.get_music_id_by_sha256(sha256)
        # 자기 자신이 이미 등록돼 있으면(재스캔) 그 값은 중복으로 치지 않는다.
        existing_self = repo.get_music_by_relative_path(rel)
        if existing_self and duplicate_of_id == existing_self["id"]:
            duplicate_of_id = None
        if duplicate_of_id is not None:
            duplicate_count += 1

        repo.upsert_music_catalog_entry({
            "filename": path.name,
            "relative_path": rel,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "duration_seconds": probe.duration_seconds,
            "codec": probe.codec,
            "bitrate": probe.bitrate,
            "sample_rate": probe.sample_rate,
            "duplicate_of_id": duplicate_of_id,
            "scanned_at": now,
        })

        if probe.status == "ok":
            ok_count += 1

    print("\n=== 스캔 결과 ===")
    print(f"전체 파일: {len(files)}")
    print(f"정상 처리: {ok_count}")
    print(f"실패: {len(failed)}")
    for name, status, detail in failed:
        print(f"  - {name}: {status} ({detail})")
    print(f"duration=0 파일: {duration_zero_count}")
    print(f"중복 후보: {duplicate_count}")
    print(f"코덱 분포: {dict(codec_counter)}")
    print(f"DB 총 카탈로그 건수: {repo.count_music_catalog()}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
