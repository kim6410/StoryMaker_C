# Claude 최우선 긴급 조사 요청서
## StoryMaker_C 사용자 자원 렌더링 실사용 검증 및 서버 부하 최소화 확정 보고서

작성일: 2026-07-29  
작업 대상: `F:\StoryMaker_C`  
우선순위: **최우선 1순위 / 다른 기능 작업보다 먼저 수행**  
목적: 동시 접속자가 증가해도 StoryMaker_C 서버가 MP4 렌더링 부하를 직접 감당하지 않도록, 사용자 브라우저 자원 기반 렌더링을 실제 코드·실행·측정 결과로 검증하고 구조를 확정한다.

---

# 1. 조사 배경

StoryMaker_C는 사용자 브라우저의 Web Worker, Canvas, WebCodecs, WebGPU, WASM 등의 자원을 활용해 MP4를 생성하고, 서버는 가능한 한 작업 지시·파일 제공·결과 수신만 담당하는 구조를 목표로 한다.

하지만 현재 서버와 브라우저를 같은 Windows PC에서 실행하고 있어, 실제 MP4 제작 부하가 다음 중 어디에서 발생하는지 명확하게 구분하기 어렵다.

- 사용자 브라우저 프로세스
- StoryMaker_C Python 서버
- 서버가 실행한 FFmpeg 프로세스
- 브라우저 WebCodecs
- 브라우저 Canvas 또는 OffscreenCanvas
- WebGPU
- WASM
- JavaScript MP4 Muxer

동시 사용자 수가 증가한 상황에서 서버 FFmpeg 렌더가 기본 경로가 되거나 자주 폴백되면 CPU, GPU, 메모리, 디스크 I/O가 급격히 증가할 수 있다.

따라서 이번 조사의 목표는 단순히 코드에 `WebGPU`, `WASM`, `WebCodecs`라는 이름이 존재하는지를 확인하는 것이 아니다.

**실제 런타임에서 어떤 프로세스가 프레임 생성, 영상 인코딩, 음성 인코딩, MP4 조립을 수행하는지 측정하고 증명해야 한다.**

---

# 2. 현재까지 확인된 잠정 사실

다음 내용은 현재 코드의 1차 정적 조사에서 확인된 잠정 결과다. Claude는 반드시 직접 다시 확인하고, 사실과 다른 부분이 있으면 근거와 함께 수정한다.

## 2-1. 브라우저 로컬 렌더 경로

확인된 파일 후보:

```text
F:\StoryMaker_C\app\static\js\local-render-controller.js
F:\StoryMaker_C\app\static\js\local-renderer-worker.js
F:\StoryMaker_C\app\static\js\mp4-muxer.min.js
```

현재 파악된 흐름:

```text
브라우저
→ 렌더 Manifest 및 이미지·음성 fetch
→ Web Worker 실행
→ Canvas 또는 OffscreenCanvas로 프레임 작성
→ WebCodecs VideoEncoder로 영상 인코딩
→ WebCodecs AudioEncoder로 음성 인코딩
→ JavaScript MP4 Muxer로 MP4 조립
→ 완성 MP4를 서버로 업로드
```

## 2-2. 서버 폴백 경로

현재 컨트롤러에는 로컬 렌더 실패, 미지원, 정체, 시간 초과 시 다음 API로 서버 폴백하는 코드가 존재하는 것으로 보인다.

```text
POST /content/job/{job_uid}/mp4/generate
```

서버에서는 Python 미디어 모듈과 FFmpeg를 사용하는 것으로 보인다.

확인 대상 후보:

```text
F:\StoryMaker_C\app\media\renderer.py
F:\StoryMaker_C\app\media\service.py
```

## 2-3. WebGPU와 WASM

현재까지는 다음과 같이 보인다.

