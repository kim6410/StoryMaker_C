# -*- coding: utf-8 -*-
"""프로젝트 전용 ffprobe만 사용하는 공용 미디어 조사 유틸리티.
시스템 PATH의 ffprobe에 의존하지 않는다(00_READ_FIRST 5-1장)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from app.config import FFPROBE_PATH

_PROBE_TIMEOUT_SECONDS = 30


@dataclass
class ProbeResult:
    ok: bool
    duration_seconds: float = 0.0
    codec_name: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    error_detail: str = ""


def probe_media(path: str) -> ProbeResult:
    """오디오/영상 파일 하나의 실제 길이를 ffprobe로 측정한다.
    글자 수 비율 등 추정치가 아니라 실제 파일을 측정한 값만 신뢰한다."""
    if not FFPROBE_PATH.is_file():
        return ProbeResult(ok=False, error_detail=f"ffprobe not found: {FFPROBE_PATH}")
    try:
        result = subprocess.run(
            [str(FFPROBE_PATH), "-v", "error", "-show_entries", "format=duration:stream=codec_name,codec_type",
             "-of", "json", path],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(ok=False, error_detail="ffprobe timeout")
    except OSError as exc:
        return ProbeResult(ok=False, error_detail=f"ffprobe exec failed: {exc}")

    if result.returncode != 0:
        return ProbeResult(ok=False, error_detail=(result.stderr or "")[:300])
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return ProbeResult(ok=False, error_detail="invalid ffprobe json output")

    duration = float((data.get("format") or {}).get("duration") or 0)
    streams = data.get("streams") or []
    codec = streams[0].get("codec_name", "") if streams else ""
    video_codec = next((s.get("codec_name", "") for s in streams if s.get("codec_type") == "video"), "")
    audio_codec = next((s.get("codec_name", "") for s in streams if s.get("codec_type") == "audio"), "")
    if duration <= 0:
        return ProbeResult(ok=False, error_detail=f"duration<=0 (codec={codec})")
    return ProbeResult(ok=True, duration_seconds=round(duration, 3), codec_name=codec,
                        video_codec=video_codec, audio_codec=audio_codec)
