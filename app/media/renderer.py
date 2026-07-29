# -*- coding: utf-8 -*-
"""
단계8: FFmpeg 렌더 Adapter. 외부 실행 파일(FFmpeg) 호출은 이 모듈만 담당한다.
프로젝트 전용 FFmpeg(runtime/ffmpeg)와 프로젝트 전용 폰트(runtime/fonts)만 사용한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import (
    FFMPEG_PATH,
    FONT_BOLD_PATH,
    FONT_REGULAR_PATH,
    MP4_FPS,
    MP4_HEIGHT,
    MP4_WIDTH,
    MUSIC_DUCKED_VOLUME,
    MUSIC_SOLO_VOLUME,
    PROJECT_ROOT,
)
from app.media.scene_planner import SceneSpec


def _to_posix_rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _run_ffmpeg(args: list[str], timeout: int = 180) -> tuple[bool, str]:
    cmd = [str(FFMPEG_PATH), "-y", "-hide_banner", "-loglevel", "error"] + args
    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timeout"
    except OSError as exc:
        return False, f"ffmpeg exec failed: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or "")[-2000:]
    return True, ""


def _zoom_expr(zoom_start: float, zoom_end: float, frames: int) -> str:
    frames = max(frames, 2)
    if abs(zoom_end - zoom_start) < 1e-9:
        return f"if(eq(on,0),{zoom_start},{zoom_start})"
    if zoom_end > zoom_start:
        step = (zoom_end - zoom_start) / (frames - 1)
        return f"if(eq(on,0),{zoom_start},min(zoom+{step:.6f},{zoom_end}))"
    step = (zoom_start - zoom_end) / (frames - 1)
    return f"if(eq(on,0),{zoom_start},max(zoom-{step:.6f},{zoom_end}))"


def generate_scene_clip(spec: SceneSpec, render_duration: float, out_path: Path, texts_dir: Path,
                         company_name: str, phone_number: str) -> tuple[bool, str]:
    """장면 하나를 독립 mp4 클립으로 렌더링한다(배경 + Ken Burns 줌 + 상호·전화번호·자막).
    spec.image_path가 있으면 그 사진을(9:16으로 채워 자르기), 없으면 기존과 동일한
    그라디언트를 배경으로 쓴다."""
    texts_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    caption_file = texts_dir / f"caption_{spec.scene_index:03d}.txt"
    caption_file.write_text(spec.caption or " ", encoding="utf-8")
    company_file = texts_dir / "company.txt"
    company_file.write_text(company_name or " ", encoding="utf-8")
    phone_file = texts_dir / "phone.txt"
    phone_file.write_text(phone_number or " ", encoding="utf-8")

    use_image = bool(spec.image_path and spec.image_path.is_file())
    bg_png: Path | None = None
    if use_image:
        bg_rel = _to_posix_rel(spec.image_path)
        scale_step = (
            f"scale={MP4_WIDTH}:{MP4_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={MP4_WIDTH}:{MP4_HEIGHT}"
        )
    else:
        bg_png = texts_dir.parent / f"scene_{spec.scene_index:03d}_bg.png"
        grad_args = [
            "-f", "lavfi", "-i",
            f"gradients=s={MP4_WIDTH}x{MP4_HEIGHT}:c0={spec.color0}:c1={spec.color1}:"
            f"x0=120:y0=90:x1={MP4_WIDTH - 120}:y1={MP4_HEIGHT - 90}:nb_colors=2",
            "-frames:v", "1", "-update", "1", str(bg_png),
        ]
        ok, err = _run_ffmpeg(grad_args, timeout=30)
        if not ok:
            return False, f"gradient_failed: {err}"
        bg_rel = _to_posix_rel(bg_png)
        scale_step = f"scale={MP4_WIDTH}:{MP4_HEIGHT}"

    frames = max(1, round(render_duration * MP4_FPS))
    zoom_expr = _zoom_expr(spec.zoom_start, spec.zoom_end, frames)
    fade_dur = min(0.3, render_duration / 4)
    fade_out_start = max(0.0, render_duration - fade_dur)

    font_regular_rel = _to_posix_rel(FONT_REGULAR_PATH)
    font_bold_rel = _to_posix_rel(FONT_BOLD_PATH)
    caption_rel = _to_posix_rel(caption_file)
    company_rel = _to_posix_rel(company_file)
    phone_rel = _to_posix_rel(phone_file)

    vf_parts = [
        scale_step,
        (
            f"zoompan=z='{zoom_expr}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={MP4_WIDTH}x{MP4_HEIGHT}:fps={MP4_FPS}"
        ),
        # 상호: 좌측 상단, 전화번호: 우측 상단 (자막과 겹치지 않고, 마지막까지 항상 표시)
        f"drawtext=fontfile='{font_bold_rel}':textfile='{company_rel}':fontcolor=white:fontsize=34:"
        f"x=44:y=56:box=1:boxcolor=black@0.35:boxborderw=10",
        f"drawtext=fontfile='{font_regular_rel}':textfile='{phone_rel}':fontcolor=white:fontsize=30:"
        f"x=w-text_w-44:y=56:box=1:boxcolor=black@0.35:boxborderw=10",
    ]
    if spec.caption_end_local > spec.caption_start_local:
        vf_parts.append(
            f"drawtext=fontfile='{font_regular_rel}':textfile='{caption_rel}':fontcolor=white:fontsize=38:"
            f"line_spacing=8:x=(w-text_w)/2:y=h-260:box=1:boxcolor=black@0.5:boxborderw=18:"
            f"enable='between(t,{spec.caption_start_local:.3f},{spec.caption_end_local:.3f})'"
        )
    vf_parts.append(f"fade=t=in:st=0:d={fade_dur:.3f}")
    vf_parts.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_dur:.3f}")

    render_args = [
        "-loop", "1", "-i", bg_rel,
        "-vf", ",".join(vf_parts), "-t", f"{render_duration:.3f}",
        "-r", str(MP4_FPS), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        _to_posix_rel(out_path),
    ]
    ok, err = _run_ffmpeg(render_args, timeout=120)
    if bg_png is not None:
        bg_png.unlink(missing_ok=True)
    if not ok:
        return False, f"scene_render_failed: {err}"
    return True, ""


def concat_scenes_with_transitions(clip_paths: list[Path], render_durations: list[float],
                                    transitions: list[float], out_path: Path) -> tuple[bool, str]:
    """xfade 체인으로 장면을 자연스럽게 이어붙인다(기본 크로스디졸브, 짧은 장면은 자동 축소)."""
    n = len(clip_paths)
    if n == 0:
        return False, "no_clips"
    if n == 1:
        args = ["-i", _to_posix_rel(clip_paths[0]), "-c", "copy", _to_posix_rel(out_path)]
        return _run_ffmpeg(args, timeout=60)

    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", _to_posix_rel(p)]

    filter_parts = []
    cumulative = render_durations[0]
    prev_label = "0:v"
    for i in range(1, n):
        t = transitions[i]
        offset = cumulative - t
        out_label = f"v{i}" if i < n - 1 else "vout"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:duration={t:.3f}:offset={offset:.3f}[{out_label}]"
        )
        cumulative = cumulative + render_durations[i] - t
        prev_label = out_label

    filter_complex = ";".join(filter_parts)
    args = inputs + ["-filter_complex", filter_complex, "-map", f"[{prev_label}]",
                      "-r", str(MP4_FPS), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                      _to_posix_rel(out_path)]
    ok, err = _run_ffmpeg(args, timeout=300)
    if not ok:
        return False, f"concat_failed: {err}"
    return True, ""


def build_final_audio(tts_master_path: Path, music_path: Path | None, total_duration: float,
                       volume_level: str, out_path: Path, start_lead: float, end_hold: float) -> tuple[bool, str]:
    """TTS 음성(리드인만큼 지연) + 배경음악(루프/트림, 페이드인·페이드아웃, 덕킹)을 혼합한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ducked = MUSIC_DUCKED_VOLUME.get(volume_level, MUSIC_DUCKED_VOLUME["normal"])
    delay_ms = int(round(start_lead * 1000))

    if music_path is None:
        args = [
            "-i", _to_posix_rel(tts_master_path),
            "-filter_complex", f"[0:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration:.3f}[aout]",
            "-map", "[aout]", "-t", f"{total_duration:.3f}", "-c:a", "pcm_s16le",
            _to_posix_rel(out_path),
        ]
        ok, err = _run_ffmpeg(args, timeout=120)
        return (ok, f"audio_mix_failed: {err}" if not ok else "")

    fade_out_start = max(0.0, total_duration - end_hold)
    args = [
        "-i", _to_posix_rel(tts_master_path),
        "-stream_loop", "-1", "-i", _to_posix_rel(music_path),
        "-filter_complex",
        (
            f"[0:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={total_duration:.3f}[voice];"
            f"[1:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,volume={ducked:.3f},"
            f"afade=t=in:st=0:d={start_lead:.3f},afade=t=out:st={fade_out_start:.3f}:d={end_hold:.3f}[music];"
            f"[voice][music]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
        ),
        "-map", "[aout]", "-t", f"{total_duration:.3f}", "-c:a", "pcm_s16le",
        _to_posix_rel(out_path),
    ]
    ok, err = _run_ffmpeg(args, timeout=120)
    return (ok, f"audio_mix_failed: {err}" if not ok else "")