```text
WebGPU:
지원 여부 진단 필드는 있으나 실제 프레임 렌더 파이프라인에서
GPUDevice, GPUCanvasContext, createRenderPipeline, createComputePipeline 등을
실제로 사용하는지는 미확인

WASM:
WebAssembly.instantiate, instantiateStreaming, .wasm 로딩,
FFmpeg.wasm 또는 다른 WASM 인코더의 실제 사용 여부 미확인
```

따라서 현재 상태를 아래처럼 단정하지 않는다.

```text
금지된 성급한 결론:
WebGPU·WASM·FFmpeg가 모두 사용자 자원으로 실행된다.
```

현재 정확한 잠정 표현은 다음과 같다.

```text
Web Worker·Canvas·WebCodecs·JavaScript Muxer는 브라우저 경로가 존재한다.
WebGPU 실사용과 WASM 실사용은 증명이 필요하다.
FFmpeg는 서버 폴백 경로일 가능성이 높다.
```

---

# 3. 이번 조사에서 반드시 답해야 할 핵심 질문

Claude는 아래 질문에 각각 `확인`, `미확인`, `미사용`, `부분 사용` 중 하나로 명확히 판정하고 근거를 제시한다.

## 3-1. 실제 실행 위치

1. 영상 프레임 작성은 브라우저에서 수행되는가?
2. 영상 인코딩은 브라우저 `VideoEncoder`가 수행하는가?
3. 음성 인코딩은 브라우저 `AudioEncoder`가 수행하는가?
4. MP4 Muxing은 브라우저 JavaScript에서 수행되는가?
5. 완성 전 중간 영상 데이터를 서버로 보내는가?
6. 서버는 최종 MP4 Blob만 수신하는가?
7. 정상 로컬 렌더에서 `ffmpeg.exe`가 전혀 실행되지 않는가?
8. 정상 로컬 렌더에서 Python 서버 CPU 사용률은 어느 정도인가?
9. 서버 디스크에는 어떤 임시파일과 최종파일이 생성되는가?
10. 브라우저 탭을 닫거나 새로고침하면 렌더 작업이 어떻게 되는가?

## 3-2. WebGPU

1. `navigator.gpu` 지원 여부만 검사하는가?
2. 실제 `requestAdapter()`와 `requestDevice()`를 호출하는가?
3. `GPUDevice`를 프레임 처리에 사용하는가?
4. `createRenderPipeline()` 또는 `createComputePipeline()`을 사용하는가?
5. Canvas 2D만 사용하는가?
6. WebGPU가 미지원이어도 WebCodecs 로컬 렌더가 가능한가?
7. 현재 UI의 `WebGPU 준비됨` 표시는 실제 사용을 의미하는가, 단순 지원 여부를 의미하는가?

## 3-3. WASM

1. `.wasm` 파일이 프로젝트에 존재하는가?
2. 브라우저가 해당 `.wasm`을 네트워크로 불러오는가?
3. `WebAssembly.instantiate()` 또는 `instantiateStreaming()`을 호출하는가?
4. FFmpeg.wasm을 사용하는가?
5. 이미지 변환, 필터, 인코딩 중 어느 단계가 WASM인가?
6. WASM이 전혀 없는데 UI나 문서에서 WASM 렌더라고 표시하고 있지는 않은가?

## 3-4. FFmpeg

1. FFmpeg는 정상 로컬 렌더에도 실행되는가?
2. 로컬 렌더 실패 시에만 실행되는가?
3. 썸네일, 음성 합성, SRT 처리 등 다른 단계에서도 FFmpeg가 실행되는가?
4. 서버 FFmpeg 프로세스 수 제한이 있는가?
5. 동시에 여러 사용자가 폴백하면 FFmpeg가 몇 개까지 실행될 수 있는가?
6. 서버 FFmpeg에 동시 실행 잠금, 큐, 세마포어, 제한이 있는가?
7. 타임아웃과 강제 종료가 안전하게 구현되어 있는가?
8. 서버 종료 후 고아 `ffmpeg.exe`가 남을 가능성이 있는가?

---

# 4. 정적 코드 조사 방법

수정 전에 전체 흐름을 먼저 작성한다.

