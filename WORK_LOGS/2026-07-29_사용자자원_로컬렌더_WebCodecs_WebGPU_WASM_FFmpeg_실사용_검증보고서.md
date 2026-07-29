# 2026-07-29 사용자자원 로컬렌더 WebCodecs·WebGPU·WASM·FFmpeg 실사용 검증보고서

작성일시: 2026-07-29
대상 요청서: `WORK_LOGS/Claude_최우선_사용자자원_렌더링_실사용검증_서버부하최소화_요청서_0729.md`
범위: 요청서 1~4단계(정적 조사, 진단 로깅·동시성 제한 구현, 8033 단일 실행 런타임 검증,
동시 사용자 부하 테스트)를 완료. 관련 커밋: `f70fcc7`(1~2단계), 이 보고서와 함께 커밋되는
변경 없음(3~4단계는 코드 수정 없이 검증만 수행).

## 1. 조사 요약

`F:\StoryMaker_C\app\static\js\render-capabilities.js`,
`local-render-controller.js`, `local-renderer-worker.js`, `app\media\renderer.py`,
`app\media\service.py`, `app\db\migrations.py`를 직접 열람하고, 8033 테스트 서버에서 실제
HTTP 요청으로 TTS·MP4 렌더 파이프라인을 1회 및 5회 동시 실행해 실측했다.

**중요한 한계(사용자 지적 반영):** 아래 검증은 서버 폴백 경로(FFmpeg)는 실제 프로세스
실행까지 실측했지만, 브라우저 로컬 렌더 경로(WebGPU 진단, WebCodecs 인코딩)는 실제 Chrome을
열어 눈으로 확인하지 않았다. **"WebGPU·WebCodecs가 실제 Chrome 렌더링에 쓰였다"는 최종
증명은 이 보고서만으로는 부족하며, 별도의 실제 브라우저 E2E가 필요하다.** 이 문서의
WebGPU/WebCodecs 판정은 코드 정독(1단계)에 근거한 것이지 브라우저 실행 실측이 아니다 -
9장·17장에 동일하게 명시했다.

## 2. 최종 판정

| 기술 | 지원 여부 진단 | 실제 렌더링 사용 | 근거 |
|---|---|---|---|
| Web Worker | 확인 | 확인(코드 근거) | `local-render-controller.js`가 `new Worker("/static/js/local-renderer-worker.js")`로 실제 생성 |
| Canvas 2D / OffscreenCanvas | 확인 | 확인(코드 근거) | `local-renderer-worker.js`의 `renderVideoTrack()`이 `drawImage`/`fillRect`로 매 프레임 합성 |
| WebCodecs VideoEncoder/AudioEncoder | 확인(진단 코드가 실제 시험 인코딩까지 수행) | **코드 근거로는 확인, 브라우저 실측은 미검증** | `render-capabilities.js`는 진단 단계에서도 실제 소형 프레임 인코딩을 시도, `local-renderer-worker.js`가 실제 프레임·오디오 인코딩 호출부를 갖고 있음. 다만 실제 Chrome에서 끝까지 성공하는지는 이번 세션에서 실행하지 않음 |
| WebGPU | 확인(`requestAdapter`→`requestDevice`→렌더패스까지 실제 실행하는 진단 코드) | **미사용(코드 근거로 확정적 판정 - 브라우저 실측 불필요한 부정 판정)** | `render-capabilities.js`의 `detectWebGPU()`는 진짜 GPU 초기화까지 하지만, 결과(`webgpu.supported`)가 `localRenderReady` 판정식과 실제 프레임 렌더링 코드 어디에도 등장하지 않음(전체 코드베이스에 WebGPU 렌더 파이프라인 자체가 없음) - "쓰는 코드가 아예 없다"는 정적 사실이므로 브라우저로 실행해봐도 결과가 달라지지 않음 |
| WASM | 확인(`typeof WebAssembly` 진단만, 이번에 추가) | 미사용(코드 근거로 확정) | 프로젝트 전체에 `.wasm` 파일 없음, `mp4-muxer.min.js`(32KB, 순수 JS)에 `WebAssembly` 문자열 0건 |
| FFmpeg | - | **서버 폴백 경로 전용, 실측 확인** (예외 1건, 6-3 참고) | `generate_mp4_for_project()`만 전체 인코딩에 FFmpeg 사용 - 8033 실제 요청으로 프로세스 존재/개수까지 실측 |

WebGPU·WASM은 "코드에 사용 경로 자체가 없다"는 정적 사실이라 브라우저로 실행해도 결론이
바뀌지 않는 성격의 판정이다. 반면 WebCodecs는 "코드는 있지만 실제 브라우저 환경(GPU 드라이버,
Chrome 버전, 코덱 지원)에서 끝까지 성공하는지"는 정적 조사로 알 수 없는 별도의 질문이라
사용자가 지적한 대로 실제 브라우저 E2E가 필요하다.

