# -*- coding: utf-8 -*-
"""
단계7 서비스 계층. 라우터는 이 모듈의 함수만 호출한다.
문장 정규화 -> 문장별 TTS 합성(Adapter) -> ffprobe 실측 길이 저장 -> 전체 합성음성 조립까지
이 계층에서 처리한다(작업지시 3장).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from app.config import (
    JOBS_DIR,
    SUPERTONIC_DEFAULT_SPEED,
    SUPERTONIC_SENTENCE_GAP_SECONDS,
    to_absolute_path,
    to_relative_path,
)
from app.constants import (
    PROJECT_STATUS_FAILED,
    PROJECT_STATUS_TTS_READY,
    TTS_ERR_NO_SCRIPT,
)
from app.db import repository as repo
from app.media.ffprobe_utils import probe_media
from app.tts import adapter
from app.tts.normalizer import build_normalized_units

USER_TTS_ERROR_MESSAGES = {
    "no_script": "먼저 SNS 8채널 생성을 완료해 영상 원고를 만들어야 합니다.",
    "empty_text": "정규화 후 남는 문장이 없습니다. 영상 원고를 확인해 주세요.",
    "engine_error": "음성 합성 엔진에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
    "empty_audio": "음성이 생성되지 않았습니다(빈 오디오). 다시 시도해 주세요.",
    "save_failed": "음성 파일 저장에 실패했습니다.",
}


def _voice_preference_for_sentence(sentence_index: int) -> str:
    """문장 인덱스로 여성·남성 음성을 교차 배정한다(0번=여성, 1번=남성, 2번=여성...).
    화면에는 음성 선택 UI가 없고 이 규칙만으로 항상 결정되므로, 최초 생성과 재시도(단일
    문장 재생성)가 항상 같은 결과를 내고 문장 순서만 알면 재현 가능하다."""
    return "female" if sentence_index % 2 == 0 else "male"


@dataclass
class TtsOutcome:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    total_sentences: int = 0
    success_sentences: int = 0
    failed_sentences: int = 0


def _job_tts_dir(job_uid: str) -> Path:
    d = JOBS_DIR / job_uid / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sentence_wav_path(job_uid: str, sentence_index: int) -> Path:
    return _job_tts_dir(job_uid) / f"sentence_{sentence_index:03d}.wav"


def _master_wav_path(job_uid: str) -> Path:
    return _job_tts_dir(job_uid) / "full.wav"


def _read_wav_as_row(path: Path) -> np.ndarray:
    data, _sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    else:
        data = data.T[:1, :]
    return data


def _rebuild_master(project: dict, job_uid: str) -> bool:
    """모든 문장이 success인 경우에만 디스크의 문장별 wav를 다시 읽어 전체 음성을 조립한다."""
    project_id = project["id"]
    rows = repo.list_tts_sentences_for_project(project_id)
    if not rows or any(r["status"] != "success" for r in rows):
        repo.upsert_tts_master(project_id, status="failed", error_code="incomplete_sentences")
        return False

    wavs = [_read_wav_as_row(to_absolute_path(r["relative_wav_path"])) for r in rows]

    sample_rate = adapter.get_sample_rate()
    full = adapter.concat_wavs(wavs, sample_rate, SUPERTONIC_SENTENCE_GAP_SECONDS)
    master_path = _master_wav_path(job_uid)
    adapter.save_wav(full, str(master_path))

    probe = probe_media(str(master_path))
    if not probe.ok:
        repo.upsert_tts_master(project_id, status="failed", error_code="save_failed")
        return False

    repo.upsert_tts_master(
        project_id, status="success", relative_wav_path=to_relative_path(master_path),
        total_duration_seconds=probe.duration_seconds, sentence_gap_seconds=SUPERTONIC_SENTENCE_GAP_SECONDS,
        voice="mixed_female_male",
    )
    return True


def generate_tts_for_project(project: dict) -> TtsOutcome:
    project_id = project["id"]
    job_uid = project["job_uid"]

    existing_master = repo.get_tts_master_for_project(project_id)
    if existing_master and existing_master["status"] == "success":
        # 이미 정상 산출물이 있으면 불필요하게 다시 만들지 않는다(작업지시 15장 지뢰 방지).
        rows = repo.list_tts_sentences_for_project(project_id)
        return TtsOutcome(ok=True, total_sentences=len(rows), success_sentences=len(rows), failed_sentences=0)

    video_script = repo.get_video_script_for_project(project_id)
    if not video_script or not video_script.get("scene_sentences_json"):
        return TtsOutcome(ok=False, error_code=TTS_ERR_NO_SCRIPT,
                           error_message=USER_TTS_ERROR_MESSAGES[TTS_ERR_NO_SCRIPT])

    import json
    scene_sentences = json.loads(video_script["scene_sentences_json"])
    units = build_normalized_units(scene_sentences)
    if not units:
        return TtsOutcome(ok=False, error_code="empty_text", error_message=USER_TTS_ERROR_MESSAGES["empty_text"])

    # 처음부터 다시 만드는 경우이므로 이전 산출 파일을 정리한다.
    tts_dir = _job_tts_dir(job_uid)
    shutil.rmtree(tts_dir, ignore_errors=True)
    tts_dir.mkdir(parents=True, exist_ok=True)

    plan = [
        {
            "sentence_index": i, "scene_index": u.scene_index, "original_text": u.original_text,
            "normalized_text": u.normalized_text,
            "voice": adapter.voice_name_for_preference(_voice_preference_for_sentence(i)),
            "speed": SUPERTONIC_DEFAULT_SPEED,
        }
        for i, u in enumerate(units)
    ]
    repo.replace_tts_sentences(project_id, plan)

    success_count = 0
    failed_count = 0
    for item in plan:
        idx = item["sentence_index"]
        result = adapter.synthesize_sentence(
            item["normalized_text"], _voice_preference_for_sentence(idx), item["speed"]
        )
        if not result.ok:
            repo.upsert_tts_sentence_result(project_id, idx, status="failed", error_code=result.error_code)
            failed_count += 1
            continue

        wav_path = _sentence_wav_path(job_uid, idx)
        adapter.save_wav(result.wav, str(wav_path))
        probe = probe_media(str(wav_path))
        if not probe.ok:
            repo.upsert_tts_sentence_result(project_id, idx, status="failed", error_code="save_failed")
            failed_count += 1
            continue

        repo.upsert_tts_sentence_result(
            project_id, idx, status="success",
            relative_wav_path=to_relative_path(wav_path), duration_seconds=probe.duration_seconds,
        )
        success_count += 1

    if failed_count == 0:
        _rebuild_master(project, job_uid)
        repo.update_project_status(project_id, PROJECT_STATUS_TTS_READY)
        return TtsOutcome(ok=True, total_sentences=len(plan), success_sentences=success_count, failed_sentences=0)

    repo.upsert_tts_master(project_id, status="failed", error_code="partial_failure")
    repo.update_project_status(project_id, PROJECT_STATUS_FAILED, error_code="tts_partial_failure")
    return TtsOutcome(
        ok=False, error_code="partial_failure",
        error_message=f"{failed_count}개 문장의 음성 생성에 실패했습니다. 실패한 문장만 다시 시도할 수 있습니다.",
        total_sentences=len(plan), success_sentences=success_count, failed_sentences=failed_count,
    )


def regenerate_tts_sentence(project: dict, sentence_index: int) -> TtsOutcome:
    project_id = project["id"]
    job_uid = project["job_uid"]

    rows = repo.list_tts_sentences_for_project(project_id)
    target = next((r for r in rows if r["sentence_index"] == sentence_index), None)
    if not target:
        return TtsOutcome(ok=False, error_code="not_found", error_message="해당 문장을 찾을 수 없습니다.")

    voice_preference = _voice_preference_for_sentence(sentence_index)
    result = adapter.synthesize_sentence(target["normalized_text"], voice_preference, target["speed"])
    if not result.ok:
        repo.upsert_tts_sentence_result(project_id, sentence_index, status="failed", error_code=result.error_code)
        return TtsOutcome(ok=False, error_code=result.error_code,
                           error_message=USER_TTS_ERROR_MESSAGES.get(result.error_code, "합성에 실패했습니다."))

    wav_path = _sentence_wav_path(job_uid, sentence_index)
    adapter.save_wav(result.wav, str(wav_path))
    probe = probe_media(str(wav_path))
    if not probe.ok:
        repo.upsert_tts_sentence_result(project_id, sentence_index, status="failed", error_code="save_failed")
        return TtsOutcome(ok=False, error_code="save_failed", error_message=USER_TTS_ERROR_MESSAGES["save_failed"])

    repo.upsert_tts_sentence_result(
        project_id, sentence_index, status="success",
        relative_wav_path=to_relative_path(wav_path), duration_seconds=probe.duration_seconds,
    )

    all_rows = repo.list_tts_sentences_for_project(project_id)
    if all(r["status"] == "success" for r in all_rows):
        _rebuild_master(project, job_uid)
        repo.update_project_status(project_id, PROJECT_STATUS_TTS_READY)

    return TtsOutcome(ok=True, total_sentences=len(all_rows),
                       success_sentences=sum(1 for r in all_rows if r["status"] == "success"),
                       failed_sentences=sum(1 for r in all_rows if r["status"] == "failed"))