## 4-1. 검색어

프로젝트 전체에서 아래 문자열을 검색한다.

```text
navigator.gpu
requestAdapter
requestDevice
GPUDevice
GPUCanvasContext
createRenderPipeline
createComputePipeline
WebAssembly
instantiateStreaming
.wasm
ffmpeg
ffmpeg.exe
subprocess
VideoEncoder
AudioEncoder
VideoFrame
EncodedVideoChunk
EncodedAudioChunk
OffscreenCanvas
transferControlToOffscreen
Worker
SharedWorker
mp4-muxer
Muxer
ArrayBuffer
Blob
upload
render-diagnostics
server fallback
fallback
```

## 4-2. 데이터 흐름 지도

다음 API와 함수의 호출 관계를 파일명·함수명·행 번호와 함께 작성한다.

```text
사용자가 MP4 생성 버튼 클릭
→ 브라우저 Capability 검사
→ Manifest 요청
→ Worker 생성
→ Worker 입력 전달
→ 이미지 로딩
→ 음성 로딩
→ 프레임 생성
→ 영상 인코딩
→ 음성 인코딩
→ MP4 Muxing
→ 최종 Blob 생성
→ 서버 업로드
→ DB 상태 변경
→ 보관함 저장
```

서버 폴백도 별도로 작성한다.

```text
로컬 실패 조건
→ 폴백 사유 결정
→ 서버 API 호출
→ 서버 렌더 준비
→ FFmpeg 실행
→ 파일 저장
→ DB 상태 변경
→ 결과 반환
```

## 4-3. 코드 판정 기준

변수명이나 주석만으로 사용 여부를 판정하지 않는다.

예:

```text
navigator.gpu 존재 검사만 함
≠ WebGPU 실제 사용

WebAssembly라는 문자열이 있음
≠ WASM 모듈 실제 실행

ffmpeg 경로 설정이 있음
≠ 정상 로컬 렌더에서 FFmpeg 사용

VideoEncoder 지원 검사
≠ 실제 VideoEncoder.encode 호출 성공
```

실제 생성자 호출, 함수 실행, 런타임 로그, 결과 파일 생성까지 확인한다.

---

# 5. 런타임 검증 계획

테스트는 같은 Windows PC에서 서버와 브라우저를 실행하더라도 프로세스별로 분리 측정한다.

## 5-1. 필수 계측 대상

다음 프로세스를 구분한다.

```text
chrome.exe 또는 msedge.exe
python.exe
ffmpeg.exe
StoryMaker_C 관련 별도 Worker 프로세스
GPU Process
```

가능하면 Windows Performance Counter 또는 PowerShell을 사용해 아래 값을 1초 간격으로 기록한다.

```text
프로세스별 CPU 사용률
Working Set
Private Bytes
GPU Engine 사용률
디스크 Read/Write Bytes
네트워크 Send/Receive Bytes
프로세스 시작·종료 시각
PID
```

## 5-2. 브라우저 계측

브라우저 DevTools에서 아래를 확인한다.

```text
Console
Network
Performance
Memory
Web Workers
Media
chrome://gpu 또는 edge://gpu
```

콘솔에 임시 진단 로그를 추가할 수 있다.

필수 로그 예시:

```text
LOCAL_RENDER_CAPABILITY
LOCAL_RENDER_START
WORKER_CREATED
FRAME_RENDER_START
VIDEO_ENCODER_CONFIGURED
VIDEO_ENCODE_START
VIDEO_ENCODE_DONE
AUDIO_ENCODER_CONFIGURED
AUDIO_ENCODE_DONE
MUX_START
MUX_DONE
UPLOAD_START
UPLOAD_DONE
LOCAL_RENDER_SUCCESS
LOCAL_RENDER_FAILED
SERVER_FALLBACK_START
SERVER_FALLBACK_DONE
```

각 로그에는 반드시 다음을 포함한다.

```text
job_uid
timestamp
elapsed_ms
frame_count
video_codec
audio_codec
output_bytes
fallback_reason
```

