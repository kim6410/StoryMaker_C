# -*- coding: utf-8 -*-
"""
단계8 서비스 계층. 라우터는 이 모듈의 generate_mp4_for_project()만 호출한다.
장면 계획 -> 장면별 렌더 -> 전환 이어붙이기 -> 배경음악 혼합 -> 최종 mux -> ffprobe 검증까지
이 계층에서 처리한다."""
from __future__ import annotations

import json
import time
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
    to_absolute_path,
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


def _log_server_ffmpeg_diagnostics(project_id: int, user_id: int, started_at: float,
                                    outcome: str, error_code: str = "") -> None:
    """Claude 최우선 요청서(0729): 서버 FFmpeg 경로(generate_mp4_for_project)의 실제 소요시간을
    content_render_diagnostics에 남긴다. 지원 여부가 아니라 실제 실행 결과만 기록한다."""
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    repo.save_render_diagnostics(project_id, user_id, {
        "render_method": "server", "webgpu_ready": False, "webcodecs_ready": False,
        "wasm_supported": False, "server_ffmpeg_used": True, "ffmpeg_elapsed_ms": elapsed_ms,
        "outcome": outcome, "fallback_reason": error_code, "total_ms": elapsed_ms,
        "user_agent": "server",
    })


def _media_dir(job_uid: str) -> Path:
    d = JOBS_DIR / job_uid / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_scene_images(project: dict, media_dir: Path) -> list[Path]:
    """제작 화면에서 선택·업로드한 이 작업의 미디어를 장면 배경 이미지 순서대로 정리한다.
    영상 파일은 아직 슬라이드에 직접 넣지 않고(단계8 엔진은 정지 이미지 장면만 지원),
    가운데 지점 프레임을 1장 뽑아 정지 이미지로 대신 쓴다(과도한 신규 렌더 엔진 없이
    기존 이미지-장면 구조를 그대로 재사용, 최소 수정 우선)."""
    snapshot = json.loads(project.get("input_snapshot_json") or "{}")
    media_ids = snapshot.get("selected_media_ids") or []
    if not media_ids:
        return []

    user_id = project["user_id"]
    rows = []
    for mid in media_ids:
        row = repo.get_company_media_owned(mid, user_id)
        if row:
            rows.append(row)

    images: list[Path] = []
    frame_dir = media_dir / "source_frames"
    for row in rows:
        try:
            abs_path = to_absolute_path(row["relative_path"])
        except Exception:
            continue
        if not abs_path.is_file():
            continue
        if row["media_type"] == "image":
            images.append(abs_path)
            continue
        # 영상: 길이의 절반 지점에서 대표 프레임을 뽑아 정지 이미지로 사용한다.
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_path = frame_dir / f"video_frame_{row['id']}.jpg"
        probe = probe_media(str(abs_path))
        mid_ts = (probe.duration_seconds / 2) if probe.ok and probe.duration_seconds > 0 else 0.0
        ok, _err = renderer.extract_frame_at(abs_path, mid_ts, frame_path)
        if ok and frame_path.is_file():
            images.append(frame_path)
    return images


