# -*- coding: utf-8 -*-
"""
단계8 서비스 계층. 라우터는 이 모듈의 generate_mp4_for_project()만 호출한다.
장면 계획 -> 장면별 렌더 -> 전환 이어붙이기 -> 배경음악 혼합 -> 최종 mux -> ffprobe 검증까지
이 계층에서 처리한다."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import (
    JOBS_DIR,
    MP4_END_HOLD_SECONDS,
    MP4_FPS,
    MP4_HEIGHT,
    MP4_START_LEAD_SECONDS,
    MP4_WIDTH,
    to_relative_path,
)
from app.constants import (
    MP4_ERR_AUDIO_MIX_FAILED,
    MP4_ERR_CONCAT_FAILED,
    MP4_ERR_MUX_FAILED,
    MP4_ERR_NO_TTS,
    MP4_ERR_SCENE_RENDER_FAILED,
    MP4_ERR_VERIFY_FAILED,
    PROJECT_STATUS_COMPLETED,
    PROJECT_STATUS_FAILED,
    PROJECT_STATUS_RENDERING,
)
from app.content.music import resolve_music_path
from app.db import repository as repo
from app.media import renderer
from app.media.ffprobe_utils import probe_media
from app.media.scene_planner import build_scene_plan
from app.subtitle.srt_builder import SRT_SYNC_TOLERANCE_SECONDS

USER_MP4_ERROR_MESSAGES = {
    "no_tts": "먼저 음성·자막(TTS·SRT) 생성을 완료해야 영상을 만들 수 있습니다.",
    "scene_render_failed": "장면 영상 제작 중 오류가 발생했습니다. 다시 시도해 주세요.",
    "concat_failed": "장면을 이어붙이는 중 오류가 발생했습니다.",
    "audio_mix_failed": "음성과 배경음악을 합치는 중 오류가 발생했습니다.",
    "mux_failed": "최종 영상 파일을 만드는 중 오류가 발생했습니다.",
    "verify_failed": "만들어진 영상이 검증을 통과하지 못했습니다.",
}


@dataclass
class Mp4Outcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    duration_seconds: float = 0.0
    file_size_bytes: int = 0


def _media_dir(job_uid: str) -> Path:
    d = JOBS_DIR / job_uid / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_mp4_for_project(project: dict) -> Mp4Outcome:
    project_id = project["id"]
    job_uid = project["job_uid"]

    existing_mp4 = repo.get_mp4_for_project(project_id)
    if existing_mp4 and existing_mp4["status"] == "success":
        # 이미 정상 MP4가 있으면 Gemini·TTS는 물론 렌더도 다시 하지 않는다(단계별 재사용 원칙).
        return Mp4Outcome(ok=True, duration_seconds=existing_mp4["duration_seconds"],
                           file_size_bytes=existing_mp4["file_size_bytes"])

    master = repo.get_tts_master_for_project(project_id)
    srt = repo.get_srt_for_project(project_id)
    sentence_rows = repo.list_tts_sentences_for_project(project_id)
    if not master or master["status"] != "success" or not srt or srt["status"] != "success":
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_NO_TTS)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_NO_TTS, error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_NO_TTS])

    repo.update_project_status(project_id, PROJECT_STATUS_RENDERING)

    from app.config import PROJECT_ROOT
    srt_path = PROJECT_ROOT / srt["relative_srt_path"]
    scenes = build_scene_plan(srt_path, master["total_duration_seconds"], sentence_rows)

    repo.replace_scenes(project_id, [
        {
            "scene_index": s.scene_index, "sentence_index": s.sentence_index,
            "start_seconds": s.start_seconds, "duration_seconds": s.duration_seconds,
            "zoom_type": s.zoom_type, "zoom_start": s.zoom_start, "zoom_end": s.zoom_end,
            "transition_in_seconds": s.transition_in_seconds, "color0": s.color0, "color1": s.color1,
        }
        for s in scenes
    ])

    snapshot = json.loads(project.get("input_snapshot_json") or "{}")
    company_name = snapshot.get("company_name", "")
    phone_number = snapshot.get("phone_number", "")

    media_dir = _media_dir(job_uid)
    scenes_dir = media_dir / "scenes"
    texts_dir = media_dir / "text"

    clip_paths: list[Path] = []
    render_durations: list[float] = []
    for i, s in enumerate(scenes):
        next_transition = scenes[i + 1].transition_in_seconds if i + 1 < len(scenes) else 0.0
        render_duration = s.duration_seconds + next_transition
        clip_path = scenes_dir / f"scene_{i:03d}.mp4"
        ok, err = renderer.generate_scene_clip(s, render_duration, clip_path, texts_dir, company_name, phone_number)
        if not ok:
            repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_SCENE_RENDER_FAILED)
            repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_SCENE_RENDER_FAILED)
            return Mp4Outcome(ok=False, error_code=MP4_ERR_SCENE_RENDER_FAILED,
                               error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_SCENE_RENDER_FAILED])
        clip_paths.append(clip_path)
        render_durations.append(render_duration)

    transitions = [s.transition_in_seconds for s in scenes]
    silent_video_path = media_dir / "silent_concat.mp4"
    ok, err = renderer.concat_scenes_with_transitions(clip_paths, render_durations, transitions, silent_video_path)
    if not ok:
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_CONCAT_FAILED)
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_CONCAT_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_CONCAT_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_CONCAT_FAILED])

    total_duration = sum(s.duration_seconds for s in scenes)
    tts_master_path = PROJECT_ROOT / master["relative_wav_path"]

    music_path: Optional[Path] = None
    music_relative = project.get("music_relative_path") or ""
    if music_relative:
        music_path = resolve_music_path(music_relative)
    volume_level = "normal"

    final_audio_path = media_dir / "final_audio.wav"
    ok, err = renderer.build_final_audio(
        tts_master_path, music_path, total_duration, volume_level, final_audio_path,
        MP4_START_LEAD_SECONDS, MP4_END_HOLD_SECONDS,
    )
    repo.upsert_music_mix(
        project_id, status="success" if ok else "failed",
        source_relative_path=music_relative, volume_level=volume_level,
        relative_mixed_audio_path=to_relative_path(final_audio_path) if ok else "",
        total_duration_seconds=total_duration if ok else 0.0,
        error_code="" if ok else MP4_ERR_AUDIO_MIX_FAILED,
    )
    if not ok:
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_AUDIO_MIX_FAILED)
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_AUDIO_MIX_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_AUDIO_MIX_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_AUDIO_MIX_FAILED])

    final_mp4_path = media_dir / "final.mp4"
    ok, err = renderer.mux_final(silent_video_path, final_audio_path, final_mp4_path)
    if not ok:
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_MUX_FAILED)
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_MUX_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_MUX_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_MUX_FAILED])

    probe = probe_media(str(final_mp4_path))
    file_size = final_mp4_path.stat().st_size if final_mp4_path.is_file() else 0
    duration_ok = probe.ok and abs(probe.duration_seconds - total_duration) <= max(1.0, SRT_SYNC_TOLERANCE_SECONDS * 2)
    if not probe.ok or probe.codec_name != "h264" or file_size <= 0 or not duration_ok:
        repo.upsert_mp4_result(
            project_id, status="failed", error_code=MP4_ERR_VERIFY_FAILED,
            relative_mp4_path=to_relative_path(final_mp4_path), duration_seconds=probe.duration_seconds,
            file_size_bytes=file_size, video_codec=probe.codec_name,
        )
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_VERIFY_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_VERIFY_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_VERIFY_FAILED])

    repo.upsert_mp4_result(
        project_id, status="success", relative_mp4_path=to_relative_path(final_mp4_path),
        width=MP4_WIDTH, height=MP4_HEIGHT, fps=MP4_FPS, video_codec="h264", audio_codec="aac",
        duration_seconds=probe.duration_seconds, file_size_bytes=file_size,
    )
    repo.update_project_status(project_id, PROJECT_STATUS_COMPLETED)
    return Mp4Outcome(ok=True, duration_seconds=probe.duration_seconds, file_size_bytes=file_size)
