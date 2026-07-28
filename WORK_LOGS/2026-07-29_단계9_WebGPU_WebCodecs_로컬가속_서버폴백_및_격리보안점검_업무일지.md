# StoryMaker_C 단계 9 — WebGPU·WebCodecs 로컬 가속·서버 폴백 및 격리·보안 점검 업무일지

- 작업 일시: 2026-07-29 (단계8 완료 직후)
- 작업 루트: `F:\StoryMaker_C`
- 근거 문서: `WORK_LOGS/2026-07-29_단계7_8_9_TTS_SRT_MP4_WebGPU_중간승인없이_자동진행_작업지시.md`, `WORK_LOGS/2026-07-29_단계9이후_UIUX_관리자편의성_고도화_상세작업지시.md` 31장(WASM·WebGPU·WebCodecs 실전 성공기 및 적용 명세)

## 1. 단계 9 완료 여부

**핵심 로컬 렌더 경로와 서버 폴백 경로 모두 실제 브라우저(Chrome, claude-in-chrome 확장)로 검증 완료.** 31장이 요구하는 실전 수준 항목 중 핵심(실제 기능 탐지·실제 시험 인코딩·실제 로컬 렌더 성공·서버 검증·서버 폴백·중복 렌더 방지·기존 산출물 재사용·결과 계약 통일)은 구현·검증했다. Worker 내부 세부 계측(31-18장), 관리자 진단 화면(31-17장), 취소/새로고침 복구 UX(31-15장)는 이번 범위에서 데이터 기반(테이블)만 마련하고 화면은 다음 범위로 남겼다(12장 참고).

## 2. 구현 내용

### 2.1 기능 탐지 (`app/static/js/render-capabilities.js`)
- WebGPU: `navigator.gpu` 존재만으로 판정하지 않고 `requestAdapter → requestDevice → 실제 렌더 패스 1회 제출`까지 성공해야 `webgpu_ready`로 판정(31-2장).
- WebCodecs: `VideoEncoder.isConfigSupported()` 통과만 믿지 않고, **실제 제작 해상도(1080x1920)** 로 소형 프레임 1개를 실제로 인코딩해 청크가 나오는지까지 확인(31-3장). 처음에는 64x64로만 시험해 "작은 해상도는 되는데 실제 해상도에서 즉시 실패"하는 오탐이 있었고, 실전 검증 중 발견해 실제 해상도로 고쳤다(3번 항목 참고).

### 2.2 로컬 렌더 Worker (`app/static/js/local-renderer-worker.js`)
- Worker에서만 프레임 생성·인코딩·Muxing을 수행하고 메인 스레드는 UI만 담당(31-4장).
- 그라디언트 배경 + Ken Burns 줌 + 자막/업체정보 오버레이를 OffscreenCanvas 2D로 그린 뒤 `VideoEncoder`로 H.264(avc1.420028, Baseline Level 4.0), `AudioEncoder`로 AAC 인코딩.
- Muxing은 오픈소스 `mp4-muxer`(MIT, Vanilagy, v5.2.2)를 `app/static/vendor/mp4-muxer.min.js`로 프로젝트에 직접 내려받아 사용(WebCodecs 청크를 표준 fMP4로 묶는 바이너리 박스 구조를 직접 구현하는 대신 검증된 라이브러리를 선택 — V1·Beta 자산이 아닌 순수 오픈소스 신규 도입).
- 배경음악 덕킹(발화 구간 낮은 음량)·시작 페이드인·종료 페이드아웃은 원시 PCM 샘플에 직접 적용(서버 FFmpeg 경로와 동일한 타임라인 규칙: 1.5초 리드인 + TTS 길이 + 2초 엔딩).

### 2.3 메인 스레드 컨트롤러 (`app/static/js/local-render-controller.js`)
- 기능 미지원/시간초과(90초)/진행정체(25초 무응답)/Worker 예외 시 자동으로 기존 서버 렌더(`POST /content/job/{job_uid}/mp4/generate`)로 폴백(31-11장). 폴백 시 AI 원고·TTS·SRT는 전혀 다시 만들지 않는다(이미 존재하는 산출물만 재사용, 서비스 계층은 단계8부터 이미 그렇게 동작).
- 폴백 발생 시 사용자에게 실패처럼 보이지 않되 사실은 숨기지 않는 안내 문구 표시(31-16장).

