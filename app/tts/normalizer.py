# -*- coding: utf-8 -*-
"""
단계7: 영상 원고를 TTS가 자연스럽게 읽을 수 있는 형태로 정규화한다.

원본 문장(자막 표시용, 화자 표시만 제거)과 TTS용 정규화 문장(숫자·전화번호·기호를
읽는 그대로 풀어씀)을 분리해서 반환한다. 어느 쪽도 서로를 덮어쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SPEAKER_TAG_RE = re.compile(r"\[[^\[\]]{1,12}\]")
_PHONE_RE = re.compile(r"(?<!\d)(0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4})(?!\d)")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_MAX_SENTENCE_LEN = 80

_DIGIT_KO = {"0": "공", "1": "일", "2": "이", "3": "삼", "4": "사",
             "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구"}

_SMALL_UNITS = ["", "십", "백", "천"]
_BIG_UNITS = ["", "만", "억", "조"]
_SINO_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]

_SYMBOL_READINGS = {
    "%": "퍼센트",
    "℃": "도씨",
    "&": "그리고",
    "@": "골뱅이",
    "+": "플러스",
}


def strip_speaker_tags(text: str) -> str:
    """자막·TTS 어디에도 [여성]/[남성] 같은 화자 표시가 남지 않도록 제거한다(작업지시 7장)."""
    return _SPEAKER_TAG_RE.sub("", text).strip()


def _read_phone_digits(match: re.Match) -> str:
    digits = re.sub(r"[-\s]", "", match.group(0))
    return " ".join(_DIGIT_KO[d] for d in digits)


def _read_group_of_four(n: int) -> str:
    """0~9999 사이 숫자를 한자어(Sino-Korean) 숫자 읽기로 변환한다."""
    if n == 0:
        return ""
    out = []
    s = str(n).zfill(4)
    for i, ch in enumerate(s):
        d = int(ch)
        unit = _SMALL_UNITS[3 - i]
        if d == 0:
            continue
        digit_str = "" if d == 1 and unit else _SINO_DIGITS[d]
        out.append(digit_str + unit)
    return "".join(out)


def _read_integer_ko(n: int) -> str:
    if n == 0:
        return "영"
    negative = n < 0
    n = abs(n)
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        parts.append(_read_group_of_four(g) + _BIG_UNITS[i])
    result = "".join(parts) or "영"
    return ("마이너스 " + result) if negative else result


def _read_number(match: re.Match) -> str:
    raw = match.group(0)
    if "." in raw:
        whole, frac = raw.split(".", 1)
        whole_read = _read_integer_ko(int(whole)) if whole else "영"
        frac_read = " ".join(_DIGIT_KO[d] for d in frac)
        return f"{whole_read} 쩜 {frac_read}"
    n = int(raw)
    # 너무 큰 수는 자릿수 읽기가 부자연스러워지므로 조 단위(약 1000조) 이상은 자리수 그대로 둔다.
    if n >= 10 ** 15:
        return raw
    return _read_integer_ko(n)


def _read_symbols(text: str) -> str:
    for symbol, reading in _SYMBOL_READINGS.items():
        text = text.replace(symbol, reading)
    return text


def normalize_for_tts(text: str) -> str:
    """TTS 엔진에 넣을 문장을 만든다: 화자표시 제거 -> 전화번호 자리읽기 -> 숫자 읽기 -> 기호 읽기."""
    text = strip_speaker_tags(text)
    text = _PHONE_RE.sub(_read_phone_digits, text)
    text = _NUMBER_RE.sub(_read_number, text)
    text = _read_symbols(text)
    return re.sub(r"\s+", " ", text).strip()


def clean_for_caption(text: str) -> str:
    """자막(SRT)에 표시할 원문. 화자 표시만 제거하고 숫자·전화번호는 원래 표기를 유지한다."""
    return re.sub(r"\s+", " ", strip_speaker_tags(text)).strip()


_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+")


def split_long_sentence(text: str, max_len: int = _MAX_SENTENCE_LEN) -> list[str]:
    """지나치게 긴 문장을 문장부호 기준으로 분할한다. 분할해도 여전히 길면 쉼표로 한 번 더 나눈다."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    parts = [p.strip() for p in _SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) <= 1:
        # 그래도 못 나누면 글자 수 기준으로 강제 절단한다(마지막 안전장치).
        parts = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    result: list[str] = []
    for p in parts:
        if len(p) > max_len:
            result.extend(split_long_sentence(p, max_len))
        else:
            result.append(p)
    return result


@dataclass
class NormalizedUnit:
    scene_index: int
    original_text: str
    normalized_text: str


def build_normalized_units(scene_sentences: list[str]) -> list[NormalizedUnit]:
    """숏폼 영상원고의 장면 문장 목록을 받아, 빈 문장을 제거하고 긴 문장은 나눠서
    (원본 자막용 텍스트, TTS용 정규화 텍스트) 쌍의 목록으로 만든다."""
    units: list[NormalizedUnit] = []
    for scene_index, raw in enumerate(scene_sentences):
        caption_full = clean_for_caption(raw)
        if not caption_full:
            continue
        for chunk in split_long_sentence(caption_full):
            if not chunk.strip():
                continue
            units.append(NormalizedUnit(
                scene_index=scene_index,
                original_text=chunk.strip(),
                normalized_text=normalize_for_tts(chunk.strip()),
            ))
    return units