## 5-3. 서버 계측

서버 로그에는 아래를 기록한다.

```text
job_uid
API endpoint
render_method
request_start
request_end
uploaded_bytes
ffmpeg_started
ffmpeg_pid
ffmpeg_exit_code
ffmpeg_elapsed_ms
server_cpu_before
server_cpu_peak
server_memory_before
server_memory_peak
```

정상 로컬 렌더에서 `ffmpeg_started=false`임을 증명해야 한다.

---

# 6. 필수 테스트 시나리오

최소 아래 시나리오를 모두 수행한다.

## 테스트 A. 정상 로컬 렌더

조건:

```text
Chrome 또는 Edge 최신 버전
WebCodecs 지원
충분한 메모리
짧은 이미지 슬라이드
정상 음성
```

확인:

- 브라우저 Worker 실행
- VideoEncoder 실제 호출
- AudioEncoder 실제 호출
- MP4 Muxer 실제 호출
- 최종 Blob 생성
- 서버에는 완성 MP4만 업로드
- `ffmpeg.exe` 미실행
- Python CPU 사용률 낮음
- 결과 MP4 재생 정상
- 오디오·영상 길이 정상
- 자막 정상
- 보관함 저장 정상

## 테스트 B. WebGPU 강제 미지원

방법:

- WebGPU 지원 검사를 강제로 false로 만들거나
- WebGPU를 비활성화한 브라우저 환경 사용

확인:

- WebCodecs 로컬 렌더가 계속 가능한지
- WebGPU가 실제 필수 의존성인지
- 단순 진단용인지
- 실패 시 정확한 사유가 기록되는지

## 테스트 C. WebCodecs 강제 미지원

방법:

- `VideoEncoder` 또는 `AudioEncoder`를 테스트 환경에서 비활성화

확인:

- 서버 폴백이 정확히 한 번만 실행되는지
- 폴백 사유가 `webcodecs_unsupported`처럼 명확한지
- 중복 렌더가 발생하지 않는지
- 브라우저 로컬 작업이 완전히 중단되는지
- 서버 FFmpeg가 한 번만 실행되는지

## 테스트 D. Worker 강제 실패

방법:

- 테스트 전용 플래그로 Worker 내부 예외 발생
- 또는 잘못된 미디어 URL 한 개 사용

확인:

- Worker 종료
- 임시 객체와 메모리 해제
- 서버 폴백 실행
- 사용자에게 이해 가능한 상태 표시
- 중복 MP4 생성 없음

## 테스트 E. 로컬 렌더 시간 초과

조건:

- 긴 영상
- 많은 이미지
- 낮은 성능 조건 시뮬레이션
- timeout 값을 테스트용으로 단축

확인:

- timeout이 실제로 동작하는지
- Worker가 terminate 되는지
- 이미 시작된 업로드나 인코더가 정리되는지
- 서버 폴백은 한 번만 발생하는지

## 테스트 F. 브라우저 새로고침·탭 닫기

확인:

- 브라우저 렌더 중 새로고침
- 탭 닫기
- 네트워크 끊기
- 다시 접속

검증:

- DB 상태가 영구적으로 `rendering`에 멈추지 않는지
- 재실행 가능 여부
- 임시 업로드 정리
- 중복 결과 방지

## 테스트 G. 동시 사용자 시뮬레이션

최소 아래 조건을 비교한다.

```text
1명 로컬 렌더
3명 로컬 렌더
5명 로컬 렌더
1명 서버 폴백
3명 서버 폴백
가능하면 5명 서버 폴백
```

브라우저를 여러 프로필 또는 자동화 브라우저로 분리한다.

각 조건에서 측정:

```text
서버 CPU 평균·최대
서버 메모리 평균·최대
ffmpeg.exe 개수
서버 디스크 쓰기량
네트워크 송수신량
평균 완료 시간
실패율
브라우저별 CPU·메모리
```