def extract_frame_at(video_path: Path, timestamp_seconds: float, out_path: Path,
                      width: int = MP4_WIDTH, height: int = MP4_HEIGHT) -> tuple[bool, str]:
    """완성된 MP4에서 지정 시각의 프레임 1장을 JPEG로 추출한다(썸네일 후보용)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-ss", f"{max(timestamp_seconds, 0.0):.3f}", "-i", _to_posix_rel(video_path),
        "-frames:v", "1", "-vf", f"scale={width}:{height}", "-q:v", "3",
        _to_posix_rel(out_path),
    ]
    ok, err = _run_ffmpeg(args, timeout=30)
    if not ok:
        return False, f"thumbnail_extract_failed: {err}"
    return True, ""


def extract_thumbnail_candidate(video_path: Path, timestamp_seconds: float, out_path: Path,
                                 texts_dir: Path, index: int, headline: str,
                                 width: int = MP4_WIDTH, height: int = MP4_HEIGHT) -> tuple[bool, str]:
    """단계11 보완: 프레임만 뽑던 것에서 나아가, 배경을 살짝 어둡게 하고 굵은 헤드라인을
    검정 외곽선과 함께 얹는다(사진 위에서도 읽히게 하는 원칙은 V1·Beta의 문서화된 방식을
    참고: 굵은 글씨 + 검정 외곽선/그림자). 후보 8장은 같은 스타일이고 추출 시점(=영상
    속 서로 다른 장면)만 다르다 - 실제로 존재가 확인되지 않는 "8종 서로 다른 레이아웃"을
    지어내지 않고, 검증 가능한 원칙만 재구현했다."""
    texts_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headline_file = texts_dir / f"thumb_headline_{index}.txt"
    headline_file.write_text(headline or " ", encoding="utf-8")

    font_bold_rel = _to_posix_rel(FONT_BOLD_PATH)
    headline_rel = _to_posix_rel(headline_file)

    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "eq=brightness=-0.08:saturation=1.05",
    ]
    if (headline or "").strip():
        vf_parts.append(
            f"drawtext=fontfile='{font_bold_rel}':textfile='{headline_rel}':fontcolor=white:fontsize=52:"
            f"line_spacing=12:x=(w-text_w)/2:y=190:borderw=6:bordercolor=black@0.9:"
            f"box=1:boxcolor=black@0.32:boxborderw=22"
        )

    args = [
        "-ss", f"{max(timestamp_seconds, 0.0):.3f}", "-i", _to_posix_rel(video_path),
        "-frames:v", "1", "-vf", ",".join(vf_parts), "-q:v", "3",
        _to_posix_rel(out_path),
    ]
    ok, err = _run_ffmpeg(args, timeout=30)
    if not ok:
        return False, f"thumbnail_extract_failed: {err}"
    return True, ""


def mux_final(video_path: Path, audio_path: Path, out_path: Path) -> tuple[bool, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-i", _to_posix_rel(video_path), "-i", _to_posix_rel(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(MP4_FPS),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        "-shortest", _to_posix_rel(out_path),
    ]
    ok, err = _run_ffmpeg(args, timeout=300)
    if not ok:
        return False, f"mux_failed: {err}"
    return True, ""
