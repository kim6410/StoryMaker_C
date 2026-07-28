# -*- coding: utf-8 -*-
"""
단계7: Supertonic TTS Adapter.

StoryMaker_C 전용 독립 설치(`pip install supertonic`, 모델은 이 프로젝트 캐시 경로로만
다운로드)만 사용하고, 기존 V1·Beta의 실행 중인 Supertonic 서비스에는 전혀 의존하지 않는다.
외부 서비스 호출(모델 로딩·추론)은 이 모듈만 담당한다(작업지시 3장, Adapter 계층 원칙).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.config import (
    SUPERTONIC_DEFAULT_SPEED,
    SUPERTONIC_MODEL_DIR,
    SUPERTONIC_VOICE_FEMALE,
    SUPERTONIC_VOICE_MALE,
)
from app.constants import TTS_ERR_EMPTY_AUDIO, TTS_ERR_EMPTY_TEXT, TTS_ERR_ENGINE_ERROR, TTS_MAX_RETRIES

_lock = threading.Lock()
_tts_instance = None
_voice_style_cache: dict[str, object] = {}


def _get_tts():
    global _tts_instance
    if _tts_instance is None:
        with _lock:
            if _tts_instance is None:
                from supertonic import TTS
                SUPERTONIC_MODEL_DIR.mkdir(parents=True, exist_ok=True)
                _tts_instance = TTS(model_dir=SUPERTONIC_MODEL_DIR, auto_download=True)
    return _tts_instance


def voice_name_for_preference(voice_preference: str) -> str:
    return SUPERTONIC_VOICE_MALE if (voice_preference or "").strip() == "male" else SUPERTONIC_VOICE_FEMALE


def _get_voice_style(voice_name: str):
    if voice_name not in _voice_style_cache:
        tts = _get_tts()
        _voice_style_cache[voice_name] = tts.get_voice_style(voice_name=voice_name)
    return _voice_style_cache[voice_name]


@dataclass
class TtsSynthesisResult:
    ok: bool
    wav: Optional[np.ndarray] = None
    duration_seconds: float = 0.0
    error_code: str = ""
    retry_count: int = 0
    latency_ms: int = 0


def _single_attempt(text: str, voice_name: str, speed: float) -> tuple[bool, Optional[np.ndarray], float, str]:
    try:
        tts = _get_tts()
        style = _get_voice_style(voice_name)
        wav, dur = tts.synthesize(text, voice_style=style, lang="ko", speed=speed)
    except Exception:
        return False, None, 0.0, TTS_ERR_ENGINE_ERROR

    if wav is None or wav.size == 0:
        return False, None, 0.0, TTS_ERR_EMPTY_AUDIO
    duration = float(dur[0]) if hasattr(dur, "__len__") else float(dur)
    if duration <= 0:
        return False, None, 0.0, TTS_ERR_EMPTY_AUDIO
    return True, wav, duration, ""


def synthesize_sentence(text: str, voice_preference: str = "female",
                         speed: float = SUPERTONIC_DEFAULT_SPEED) -> TtsSynthesisResult:
    """문장 하나를 합성한다. timeout/네트워크 개념이 없는 로컬 추론이므로 엔진 예외만
    분류하고, 제한적으로만 재시도한다(무한 재시도 금지, 작업지시 8장)."""
    started = time.monotonic()
    if not text or not text.strip():
        return TtsSynthesisResult(ok=False, error_code=TTS_ERR_EMPTY_TEXT, latency_ms=0)

    voice_name = voice_name_for_preference(voice_preference)
    retry_count = 0
    last_error = TTS_ERR_ENGINE_ERROR
    while True:
        ok, wav, duration, error_code = _single_attempt(text, voice_name, speed)
        if ok:
            return TtsSynthesisResult(
                ok=True, wav=wav, duration_seconds=duration, retry_count=retry_count,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        last_error = error_code
        if retry_count >= TTS_MAX_RETRIES:
            break
        retry_count += 1

    return TtsSynthesisResult(
        ok=False, error_code=last_error, retry_count=retry_count,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def save_wav(wav: np.ndarray, output_path: str) -> None:
    tts = _get_tts()
    tts.save_audio(wav, output_path)


def concat_wavs(wavs: list[np.ndarray], sample_rate: int, gap_seconds: float) -> np.ndarray:
    """문장별 wav를 무음 간격을 두고 이어붙인다(전체 합성 음성 산출용)."""
    if not wavs:
        return np.zeros((1, 0), dtype=np.float32)
    silence = np.zeros((1, int(gap_seconds * sample_rate)), dtype=np.float32)
    arrays = []
    for i, w in enumerate(wavs):
        arrays.append(w)
        if i < len(wavs) - 1:
            arrays.append(silence)
    return np.concatenate(arrays, axis=1)


def get_sample_rate() -> int:
    return int(_get_tts().sample_rate)
