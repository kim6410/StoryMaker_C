# -*- coding: utf-8 -*-
"""
단계8: TTS 문장 타임라인을 MP4 장면 목록으로 변환한다.

장면 경계는 음성 문장 경계와 맞춘다(작업지시 8장). 각 장면은 그 문장의 실제
발화 시간과 다음 문장까지의 무음 간격을 포함하고, 첫 장면은 배경음악 페이드인
시간만큼, 마지막 장면은 엔딩 유지 시간만큼 앞뒤로 늘어난다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import MP4_END_HOLD_SECONDS, MP4_START_LEAD_SECONDS
from app.subtitle.srt_builder import parse_srt, srt_timestamp_to_seconds

_PALETTE = [
    ("0x1b2a4a", "0x3a5a8c"),
    ("0x2a1b4a", "0x8c3a5a"),
    ("0x1b4a3a", "0x3a8c5a"),
    ("0x4a3a1b", "0x8c6a3a"),
    ("0x1b3a4a", "0x3a6a8c"),
    ("0x3a1b4a", "0x8c3a8c"),
]


@dataclass
class SceneSpec:
    scene_index: int
    sentence_index: int
    caption: str
    start_seconds: float           # 최종 영상 타임라인에서 이 장면 '내용'이 시작되는 시각
    duration_seconds: float        # 장면 내용 길이(리드인·엔딩 유지 시간 포함, 전환용 여유는 미포함)
    caption_start_local: float     # 이 장면 클립 내부 기준 자막 표시 시작
    caption_end_local: float
    zoom_type: str
    zoom_start: float
    zoom_end: float
    transition_in_seconds: float   # 이전 장면에서 이 장면으로 넘어오는 전환 길이(첫 장면은 0)
    color0: str
    color1: str


def _zoom_pattern(index: int, duration: float) -> tuple[str, float, float]:
    """2개 움직임 장면 뒤 정지 장면 1개, 같은 효과 3회 연속 금지, 짧은 장면엔 강한 줌 금지."""
    if duration < 3.0:
        return "static", 1.015, 1.015
    cycle = index % 3
    if cycle == 0:
        return "zoom_in", 1.02, 1.10
    if cycle == 1:
        return "zoom_out", 1.10, 1.02
    return "static", 1.03, 1.03


def _transition_seconds(prev_duration: float, this_duration: float) -> float:
    def base_for(d: float) -> float:
        if d >= 6:
            return 2.5
        if d >= 4:
            return 1.8
        if d >= 3:
            return 1.2
        return 0.6

    t = min(base_for(prev_duration), base_for(this_duration))
    return round(min(t, prev_duration / 2, this_duration / 2), 3)


def build_scene_plan(srt_path: Path, master_total_duration: float, sentence_rows: list[dict]) -> list[SceneSpec]:
    cues = parse_srt(srt_path)
    if len(cues) != len(sentence_rows):
        raise ValueError(f"cue count {len(cues)} != sentence count {len(sentence_rows)}")

    n = len(cues)
    scenes: list[SceneSpec] = []
    cumulative_content = 0.0

    for i, (cue, srow) in enumerate(zip(cues, sentence_rows)):
        cue_start = srt_timestamp_to_seconds(cue["start"])
        speech_duration = float(srow["duration_seconds"])
        next_start = srt_timestamp_to_seconds(cues[i + 1]["start"]) if i + 1 < n else master_total_duration
        content_duration = next_start - cue_start

        caption_start_local = 0.0
        caption_end_local = speech_duration
        if i == 0:
            content_duration += MP4_START_LEAD_SECONDS
            caption_start_local += MP4_START_LEAD_SECONDS
            caption_end_local += MP4_START_LEAD_SECONDS
        if i == n - 1:
            content_duration += MP4_END_HOLD_SECONDS

        zoom_type, zoom_start, zoom_end = _zoom_pattern(i, content_duration)
        color0, color1 = _PALETTE[i % len(_PALETTE)]
        transition_in = 0.0 if i == 0 else _transition_seconds(scenes[-1].duration_seconds, content_duration)

        scenes.append(SceneSpec(
            scene_index=i, sentence_index=int(srow["sentence_index"]),
            caption=cue["text"].replace("\n", " ").strip(),
            start_seconds=round(cumulative_content, 3), duration_seconds=round(content_duration, 3),
            caption_start_local=round(caption_start_local, 3), caption_end_local=round(caption_end_local, 3),
            zoom_type=zoom_type, zoom_start=zoom_start, zoom_end=zoom_end,
            transition_in_seconds=transition_in, color0=color0, color1=color1,
        ))
        cumulative_content += content_duration

    return scenes


def total_plan_duration(scenes: list[SceneSpec]) -> float:
    return sum(s.duration_seconds for s in scenes)
