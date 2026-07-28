# -*- coding: utf-8 -*-
"""
HTTP Range 요청을 지원하는 파일 스트리밍 응답.

설치된 Starlette 0.38.6의 FileResponse는 Range 헤더를 전혀 처리하지 않는다(실제 확인:
요청에 Range를 넣어도 매번 200 + 전체 바이트를 돌려줌). 브라우저 <video>/<audio> 태그는
탐색(seek)과 초기 재생 판단에 Range 응답(206 Partial Content)을 사용하므로, 이 헬퍼 없이는
자체 제작한 TTS/MP4 스트리밍이 일부 브라우저에서 로딩이 멈출 수 있다(단계9 검증 중 실제로
Chrome에서 재현·확인함)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK_SIZE = 1024 * 1024


def range_file_response(request: Request, path: Path, media_type: str,
                         filename: Optional[str] = None) -> Response:
    file_size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes"}
    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'

    range_header = request.headers.get("range")
    if not range_header:
        def full_iter():
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        headers["Content-Length"] = str(file_size)
        return StreamingResponse(full_iter(), status_code=200, media_type=media_type, headers=headers)

    match = _RANGE_RE.match(range_header.strip())
    if not match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start_str, end_str = match.groups()
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    length = end - start + 1

    def ranged_iter():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    headers["Content-Length"] = str(length)
    return StreamingResponse(ranged_iter(), status_code=206, media_type=media_type, headers=headers)