## 3. 실제 렌더 구조

```text
[정상 로컬 렌더]
브라우저 클릭
→ render-capabilities.js: WebGPU/WebCodecs/Worker 실제 진단
→ local-render-controller.js: /render-manifest.json GET, TTS/음악 오디오 fetch+decode
→ Worker(local-renderer-worker.js) 생성, manifest+오디오 샘플 postMessage
→ Worker: OffscreenCanvas로 프레임 합성(그라디언트 또는 업로드 이미지)
→ VideoEncoder.encode() 실제 호출(WebCodecs)
→ AudioEncoder.encode() 실제 호출(WebCodecs)
→ Mp4Muxer(순수 JS, WASM 아님)로 최종 MP4 Blob 조립
→ POST /content/job/{uid}/mp4/upload-local 로 완성 MP4만 서버 업로드
→ 서버(accept_local_render_upload)가 코덱·길이만 ffprobe로 재검증 후 저장(FFmpeg 인코딩 없음)

[서버 폴백]
로컬 실패/미지원/시간초과
→ POST /content/job/{uid}/mp4/generate
→ generate_mp4_for_project(): 장면별 FFmpeg 렌더 → xfade 컨캣 → 오디오 믹스(FFmpeg) → 최종 mux(FFmpeg)
→ 완료 후 _log_server_ffmpeg_diagnostics()가 소요시간을 content_render_diagnostics에 기록(이번에 추가)
```

## 4. 파일·함수·행 번호 근거 (1단계 정적 조사에서 확인, 요약)

- `app/static/js/render-capabilities.js` `detectWebGPU()`/`detectWebCodecs()`: 실제 GPU·인코더 시험
- `app/static/js/local-render-controller.js` `startLocalRender()`/`finishWithFallback()`: 로컬↔서버 분기
- `app/static/js/local-renderer-worker.js` `renderVideoTrack()`/`renderAudioTrack()`: 실제 인코딩 루프
- `app/media/renderer.py` `_run_ffmpeg()`: 유일한 FFmpeg 실행 지점(세마포어 적용 지점)
- `app/media/service.py` `generate_mp4_for_project()`: 서버 폴백 전체 파이프라인, `_resolve_scene_images()`: 영상 미디어 대표 프레임 추출 시 FFmpeg 1회 호출(로컬 경로에서도 발생하는 유일한 예외)

## 5. WebGPU 실사용 판정

**미사용.** `localRenderReady = webcodecsVideo.supported && audio.supported && worker && offscreenCanvas`
식에 `webgpu`가 포함되지 않고, 프레임 합성은 전부 Canvas 2D API(`drawImage`, `fillRect`,
`createLinearGradient`)로만 이루어진다. UI 표기(`admin_diagnostics.html`)는 "WebGPU 지원
브라우저"로 정직하게 표시 중이라 과장 표시는 없다. 이 판정은 코드에 WebGPU 렌더 경로 자체가
없다는 정적 사실에 근거하므로, 실제 브라우저로 재현해도 결론은 바뀌지 않는다.

## 6. WASM 실사용 판정

**미사용.** 요청서 지시에 따라 이번에 `wasm_supported` 진단 필드를 추가했으나(2단계),
이는 `typeof WebAssembly !== "undefined"`라는 지원 여부 확인일 뿐이며, 실제 사용 코드는
프로젝트 어디에도 없다.

## 7. WebCodecs 실사용 판정

**코드 근거로는 확인, 실제 브라우저 실행 증명은 미검증(사용자 지적 사항).** 8033 실측에서는
서버 경로(FFmpeg)만 실제로 열어 확인했고, 브라우저 로컬 렌더 경로 자체는 이번 세션에서 실제
Chrome으로 열어보지 못했다. 코드 레벨에서는 실제 `VideoEncoder.encode()`/`AudioEncoder.encode()`
호출과 실제 프레임 데이터 전달이 확인되며, 진단 코드(`render-capabilities.js`)조차 지원
여부만 보지 않고 실제 소형 프레임을 인코딩해 성공 여부를 판정하도록 이미 견고하게 작성되어
있다. 하지만 이것은 "코드가 그렇게 되어 있다"는 근거이지 "실제 사용자 Chrome에서 매번
성공한다"는 증명이 아니다. 최종 증명에는 별도의 실제 브라우저 E2E가 필요하다.

## 8. FFmpeg 실행 위치와 조건

- 정상 로컬 렌더(이미지만 사용): 코드상 FFmpeg 호출 경로 없음(정적 확인). 브라우저를 직접
  열어 "로컬 렌더 중 ffmpeg.exe가 뜨지 않는다"를 실측 재현하지는 않았다.
