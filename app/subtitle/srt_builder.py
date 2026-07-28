# -*- coding: utf-8 -*-
"""
단계7: 문장별 실제 음성 길이(ffprobe 실측)를 기준으로 SRT를 만든다.
글자 수 비율로 시간을 임의 분배하지 않는다(작업지시 6장).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import JOBS_DIR, to_relative_path
from app.constants import (
    PROJECT_STATUS_SUBTITLE_READY,
    SRT_ERR_DRIFT_EXCEEDED,
    SRT_ERR_INCOMPLETE_AUDIO,
    SRT_ERR_NO_SENTENCES,
    SRT_SYNC_TOLERANCE_SECONDS,
)
from app.db import repository as repo

_MAX_CHARS_PER_LINE = 20
_MAX_LINES = 2

USER_SRT_ERROR_MESSAGES = {
    "no_sentences": "먼저 TTS 음성 생성을 완료해야 SRT를 만들 수 있습니다.",
    "incomplete_audio": "일부 문장의 음성이 아직 없어 SRT를 만들 수 없습니다. 실패한 문장을 먼저 재생성해 주세요.",
    "drift_exceeded": "자막 종료 시각과 실제 음성 길이의 차이가 허용 오차를 넘었습니다.",
}


@dataclass
class SrtOutcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    cue_count: int = 0
    last_cue_end_seconds: float = 0.0
    drift_seconds: float = 0.0


def _format_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _wrap_caption(text: str, max_chars: int = _MAX_CHARS_PER_LINE, max_lines: int = _MAX_LINES) -> str:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) >= max_lines - 1 and current:
            continue
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        head = lines[:max_lines - 1]
        tail = " ".join(lines[max_lines - 1:])
        lines = head + [tail[:max_chars * 2]]
    return "\n".join(lines)


def build_srt_for_project(project: dict) -> SrtOutcome:
    project_id = project["id"]
    job_uid = project["job_uid"]

    existing = repo.get_srt_for_project(project_id)
    if existing and existing["status"] == "success":
        # 기존 정상 SRT는 불필요하게 덮어쓰지 않는다(작업지시 6장).
        return SrtOutcome(ok=True, cue_count=existing["cue_count"],
                           last_cue_end_seconds=existing["last_cue_end_seconds"],
                           drift_seconds=existing["drift_seconds"])

    master = repo.get_tts_master_for_project(project_id)
    sentences = repo.list_tts_sentences_for_project(project_id)
    if not sentences:
        return SrtOutcome(ok=False, error_code=SRT_ERR_NO_SENTENCES,
                           error_message=USER_SRT_ERROR_MESSAGES[SRT_ERR_NO_SENTENCES])
    if not master or master["status"] != "success" or any(s["status"] != "success" for s in sentences):
        return SrtOutcome(ok=False, error_code=SRT_ERR_INCOMPLETE_AUDIO,
                           error_message=USER_SRT_ERROR_MESSAGES[SRT_ERR_INCOMPLETE_AUDIO])

    gap = master["sentence_gap_seconds"]
    cursor = 0.0
    cue_lines: list[str] = []
    for i, s in enumerate(sentences, start=1):
        start = cursor
        end = start + s["duration_seconds"]
        cue_lines.append(str(i))
        cue_lines.append(f"{_format_timestamp(start)} --> {_format_timestamp(end)}")
        cue_lines.append(_wrap_caption(s["original_text"]))
        cue_lines.append("")
        cursor = end + gap
    last_cue_end = cursor - gap  # 마지막 문장 뒤에는 gap을 더하지 않는다.

    drift = abs(last_cue_end - master["total_duration_seconds"])
    if drift > SRT_SYNC_TOLERANCE_SECONDS:
        return SrtOutcome(ok=False, error_code=SRT_ERR_DRIFT_EXCEEDED,
                           error_message=USER_SRT_ERROR_MESSAGES[SRT_ERR_DRIFT_EXCEEDED],
                           cue_count=len(sentences), last_cue_end_seconds=last_cue_end, drift_seconds=drift)

    subtitle_dir = JOBS_DIR / job_uid / "subtitle"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    srt_path = subtitle_dir / "subtitle.srt"
    srt_path.write_text("\n".join(cue_lines).strip() + "\n", encoding="utf-8")

    repo.upsert_srt_result(
        project_id, status="success", relative_srt_path=to_relative_path(srt_path),
        cue_count=len(sentences), last_cue_end_seconds=last_cue_end,
        audio_duration_seconds=master["total_duration_seconds"], drift_seconds=drift,
    )
    repo.update_project_status(project_id, PROJECT_STATUS_SUBTITLE_READY)
    return SrtOutcome(ok=True, cue_count=len(sentences), last_cue_end_seconds=last_cue_end, drift_seconds=drift)


def parse_srt(path: Path) -> list[dict]:
    """검증용: 만든 SRT가 실제로 파싱 가능한지 확인한다."""
    text = path.read_text(encoding="utf-8")
    blocks = [b for b in text.strip().split("\n\n") if b.strip()]
    cues = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"malformed cue block: {block!r}")
        index = int(lines[0])
        start_str, _, end_str = lines[1].partition(" --> ")
        cues.append({"index": index, "start": start_str, "end": end_str, "text": "\n".join(lines[2:])})
    return cues