### 2.4 서버 측 (`app/main.py`, `app/media/service.py`)
- `GET /content/job/{job_uid}/render-manifest.json`: 서버가 이미 계산한 장면·오디오 URL만 제공(소유자 전용).
- `POST /content/job/{job_uid}/mp4/upload-local`: 브라우저가 만든 MP4를 서버가 **다시 ffprobe로 검증**(코덱 h264/오디오 존재, 길이 오차 ≤1.5초, 파일크기>0)한 뒤에만 완료 처리한다(Blob 생성만으로 성공 처리 금지, 31-14장).
- `POST /content/job/{job_uid}/mp4/render-diagnostics`: 성능·성공여부 진단 로그(개인정보·과도한 장치 지문 없이 최소 정보만) 저장.
- `content_mp4.render_method`(local/server)로 로컬·서버 결과를 같은 테이블·같은 `/mp4/video` 재생 경로로 통일(31-13장, 결과 계약 통일).
- `try_start_mp4_render()`로 작업 ID별 렌더 잠금 추가 — 로컬 렌더 업로드와 서버 렌더가 동시에 같은 작업을 처리하지 못하게 차단(31-10장).

### 2.5 마이그레이션 010
- `content_mp4`에 `render_method`, `fallback_reason` 컬럼 추가.
- `content_render_diagnostics` 테이블 신규(웹지피유/웹코덱 준비 여부, 메모리 추정치, 결과, 폴백 사유, 소요시간만 저장 — 개인정보 없음).

## 3. 실전 검증 중 발견하고 수정한 버그 3건

실제 Chrome 브라우저(claude-in-chrome)로 검증하지 않았다면 발견하지 못했을 버그들이다. 전부 실제 브라우저 실행 결과로 발견 → 원인 규명 → 수정 → 재검증까지 완료했다.

| # | 증상 | 원인 | 수정 |
|---|---|---|---|
| 1 | Worker가 `addColorStop` 예외로 즉시 실패 | 서버(FFmpeg lavfi)는 `0x1b2a4a` 표기를 쓰는데 Canvas는 CSS `#1b2a4a` 표기가 필요 | `local-renderer-worker.js`에 `toCssColor()` 변환 추가 |
| 2 | `VideoEncoder` 설정 직후 "coded area exceeds maximum... AVC level 3.1" 오류 | 1080x1920(약 207만 화소)은 Level 3.1(92만 화소 한도)을 초과하는데 코덱 문자열을 `avc1.42001f`(Level 3.1)로 고정해뒀음 | `avc1.420028`(Level 4.0, 209만 화소 한도)로 수정. 실제 제작 해상도로 시험 인코딩하도록 기능탐지도 함께 고침(2.1항) |
| 3 | 자체 제작 TTS/MP4 스트리밍이 브라우저에서 계속 로딩만 되고 재생되지 않음(HAVE_NOTHING 고착) | 설치된 Starlette 0.38.6의 `FileResponse`가 **HTTP Range 요청을 전혀 처리하지 않음**(실제 fetch로 확인: Range 헤더를 보내도 매번 200 + 전체 바이트 응답, `Accept-Ranges` 헤더도 없음). 브라우저 `<video>`/`<audio>`는 재생 판단에 Range(206) 응답이 필요 | `app/media/range_response.py` 신규 — 직접 Range 파싱 + 206 Partial Content 응답 구현. `content_job_tts_audio`, `content_job_mp4_video`, `music_preview` 3개 라우트에 적용 |

3번 버그는 **단계7·8에서 이미 커밋된 기존 기능**(TTS 오디오 재생, MP4 재생)에도 영향을 주는 실제 결함이었다. 단계 9 검증 과정에서 발견해 즉시 고쳤다.

## 4. 실제 브라우저 검증 결과 (claude-in-chrome)

이번 세션 소유의 임시 개발 서버(포트 8032, 아래 8번 참고)에서 진행. 실제 회원가입→로그인→업체정보→작업생성→8채널 생성→TTS·SRT 생성까지 전부 실제 화면 클릭/폼 제출로 수행한 뒤:

- 기능 탐지 결과(이 Chrome 인스턴스, GPU 어댑터 미노출 환경): `webgpu.supported=false`(reason: no_adapter), `webcodecsVideo.supported=true`(실제 시험 인코딩 성공), `worker=true`, `offscreenCanvas=true`. → `localRenderReady=true`로 정확히 판정.
- **"내 PC에서 빠르게 만들기" 버튼 실제 클릭 → 실제 성공**: 화면에 `제작 방식: 내 PC`로 표시됨. 서버 DB 확인: `content_mp4.status='success'`, `render_method='local'`, `duration_seconds=18.433`, `file_size_bytes=750199`.
- **서버 폴백 실제 검증(2가지 방식)**:
  1. 버그 수정 전, Worker가 실제로 예외를 던졌을 때 컨트롤러가 자동으로 서버 렌더를 호출해 성공(`outcome='fallback_success'`, 결과 화면에 `제작 방식: 서버`로 정상 표시) — 의도치 않게 실전 폴백까지 검증된 셈이다.
  2. 기능 미지원을 강제 주입한 명시적 시험: `localRenderReady=false`로 설정 → 즉시(`onFallback` 호출) 서버 렌더로 전환 → 성공(`{ok: true, method: 'server'}`).