실제 서버 폴백 5개 동시 실행이 위험하면 무리하게 수행하지 말고, 코드 분석과 제한된 2~3개 테스트로 상한을 추정한다.

---

# 7. 서버 부하 최소화 방향의 확정 요구사항

조사 결과와 별개로 StoryMaker_C의 장기 원칙은 아래처럼 고정한다.

## 7-1. 기본 렌더 정책

```text
기본값: 사용자 브라우저 로컬 렌더
서버 FFmpeg: 예외적 폴백
```

서버 렌더를 사용자가 임의로 기본 선택할 수 있게 하지 않는다.

## 7-2. 로컬 렌더 완료 조건

다음이 실제로 확인된 경우에만 `local_success`로 기록한다.

```text
Worker 실행 성공
VideoEncoder 성공
AudioEncoder 성공
Mux 성공
최종 MP4 검증 성공
서버 업로드 성공
DB 저장 성공
```

지원 여부 검사만 통과했다고 로컬 성공으로 처리하지 않는다.

## 7-3. 서버 폴백 제한

서버 FFmpeg에는 반드시 동시 실행 제한을 둔다.

권장 기본안:

```text
서버 FFmpeg 동시 실행: 1개 또는 최대 2개
나머지: 대기열
사용자별 동시 폴백: 1개
작업별 중복 실행: 금지
```

정확한 수치는 Windows 서버 CPU, RAM, 디스크, 실제 벤치마크 결과로 결정한다.

무제한 `subprocess.Popen()` 또는 `subprocess.run()` 병렬 실행은 금지한다.

## 7-4. 폴백 남용 방지

아래 경우에 자동 서버 폴백을 무조건 허용하지 않는다.

```text
브라우저 탭이 백그라운드여서 일시 정체
사용자가 네트워크를 끊음
사용자가 탭을 닫음
단순 UI 오류
Manifest의 잘못된 미디어 한 개
재시도 가능한 일시 오류
```

이 경우에는 로컬 재시도 또는 사용자 안내를 우선 검토한다.

서버 폴백이 필요한 조건을 코드와 문서에서 명확히 정의한다.

## 7-5. 서버가 담당해야 할 일

서버의 기본 책임을 아래로 제한한다.

```text
인증
작업 상태 관리
Manifest 제공
이미지·음성 파일 제공
렌더 정책 제공
최종 MP4 업로드 수신
파일 검증
보관함 저장
진단 로그 저장
예외적 서버 폴백
```

정상 로컬 렌더에서 서버가 수행하지 않아야 할 일:

```text
프레임 생성
전체 영상 인코딩
전체 오디오 인코딩
MP4 Muxing
대형 임시 프레임 저장
```

---

# 8. WebGPU·WASM 도입 여부 판정

이번 조사에서 WebGPU와 WASM이 실제 사용되지 않는 것으로 확인될 수 있다.

이 경우 이름만 유지하지 말고 명확히 정리한다.

## 8-1. 실제 미사용이라면

UI와 문서에 다음처럼 과장 표시하지 않는다.

```text
WebGPU 렌더
WASM 렌더
GPU 렌더 완료
```

실제 기술에 맞게 표시한다.

```text
브라우저 로컬 렌더
WebCodecs 영상 인코딩
Web Worker 백그라운드 처리
Canvas 프레임 합성
```

## 8-2. WebGPU 도입 검토

WebGPU는 다음 경우에만 도입 가치가 있다.

```text
프레임 합성·필터·전환 효과가 Canvas 2D 병목인 경우
WebGPU 적용으로 측정 가능한 속도 개선이 있는 경우
구형 브라우저 폴백이 유지되는 경우
코드 복잡도 증가가 감당 가능한 경우
```

단순히 기술 이름을 사용하기 위해 도입하지 않는다.

## 8-3. WASM 도입 검토

WASM은 다음 경우에만 검토한다.

```text
WebCodecs 미지원 브라우저에 브라우저 내 인코딩이 필요한 경우
고성능 이미지 처리 또는 특수 코덱이 필요한 경우
서버 폴백보다 사용자 경험과 서버 비용 측면에서 유리한 경우
```