def generate_mp4_for_project(project: dict) -> Mp4Outcome:
    project_id = project["id"]
    job_uid = project["job_uid"]
    user_id = project["user_id"]

    existing_mp4 = repo.get_mp4_for_project(project_id)
    if existing_mp4 and existing_mp4["status"] == "success":
        # 이미 정상 MP4가 있으면 Gemini·TTS는 물론 렌더도 다시 하지 않는다(단계별 재사용 원칙).
        return Mp4Outcome(ok=True, duration_seconds=existing_mp4["duration_seconds"],
                           file_size_bytes=existing_mp4["file_size_bytes"])

    if not repo.try_start_mp4_render(project_id):
        # 동일 작업에서 로컬 렌더 업로드 등 다른 렌더가 이미 진행 중이면 중복 실행하지 않는다(31-10장).
        return Mp4Outcome(ok=False, error_code="render_in_progress",
                           error_message="이미 다른 렌더가 진행 중입니다. 잠시 후 다시 확인해 주세요.")

    master = repo.get_tts_master_for_project(project_id)
    srt = repo.get_srt_for_project(project_id)
    sentence_rows = repo.list_tts_sentences_for_project(project_id)
    if not master or master["status"] != "success" or not srt or srt["status"] != "success":
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_NO_TTS)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_NO_TTS, error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_NO_TTS])

    repo.update_project_status(project_id, PROJECT_STATUS_RENDERING)
    render_started = time.monotonic()

    media_dir = _media_dir(job_uid)
    scene_images = _resolve_scene_images(project, media_dir)

    srt_path = to_absolute_path(srt["relative_srt_path"])
    scenes = build_scene_plan(
        srt_path, master["total_duration_seconds"], sentence_rows, image_paths=scene_images or None
    )

    repo.replace_scenes(project_id, [
        {
            "scene_index": s.scene_index, "sentence_index": s.sentence_index,
            "start_seconds": s.start_seconds, "duration_seconds": s.duration_seconds,
            "zoom_type": s.zoom_type, "zoom_start": s.zoom_start, "zoom_end": s.zoom_end,
            "transition_in_seconds": s.transition_in_seconds, "color0": s.color0, "color1": s.color1,
            "image_relative_path": to_relative_path(s.image_path) if s.image_path else "",
            "caption": s.caption, "caption_start_local": s.caption_start_local,
            "caption_end_local": s.caption_end_local,
        }
        for s in scenes
    ])

    snapshot = json.loads(project.get("input_snapshot_json") or "{}")
    company_name = snapshot.get("company_name", "")
    phone_number = snapshot.get("phone_number", "")

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
            _log_server_ffmpeg_diagnostics(project_id, user_id, render_started,
                                            "server_failed", MP4_ERR_SCENE_RENDER_FAILED)
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
        _log_server_ffmpeg_diagnostics(project_id, user_id, render_started,
                                        "server_failed", MP4_ERR_CONCAT_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_CONCAT_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_CONCAT_FAILED])

    total_duration = sum(s.duration_seconds for s in scenes)
    tts_master_path = to_absolute_path(master["relative_wav_path"])

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
        _log_server_ffmpeg_diagnostics(project_id, user_id, render_started,
                                        "server_failed", MP4_ERR_AUDIO_MIX_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_AUDIO_MIX_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_AUDIO_MIX_FAILED])

    final_mp4_path = media_dir / "final.mp4"
    ok, err = renderer.mux_final(silent_video_path, final_audio_path, final_mp4_path)
    if not ok:
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_MUX_FAILED)
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_MUX_FAILED)
        _log_server_ffmpeg_diagnostics(project_id, user_id, render_started,
                                        "server_failed", MP4_ERR_MUX_FAILED)
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
        _log_server_ffmpeg_diagnostics(project_id, user_id, render_started,
                                        "server_failed", MP4_ERR_VERIFY_FAILED)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_VERIFY_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_VERIFY_FAILED])

    repo.upsert_mp4_result(
        project_id, status="success", relative_mp4_path=to_relative_path(final_mp4_path),
        width=MP4_WIDTH, height=MP4_HEIGHT, fps=MP4_FPS, video_codec="h264", audio_codec="aac",
        duration_seconds=probe.duration_seconds, file_size_bytes=file_size, render_method="server",
    )
    repo.update_project_status(project_id, PROJECT_STATUS_COMPLETED)
    _log_server_ffmpeg_diagnostics(project_id, user_id, render_started, "server_success")
    return Mp4Outcome(ok=True, duration_seconds=probe.duration_seconds, file_size_bytes=file_size)