- 브라우저 진단 로그가 `content_render_diagnostics`에 실제로 저장됨을 DB에서 확인.

### 4.1 실제 재생(육안) 확인의 한계

이 Chrome 인스턴스는 `WebGPU requestAdapter()`가 항상 실패하고, `<video>` 태그로 **직접 제작한 MP4는 물론 이미 검증된 FFmpeg 제작 MP4(단계8 산출물)조차 재생이 시작되지 않고 멈추는 환경**임을 별도로 확인했다(`video.play()` 호출 시 렌더러가 45초간 응답 없이 멈춤). 이는 이 브라우저 인스턴스의 하드웨어/미디어 파이프라인 제약으로 판단되며(WebGPU 어댑터 미노출과 같은 계열의 환경 제약), 파일 자체의 문제가 아님을 ffprobe/ffmpeg 완전 디코드 성공, MP4 박스 구조 직접 검사(ftyp/moov/mdat 정상), 서버 측 재검증 통과로 교차 확인했다. 따라서 "브라우저에서 사람이 눈으로 재생 확인"은 이번 세션에서 완전히 하지 못했고, 이는 정직하게 미완료로 남긴다(10번 항목 참고).

## 5. 격리·보안 점검 (사용자 지시로 단계9 직후 최소 수정 보강)

### 5.1 경로 이탈(Path Traversal) 방지 보강
`app/config.py`의 `to_absolute_path()`가 상대경로를 절대경로로 복원할 때 `PROJECT_ROOT` 밖으로 벗어나는지 검사하지 않고 있었다. `PathEscapeError`를 추가하고 `candidate.relative_to(PROJECT_ROOT)`로 포함 여부를 검증하도록 고쳤다. 단위 시험으로 확인:

```
정상: to_absolute_path('data/jobs/test/tts/full.wav') -> 정상 반환
차단: '../../../Windows/System32/drivers/etc/hosts' -> PathEscapeError
차단: '..\\..\\secret.txt' -> PathEscapeError
차단: 'data/../../../etc/passwd' -> PathEscapeError
```

이 헬퍼를 실제로 쓰도록 `app/main.py`(SRT 다운로드, MP4 스트리밍), `app/media/service.py`, `app/tts/service.py`의 `PROJECT_ROOT / db경로` 직접 조합 코드 6곳을 전부 `to_absolute_path()` 호출로 교체했다.

### 5.2 DB 경로형 컬럼 전수 조사
`content_tts_sentences/master`, `content_srt`, `content_scenes`, `content_music_mix`, `content_mp4`, `music_catalog`의 경로 컬럼 총 142개 값을 스크립트로 전수 검사 — 절대경로·`..` 포함 값 **0건**.