FFmpeg.wasm은 다운로드 크기, 메모리 사용, 모바일 성능, SharedArrayBuffer, COOP·COEP 요구사항을 반드시 검토한다.

---

# 9. 코드 수정 요구사항

조사 후 필요한 수정은 최소 범위로 수행한다.

## 9-1. 진단 정보 강화

DB 또는 진단 로그에 아래를 저장한다.

```text
render_method
browser_name
browser_version
os
webgpu_supported
webgpu_actually_used
webcodecs_video_supported
webcodecs_audio_supported
webcodecs_actually_used
wasm_supported
wasm_actually_used
worker_used
canvas_backend
video_codec
audio_codec
frame_count
render_elapsed_ms
mux_elapsed_ms
upload_elapsed_ms
output_bytes
fallback_used
fallback_reason
server_ffmpeg_used
server_ffmpeg_elapsed_ms
```

`지원됨`과 `실제 사용됨`을 반드시 구분한다.

## 9-2. 사용자 화면 표시

개발·관리자 진단 영역에는 실제 완료 결과를 표시한다.

정상 로컬 렌더 예:

```text
렌더 위치: 사용자 브라우저
영상 인코더: WebCodecs VideoEncoder
음성 인코더: WebCodecs AudioEncoder
프레임 합성: OffscreenCanvas
MP4 조립: JavaScript Muxer
WebGPU: 지원 / 실제 사용 안 함
WASM: 사용 안 함
서버 FFmpeg: 사용 안 함
```

서버 폴백 예:

```text
렌더 위치: StoryMaker_C 서버
폴백 사유: VideoEncoder 미지원
서버 FFmpeg: 사용
대기시간: 12초
렌더시간: 48초
```

일반 사용자 화면은 과도하게 기술적이지 않게 표시하고, 상세 정보는 관리자·진단 영역에 둔다.

## 9-3. 서버 렌더 큐

서버 FFmpeg 경로에 동시 실행 제한이 없다면 구현한다.

필수 요소:

```text
글로벌 세마포어
사용자별 중복 방지
작업별 lock
대기 상태
시작 상태
완료·실패 상태
timeout
프로세스 terminate/kill
고아 프로세스 정리
서버 재시작 후 복구
```

---

# 10. 성능 보고서에 포함할 표

최종 보고서에는 아래 표를 실제 수치로 작성한다.

## 10-1. 단일 작업 비교

| 항목 | 브라우저 로컬 렌더 | 서버 FFmpeg 렌더 |
|---|---:|---:|
| 총 완료 시간 |  |  |
| 브라우저 CPU 최대 |  |  |
| 브라우저 메모리 최대 |  |  |
| 서버 CPU 최대 |  |  |
| 서버 메모리 증가 |  |  |
| 서버 디스크 쓰기 |  |  |
| 네트워크 다운로드 |  |  |
| 네트워크 업로드 |  |  |
| FFmpeg 실행 여부 |  |  |
| 결과 MP4 크기 |  |  |
| 영상 길이 |  |  |
| 성공 여부 |  |  |

## 10-2. 동시 사용자 비교

| 동시 작업 수 | 방식 | 서버 CPU 최대 | 서버 메모리 | FFmpeg 수 | 평균 시간 | 성공률 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | 로컬 |  |  |  |  |  |
| 3 | 로컬 |  |  |  |  |  |
| 5 | 로컬 |  |  |  |  |  |
| 1 | 서버 |  |  |  |  |  |
| 3 | 서버 |  |  |  |  |  |
| 5 또는 안전 상한 | 서버 |  |  |  |  |  |

## 10-3. 기능 사용 여부