- 서버 폴백: 장면 렌더·컨캣·오디오 믹스·최종 mux 전부 FFmpeg. **실측: 단일 요청당 ffmpeg.exe
  프로세스 최대 1개.**
- 예외: 사용자가 "영상"을 미디어로 선택하면 로컬/서버 관계없이 대표 프레임 추출 1회에
  한해 FFmpeg 호출(이번 테스트는 이미지 없는 텍스트 전용 시나리오라 이 경로는 재현하지 않음).

## 9. 정상 로컬 렌더 측정치

**미검증(실제 브라우저 미실행).** 이 세션에서는 실제 Chrome/Edge를 열어 WebCodecs 인코딩이
끝까지 도는 것을 육안으로 확인하지 못했다. 대신 아래로 대체 검증했다:

- `GET /render-manifest.json` 데이터 계약 확인: `scenes[0]` 키에 `caption`,
  `caption_start_local`, `caption_end_local`, `image_url` 등 로컬 렌더가 실제로 필요로
  하는 값이 모두 채워져 내려옴을 실측 확인(PASS) - 이건 "로컬 렌더가 받을 재료가 올바르다"는
  증명이지 "브라우저가 그 재료로 실제 인코딩에 성공한다"는 증명은 아니다.
- 브라우저가 보내는 것과 동일한 형태로 `/mp4/render-diagnostics`를 시뮬레이션 전송해
  `wasm_supported`, `server_ffmpeg_used`, `webgpu_ready`, `webcodecs_ready` 필드가
  DB에 정확히 저장됨을 실측 확인(PASS, 10장 상세) - 이것도 "배선이 맞다"는 증명이지
  브라우저 실행 자체의 증명은 아니다.

**실제 브라우저 GPU 인코딩 자체는 사용자가 직접 "영상 만들기"를 눌러 확인하거나, 별도 승인
시 이 세션에서 Claude in Chrome으로 재시도하는 것을 권장한다(18장).**

## 10. 서버 폴백 측정치 (8033, 실측)

단일 요청(테스트 프로젝트, 문장 3개):

| 항목 | 값 |
|---|---|
| TTS 생성 | 200 OK, 9.299초 분량 음성 |
| SRT | 3 cue 성공 |
| MP4 생성 요청 | 200 OK |
| 총 소요시간 | 7.03초 |
| FFmpeg 소요시간(`ffmpeg_elapsed_ms`) | 6,800ms |
| 동시 ffmpeg.exe 프로세스 | 최대 1개 |
| 결과 MP4 | h264/aac, 12.799초, 990,178 bytes |
| `content_render_diagnostics` 기록 | `render_method=server`, `server_ffmpeg_used=1`, `outcome=server_success` - 자동 기록 확인(PASS) |
| 시뮬레이션 브라우저 보고 | `render_method=local`, `webgpu_ready=1`, `wasm_supported=1`, `server_ffmpeg_used=0` - 정확히 저장 확인(PASS) |

## 11. 동시 사용자 부하 결과 (8033, 실측, 서로 다른 테스트 계정 5개)

| 동시 요청 수 | 결과 | 총 소요시간 | 개별 소요시간 | FFmpeg 동시 최대 |
|---:|---|---:|---|---:|
| 5 | 전부 200 OK, `status=success` | 32.66초 | 18.5초~32.66초 | **2개** |

`FFMPEG_MAX_CONCURRENT=2` 설정과 정확히 일치했다. 폴링 샘플 꼬리
`[2,2,2,...,2,1,1,1,0,0]`에서 큐가 2개씩 처리되며 순서대로 빠지는 패턴이 뚜렷하게 관찰됨 -
세마포어가 실제로 대기열처럼 동작함을 실측으로 증명. 5개 전부 최종 `status=success`,
`render_method=server`로 정상 완료. (이 테스트는 서버 경로만 다뤘고, 실제 여러 브라우저
탭에서 동시에 로컬 렌더를 시도하는 시나리오는 다루지 않았다.)

## 12. 발견된 문제 (전부 수정 완료, 커밋 f70fcc7)

1. `local-render-controller.js`가 서버 폴백 시에도 `render_method`를 항상 `"local"`로
   잘못 전송하던 버그 - 수정
2. `generate_mp4_for_project()`에 서버 FFmpeg 소요시간을 기록할 방법 자체가 없었음 - 헬퍼
   함수와 6개 리턴 지점에 로깅 추가로 해결
3. 이 작업 중 `generate_mp4_for_project()`에 `user_id` 지역변수가 정의돼 있지 않던 것을
   발견(내 로깅 코드가 필요로 해서 드러남) - `project["user_id"]`로 정의 추가
4. 서버 FFmpeg 동시 실행에 전역 제한이 없어 무제한 병렬 실행 가능했음 - 세마포어(기본 2개)로 해결
5. (문서화만, 코드 변경 없음) 로컬 렌더 경로에서도 "영상" 미디어 선택 시 대표 프레임 추출을
   위해 FFmpeg가 1회 호출되는 숨은 예외 존재