### 5.3 심볼릭 링크·Junction·서브모듈 재검증
- `find -type l`: 0건. PowerShell `Get-ChildItem -Attributes ReparsePoint`(전체 트리 재귀): 0건.
- `.gitmodules` 없음, `git submodule status` 없음.
- `app/` 소스 안에 다른 드라이브 절대경로(`C:\`, `D:\` 등)나 `StoryMaker_V1`/`StoryMaker_beta` 참조 문자열 검색 결과 0건.

### 5.4 Gemini 설정 독립성 보강
코드는 이미 `GEMINI_API_KEY`/`GEMINI_MODEL`이라는 일반 이름만 읽고 Beta 전용 변수명(`BETA_GEMINI_API_KEY` 등)은 어디에서도 참조하지 않음을 재확인했다. 다만 6A 조사에서 이 PC의 **OS 사용자 수준 `GEMINI_API_KEY`를 Beta와 암묵적으로 공유**하고 있었던 상태였으므로, `config/.env`가 비어 있던 `GEMINI_API_KEY` 값을 프로젝트 전용 파일에 직접 채워 넣어 완전히 독립시켰다(키 원문은 어떤 로그·업무일지·화면에도 출력하지 않았고, 이관 전후 해시 비교로만 동일 값임을 확인했다). `config/.env`는 `.gitignore`에 포함되어 있어 이 변경은 커밋되지 않는다. 앞으로 이 세션 이후에도 StoryMaker_C는 OS 공유 환경변수 없이 자체 파일만으로 동작한다.

### 5.5 `.claude/settings.local.json` 권한 축소
장시간 세션 동안 누적된 `Bash(powershell.exe *)`, `Bash(curl *)`, `Bash(git add *)`(00_READ_FIRST의 `git add .`/`-A` 금지 원칙과 충돌) 같은 광범위 와일드카드와, 스크래치패드 임시경로에 묶인 1회성 명령 수십 건을 정리해 프로젝트 작업에 필요한 최소 패턴(프로젝트 venv python/pip, git commit/push/ls-remote, 로컬 헬스체크, 프로젝트 ffmpeg/ffprobe 실행파일, PID 기반 taskkill)만 남겼다. (참고: Claude Code 하네스가 새 명령을 승인할 때마다 이 파일에 자동으로 항목을 추가하는 방식으로 동작하므로, 이번 세션 이후 작업 중 다시 늘어날 수 있음 — 세션 종료 시점에 다시 한번 정리 권장.)

## 6. 회귀 재검증

경로 보안 강화(5.1항) 반영 후 단계 8·9 E2E를 모두 다시 실행해 회귀가 없음을 확인했다.

- 단계8 MP4 E2E: 전체 재통과(h264/aac, 1080x1920/30fps, 배경음악 포함, 타임라인 정확히 일치, 소유권 차단, DB 무결성 `ok`/FK 위반 0).
- 단계9 서버측 E2E: 전체 재통과(위조 파일 거부, 소유권 차단, 서버·로컬 결과 동일 경로 재생, Range 요청 206 정상, 렌더 잠금 정상 차단, 진단 로그 저장, DB 무결성 `ok`/FK 위반 0).

## 7. 8031/8032 서버 구분과 정리

- 8031: 기존에 실행 중이던 **운영 개발 서버**(PID 7736). 6A 업무일지부터 기록된 권한 문제로 이 세션에서 재시작할 수 없어 전혀 건드리지 않았다. 최신 코드는 이미 반영되어 있으므로, 사용자가 직접(또는 상위 권한으로) 재시작하면 즉시 최신 상태로 동작한다.
- 8032: 이번 세션이 **직접 실행하고 소유한 단계9 실브라우저 검증 전용 임시 서버**. 검증이 끝난 지금 완전히 종료했다(`taskkill`로 프로세스 종료 확인, `netstat`로 포트 미점유 확인). 관련 임시 로그 파일(`temp_server_8032.log`)과 디버그용 임시 라우트(`/debug/save-blob`, 검증 후 코드에서 완전히 제거), 임시 테스트 페이지(`app/static/test_capabilities.html`)도 모두 삭제·원복했다.

## 8. 미완료·남은 위험

- **브라우저 육안 재생 확인 불가**: 4.1항 참고. 이 세션의 Chrome 인스턴스가 WebGPU·비디오 하드웨어 디코드에 제약이 있어 사람이 눈으로 재생을 확인하지 못했다. 파일 유효성은 ffprobe·박스 구조·서버 재검증으로 교차 확인했지만, "일반 사용자 브라우저에서 실제 재생 확인"(31-14, 31-20 기준)은 이 세션에서 완전히 증명하지 못했다.
- WebGPU 프레임 합성 경로는 이번 범위에서 실제 사용(디텍션만 정확히 구현, 프레임 그리기는 Canvas2D로 통일)하지 않았다 — WebGPU가 잡히는 환경에서의 실제 가속 경로는 다음 범위.
- Worker 세부 계측(31-18장 전체 항목), 관리자 진단 화면(31-17장), 로컬 렌더 사전 적합성 검사 UI(31-6장, 현재는 자동 판정만), 취소 버튼·탭종료 경고 UI(31-15, 31-16 일부)는 데이터 기반은 마련했지만 화면 UI는 다음 범위.
- 사용자 업로드 사진·영상이 아직 없어(단계8부터 이어지는 제약) 로컬 렌더도 그라디언트 배경을 사용한다.
- `.claude/settings.local.json`은 하네스가 세션 중 자동으로 다시 넓어질 수 있다(5.5항 참고) — 다음 세션 시작 시 재점검 권장.

## 9. Git 상태 및 Push 결과

아래 파일만 선별 스테이징해 커밋했다(관련 없는 변경 없음, `git add .`/`-A` 미사용):

수정: `app/config.py`, `app/db/migrations.py`, `app/db/repository.py`, `app/main.py`, `app/media/ffprobe_utils.py`, `app/media/service.py`, `app/templates/content_job_mp4.html`, `app/tts/service.py`
신규: `app/media/range_response.py`, `app/static/js/local-render-controller.js`, `app/static/js/local-renderer-worker.js`, `app/static/js/render-capabilities.js`, `app/static/vendor/mp4-muxer.min.js`, `app/static/vendor/mp4-muxer.LICENSE.txt`, 이 업무일지

커밋 해시·Push 결과·세 해시(로컬 HEAD/origin/main/`git ls-remote`) 일치 여부는 커밋 직후 별도로 기록한다.