def build_render_manifest(project: dict) -> Optional[dict]:
    """단계9: 로컬(브라우저) 렌더가 사용할 검증된 작업 명세. 서버가 이미 계산한 장면·오디오만
    내려주고, 브라우저가 임의 경로에 접근하지 못하도록 이 작업 소유의 파일 URL만 포함한다."""
    project_id = project["id"]
    job_uid = project["job_uid"]
    master = repo.get_tts_master_for_project(project_id)
    srt = repo.get_srt_for_project(project_id)
    if not master or master["status"] != "success" or not srt or srt["status"] != "success":
        return None

    scenes = repo.list_scenes_for_project(project_id)
    if not scenes:
        # 서버가 아직 장면을 만든 적이 없는 상태에서 로컬 렌더가 먼저 매니페스트를 요청한
        # 경우다. MP4와 썸네일이 서로 다른 이미지 목록을 쓰지 않도록, 서버 렌더와 동일한
        # _resolve_scene_images()로 같은 순서의 이미지를 배정한다(단계11 보완).
        srt_path = to_absolute_path(srt["relative_srt_path"])
        sentence_rows = repo.list_tts_sentences_for_project(project_id)
        scene_images = _resolve_scene_images(project, _media_dir(job_uid))
        scenes_spec = build_scene_plan(
            srt_path, master["total_duration_seconds"], sentence_rows, image_paths=scene_images or None
        )
        repo.replace_scenes(project_id, [
            {
                "scene_index": s.scene_index, "sentence_index": s.sentence_index,
                "start_seconds": s.start_seconds, "duration_seconds": s.duration_seconds,
                "zoom_type": s.zoom_type, "zoom_start": s.zoom_start, "zoom_end": s.zoom_end,
                "transition_in_seconds": s.transition_in_seconds, "color0": s.color0, "color1": s.color1,
                "image_relative_path": to_relative_path(s.image_path) if s.image_path else "",
                "caption": s.caption, "caption_start_local": s.caption_start_local,
                "caption_end_local": s.caption_end_local,
            }
            for s in scenes_spec
        ])
        scenes = repo.list_scenes_for_project(project_id)

    snapshot = json.loads(project.get("input_snapshot_json") or "{}")
    total_duration = sum(s["duration_seconds"] for s in scenes)

    music_relative = project.get("music_relative_path") or ""
    music_url = f"/content/music-preview/{Path(music_relative).name}" if music_relative else None

    return {
        "job_uid": job_uid,
        "width": MP4_WIDTH, "height": MP4_HEIGHT, "fps": MP4_FPS,
        "start_lead_seconds": MP4_START_LEAD_SECONDS, "end_hold_seconds": MP4_END_HOLD_SECONDS,
        "total_duration_seconds": total_duration,
        "company_name": snapshot.get("company_name", ""), "phone_number": snapshot.get("phone_number", ""),
        "tts_audio_url": f"/content/job/{job_uid}/tts/audio/full.wav",
        "music_url": music_url,
        "scenes": [
            {
                "scene_index": s["scene_index"], "start_seconds": s["start_seconds"],
                "duration_seconds": s["duration_seconds"], "zoom_type": s["zoom_type"],
                "zoom_start": s["zoom_start"], "zoom_end": s["zoom_end"],
                "transition_in_seconds": s["transition_in_seconds"],
                "color0": s["color0"], "color1": s["color1"],
                "caption": s.get("caption", ""),
                "caption_start_local": s.get("caption_start_local", 0.0),
                "caption_end_local": s.get("caption_end_local", 0.0),
                "image_url": (
                    f"/content/job/{job_uid}/mp4/scene-image/{s['scene_index']}"
                    if s.get("image_relative_path") else None
                ),
            }
            for s in scenes
        ],
    }


def accept_local_render_upload(project: dict, uploaded_path: Path) -> Mp4Outcome:
    """브라우저(WebGPU/WASM/WebCodecs)가 만든 MP4를 서버가 최종 검증 없이 그대로 완료 처리하지
    않는다(작업지시 31-14장). 서버 렌더와 동일한 코덱·해상도·길이 검증을 통과해야 저장한다."""
    project_id = project["id"]
    job_uid = project["job_uid"]

    master = repo.get_tts_master_for_project(project_id)
    srt = repo.get_srt_for_project(project_id)
    if not master or master["status"] != "success" or not srt or srt["status"] != "success":
        return Mp4Outcome(ok=False, error_code=MP4_ERR_NO_TTS, error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_NO_TTS])

    if not repo.try_start_mp4_render(project_id):
        return Mp4Outcome(ok=False, error_code="render_in_progress",
                           error_message="이미 다른 렌더가 진행 중입니다. 잠시 후 다시 확인해 주세요.")

    scenes = repo.list_scenes_for_project(project_id)
    expected_total = sum(s["duration_seconds"] for s in scenes) if scenes else (
        MP4_START_LEAD_SECONDS + master["total_duration_seconds"] + MP4_END_HOLD_SECONDS
    )

    probe = probe_media(str(uploaded_path))
    file_size = uploaded_path.stat().st_size if uploaded_path.is_file() else 0
    duration_ok = probe.ok and abs(probe.duration_seconds - expected_total) <= 1.5
    codec_ok = probe.video_codec in ("h264", "avc1") and bool(probe.audio_codec)
    if not probe.ok or not codec_ok or file_size <= 0 or not duration_ok:
        repo.upsert_mp4_result(project_id, status="failed", error_code=MP4_ERR_VERIFY_FAILED,
                                render_method="local")
        repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code=MP4_ERR_VERIFY_FAILED)
        uploaded_path.unlink(missing_ok=True)
        return Mp4Outcome(ok=False, error_code=MP4_ERR_VERIFY_FAILED,
                           error_message=USER_MP4_ERROR_MESSAGES[MP4_ERR_VERIFY_FAILED])

    final_mp4_path = _media_dir(job_uid) / "final.mp4"
    final_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    uploaded_path.replace(final_mp4_path)

    repo.upsert_mp4_result(
        project_id, status="success", relative_mp4_path=to_relative_path(final_mp4_path),
        width=MP4_WIDTH, height=MP4_HEIGHT, fps=MP4_FPS, video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        duration_seconds=probe.duration_seconds, file_size_bytes=final_mp4_path.stat().st_size,
        render_method="local",
    )
    repo.update_project_status(project_id, PROJECT_STATUS_COMPLETED)
    return Mp4Outcome(ok=True, duration_seconds=probe.duration_seconds,
                       file_size_bytes=final_mp4_path.stat().st_size)