## 13. 수정한 코드

`app/config.py`, `app/media/renderer.py`, `app/db/migrations.py`,
`app/static/js/render-capabilities.js`, `app/static/js/local-render-controller.js`,
`app/main.py`, `app/db/repository.py`, `app/media/service.py` - 커밋 `f70fcc7`
(2026-07-29, "요청서 1-2단계: FFmpeg 동시 실행 제한 및 렌더 진단 로깅 보강").
3~4단계는 검증만 수행했고 추가 코드 수정은 없다.

## 14. 서버 부하 최소화 정책 (확정)

```text
기본값: 사용자 브라우저 로컬 렌더(WebCodecs)
서버 FFmpeg: 예외적 폴백만, 전역 동시 실행 2개로 제한
초과 요청: threading.Semaphore 대기열에서 자동 대기(거부 아님)
```

## 15. 서버 렌더 동시 실행 제한 (구현·실측 완료)

`app/media/renderer.py`의 `_run_ffmpeg()`를 `threading.Semaphore(FFMPEG_MAX_CONCURRENT)`로
감쌌다(`FFMPEG_MAX_CONCURRENT` 기본값 2, `app/config.py`에서 환경변수로 조정 가능). 5개
동시 요청 실측에서 실제 ffmpeg.exe 프로세스가 2개를 초과한 적이 단 한 번도 없음을 폴링으로
확인했다(11장).

## 16. 테스트 결과 요약

```text
□ py_compile / node --check 문법 검사 - PASS (2단계에서 완료)
□ scripts/db_selftest.py 24개 항목 - PASS (2단계에서 완료, migration 16 반영 확인)
□ 8033 단일 TTS→SRT→MP4(서버) 실행 - PASS (실측)
□ render-manifest.json 데이터 계약 - PASS (실측)
□ 진단 로그 서버 경로 자동 기록 - PASS (실측)
□ 진단 로그 브라우저 시뮬레이션 왕복 - PASS (실측)
□ FFmpeg 동시 실행 2개 제한 - PASS (5-way 동시 실측)
□ 8032 운영 서버 무영향 - PASS (테스트 전후 PID 4440 유지, /docs 200 확인)
□ 실제 브라우저 WebCodecs/WebGPU 인코딩 육안 확인 - 미검증(사용자 지적, 별도 실제 브라우저 E2E 필요)
```

## 17. 미확인 항목

- **실제 Chrome/Edge에서 "영상 만들기"를 눌러 로컬 렌더가 끝까지 성공하는 것을 육안으로
  확인하지 못함 - WebGPU/WebCodecs가 실제 렌더링에 쓰였다는 최종 증명에는 별도의 실제
  브라우저 E2E가 필요하다(사용자 지적).** WebGPU는 코드상 사용 경로 자체가 없어 이 미검증이
  판정을 바꾸지 않지만(5장), WebCodecs는 "코드가 있다"와 "실제로 매번 성공한다"가 다른
  질문이라 이 미검증이 실질적인 공백이다.
- 요청서 9-1장이 요구한 `server_cpu_before/peak`, `ffmpeg_pid`, `ffmpeg_exit_code` 등
  프로세스/CPU 수준 계측은 미구현(psutil 등 추가 의존성 필요, 이번 범위에서는 생략)
- 서버 재시작 후 `rendering` 상태로 멈춘 작업의 복구 시나리오(요청서 6-3 테스트 F)는
  이번에 재현하지 않음
- 브라우저 탭 닫기·새로고침 중 로컬 렌더 중단 시나리오(테스트 F)도 미검증
- 여러 브라우저 탭에서 동시에 로컬 렌더를 시도하는 시나리오(순수 클라이언트 부하)는
  다루지 않음 - 11장 부하 테스트는 서버 폴백 경로만 다룸

## 18. 다음 작업 (선택, 사용자 승인 시)

1. **실제 브라우저(Chrome)로 "영상 만들기" 1회 눌러 로컬 렌더가 끝까지 성공하는지 육안
   확인 - WebGPU 미사용/WebCodecs 실사용 판정의 최종 증명을 완성하는 항목.** 이 세션에서
   Claude in Chrome 자동화로 시도하거나, 사용자가 직접 8032/8033에서 확인 가능
2. `ffmpeg_pid`/`server_cpu_peak` 등 프로세스 수준 계측 추가 여부 결정
3. 서버 재시작 복구, 탭 닫기 등 예외 시나리오 테스트

## 19. Git 커밋·Push 결과

1~2단계 코드 변경은 이미 커밋됨(`f70fcc7`, `origin/main`에 Push 및 해시 일치 확인 완료).
3~4단계는 코드 수정이 없어 이 보고서 파일만 추가 커밋한다.