| 기술 | 지원 여부 | 실제 사용 여부 | 실행 위치 | 근거 |
|---|---|---|---|---|
| Web Worker |  |  |  |  |
| Canvas 2D |  |  |  |  |
| OffscreenCanvas |  |  |  |  |
| WebCodecs VideoEncoder |  |  |  |  |
| WebCodecs AudioEncoder |  |  |  |  |
| WebGPU |  |  |  |  |
| WASM |  |  |  |  |
| JavaScript MP4 Muxer |  |  |  |  |
| FFmpeg |  |  |  |  |

---

# 11. 완료 판정 기준

아래 조건을 모두 만족해야 이번 작업을 완료로 판단한다.

```text
□ MP4 생성 전체 데이터 흐름 지도가 작성됨
□ WebGPU 지원과 실제 사용이 구분됨
□ WASM 지원과 실제 사용이 구분됨
□ WebCodecs 실제 인코딩 호출이 증명됨
□ 정상 로컬 렌더에서 ffmpeg.exe 미실행이 증명됨
□ 서버 CPU·메모리·디스크 사용량이 측정됨
□ 로컬 렌더와 서버 렌더 성능이 비교됨
□ 동시 사용자 테스트 또는 안전한 상한 추정이 수행됨
□ 서버 FFmpeg 동시 실행 제한 여부가 확인됨
□ 필요 시 서버 렌더 큐와 세마포어가 구현됨
□ 폴백 조건이 코드와 문서에 명확히 고정됨
□ 지원 여부와 실제 사용 여부가 진단 DB에 분리 저장됨
□ 일반 사용자와 관리자 진단 표시가 구분됨
□ DB 무결성 및 기존 기능 회귀가 확인됨
□ 업무일지와 최종 보고서가 작성됨
□ 관련 파일만 커밋·Push됨
```

---

# 12. 최종 산출물

Claude는 최소 아래 문서를 작성한다.

```text
F:\StoryMaker_C\WORK_LOGS\2026-07-29_사용자자원_로컬렌더_WebCodecs_WebGPU_WASM_FFmpeg_실사용_검증보고서.md
```

보고서에는 다음을 포함한다.

1. 조사 요약
2. 최종 판정
3. 실제 렌더 구조
4. 파일·함수·행 번호 근거
5. WebGPU 실사용 판정
6. WASM 실사용 판정
7. WebCodecs 실사용 판정
8. FFmpeg 실행 위치와 조건
9. 정상 로컬 렌더 측정치
10. 서버 폴백 측정치
11. 동시 사용자 부하 결과
12. 발견된 문제
13. 수정한 코드
14. 서버 부하 최소화 정책
15. 서버 렌더 동시 실행 제한
16. 테스트 결과
17. 미확인 항목
18. 다음 작업
19. Git 커밋·Push 결과

추측은 사실처럼 기록하지 않는다.

실행 테스트를 못 한 항목은 반드시 `미검증`으로 표시한다.

---

# 13. Claude에게 전달할 최종 명령

다른 UI 개선, 썸네일 디자인, 프롬프트 품질, 회원관리, 보관함 작업보다 이 조사를 먼저 수행한다.

수정부터 시작하지 말고 아래 순서로 진행한다.

```text
1. 00_READ_FIRST.md 전체 읽기
2. 최신 WORK_LOGS 확인
3. MP4 로컬·서버 렌더 전체 코드 흐름 조사
4. WebGPU·WASM·WebCodecs·FFmpeg 실사용 여부 판정
5. 런타임 계측 도구와 테스트 계획 작성
6. 정상 로컬 렌더 측정
7. 강제 실패와 서버 폴백 측정
8. 동시 사용자 부하 시험
9. 서버 부하 위험 분석
10. 최소 수정안 구현
11. 서버 렌더 큐·동시 실행 제한 확정
12. 회귀·DB 무결성·E2E 검증
13. 상세 보고서 작성
14. 관련 파일만 커밋·Push
```

핵심 목표는 다음 한 문장이다.

> **정상적인 MP4 제작의 무거운 작업은 사용자 브라우저가 담당하고, StoryMaker_C 서버는 예외적 폴백을 제외하면 영상 인코딩 부하를 감당하지 않는 구조로 확정한다.**
