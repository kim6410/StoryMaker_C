# StoryMaker_C 단계 7 — TTS·SRT(Supertonic) 실제 완주 업무일지

- 작업 일시: 2026-07-29 (6B 완료 직후, 단계7~9 자동진행 지시서 기준)
- 작업 루트: `F:\StoryMaker_C`
- 근거 문서: `WORK_LOGS/2026-07-29_단계7_8_9_TTS_SRT_MP4_WebGPU_중간승인없이_자동진행_작업지시.md`(단계 7 절)

## 1. TTS 엔진 선정과 독립 설치

작업지시가 예시로 든 "Supertonic"은 Beta 전용 사설 서비스가 아니라 **공개 오픈소스 TTS 패키지**(`pip install supertonic`, GitHub `supertone-inc/supertonic`, 모델은 OpenRAIL-M 라이선스로 Hugging Face에서 배포)임을 6A 종료 업무일지 8장에서 이미 확인해 두었다. 이에 따라:

- `F:\StoryMaker_C\.venv`에 `pip install supertonic`으로 독립 설치(버전 `1.3.1`, 의존성 `onnxruntime==1.28.0`, `soundfile==0.14.0`, `numpy==2.5.1`도 함께 설치·`requirements.txt`에 고정).
- 모델 가중치는 `SUPERTONIC_MODEL_DIR = F:\StoryMaker_C\runtime\models\supertonic`로 최초 1회만 Hugging Face에서 다운로드(약 400MB, 26개 파일, 12초 소요 확인). `runtime/`은 `.gitignore`에 이미 포함되어 있어 모델 파일이 저장소에 올라가지 않는다.
- Beta의 `Supertonic3` 폴더나 실행 중인 Beta Supertonic 서비스는 전혀 참조하지 않았다(코드·모델 복사 없음, 완전 독립 설치).

## 2. DB 마이그레이션 008

`app/db/migrations.py`에 `_migration_008_tts_subtitle` 추가(적용 확인: `run_migrations() -> [8]`).

- `content_tts_sentences`: 문장별 원본 자막 텍스트, TTS용 정규화 텍스트, 화자, 속도, 저장 경로, ffprobe 실측 길이, 상태/오류코드. `(project_id, sentence_index)` 유니크.
- `content_tts_master`: 프로젝트당 1행, 전체 합성 WAV 경로와 ffprobe 실측 전체 길이.
- `content_srt`: 프로젝트당 1행, SRT 경로, 큐 개수, 마지막 자막 종료 시각, 오디오 길이, 오차(drift), 상태/오류코드.

## 3. 영상원고 정규화 (`app/tts/normalizer.py`)

6B에서 저장한 `content_video_scripts.scene_sentences_json`(장면 문장 목록)을 입력으로 받는다.

- `strip_speaker_tags()` — `[여성]`/`[남성]` 같은 대괄호 화자 표시 제거(자막·TTS 양쪽 모두).
- `clean_for_caption()` — 자막(SRT)에 쓸 원문. 화자 표시만 제거하고 숫자·전화번호 표기는 그대로 유지(가독성).
- `normalize_for_tts()` — TTS 입력 전용. 전화번호(`010-1234-5678` → "공 일 공 일 이 삼 사 오 육 칠 팔")는 자리별로, 일반 숫자(`3900원` → "삼천구백원", `20%` → "이십퍼센트", `1200000원` → "백이십만원")는 한자어(Sino-Korean) 자릿수 읽기로 변환.
- `split_long_sentence()` — 80자 초과 문장을 문장부호 → 쉼표 → 강제 절단 순으로 분할.
- `build_normalized_units()` — 빈 문장 제거 + 분할까지 적용해 (원본 자막용 텍스트, TTS용 정규화 텍스트) 쌍의 목록을 만든다. **원본과 정규화본을 항상 분리 저장**한다(작업지시 요구사항).

단위 테스트(수동 스크립트)로 위 규칙이 실제로 정확히 동작함을 확인했다(전화번호 자리읽기, 3900원/20%/24시간/1200000원 숫자 읽기, 6문장 분할, 빈 문장 3개 필터링 모두 기대값과 일치).

## 4. TTS Adapter (`app/tts/adapter.py`)

- Supertonic 모델은 프로세스당 1회만 지연 로딩(싱글턴)하고, 음성 스타일도 캐시한다.
- `synthesize_sentence()`가 문장 하나를 합성한다. 로컬 추론이라 네트워크 timeout 개념은 없지만, 엔진 예외(`engine_error`)와 빈 오디오(`empty_audio`)를 구분해서 반환하고, 실패 시 **최대 1회만 재시도**한다(무한 재시도 금지, `TTS_MAX_RETRIES=1`).
- 빈 텍스트는 애초에 엔진을 호출하지 않고 `empty_text`로 즉시 반환한다.

## 5. 서비스 계층 (`app/tts/service.py`)

- `generate_tts_for_project()`: 영상원고 존재 확인 → 정규화 → 문장별 계획을 `content_tts_sentences`에 기록 → 문장별로 순서대로 합성·저장·ffprobe 실측 → 전부 성공하면 `content_tts_master`에 전체 합성 WAV(무음 간격 0.4초로 이어붙임) 생성. 이미 `content_tts_master.status='success'`면 다시 만들지 않는다(불필요한 재작업 방지, 작업지시 15장 "기존 정상 산출물 재사용" 원칙).
- `regenerate_tts_sentence()`: 문장 하나만 다시 합성한다. 모든 문장이 성공 상태가 되면 그때 전체 합성 WAV를 다시 조립한다(디스크의 문장별 wav를 다시 읽어 조립 — 실패 문장만 재생성해도 나머지 문장을 다시 합성하지 않는다).
- 파일은 `data/jobs/{job_uid}/tts/sentence_NNN.wav`, `.../tts/full.wav`에 저장하고 DB에는 항상 `PROJECT_ROOT` 기준 상대경로만 저장한다.

## 6. SRT 생성 (`app/subtitle/srt_builder.py`)

- 글자 수 비율로 임의 분배하지 않고, **문장별 ffprobe 실측 길이**로만 누적 시작·종료 시각을 계산한다(작업지시 6장 핵심 요구사항).
- 자막 줄 길이(20자)·최대 2줄로 줄바꿈.
- 전체 합성 WAV의 ffprobe 실측 길이와 마지막 큐 종료 시각의 차이(drift)가 허용 오차(0.5초)를 넘으면 실패 처리하고 파일을 만들지 않는다.
- 이미 `content_srt.status='success'`면 다시 만들지 않는다(기존 정상 SRT 불필요한 덮어쓰기 금지).
- `parse_srt()`로 만든 파일이 실제로 파싱 가능한지 검증 유틸도 함께 제공.

## 7. 라우터/화면

`app/main.py`에 추가:

- `POST /content/job/{job_uid}/tts/generate` — TTS 생성 후 성공하면 이어서 SRT까지 생성.
- `POST /content/job/{job_uid}/tts/sentence/{index}/regenerate` — 문장 하나만 재생성, 전체가 성공 상태가 되면 SRT도 다시 만든다.
- `GET /content/job/{job_uid}/tts` — 문장별 상태·길이·재생, 전체 음성 재생, SRT 상태·다운로드를 실제 DB에서 읽어 표시(`content_job_tts.html` 신규).
- `GET /content/job/{job_uid}/tts/audio/{filename}` — 소유자만, 해당 작업의 `tts/` 폴더 안 파일명만 서빙(경로 이탈 불가, `Path(filename).name`으로 디렉터리 구분자 제거).
- `GET /content/job/{job_uid}/subtitle/download` — 소유자만 SRT 다운로드.

## 8. 실제 검증 (인프로세스 E2E)

기존 실행 중 서버(PID 7736, 권한 문제로 재시작 불가)를 건드리지 않고 `httpx.ASGITransport`로 앱을 새 프로세스에 불러와 실제 코드 경로로 검증했다.

시나리오: 회원가입 2계정(소유자/침입자) → 업체정보 → 작업생성 → 8채널 생성(영상원고 확보) → **TTS 생성** → **SRT 생성** → 강제 실패 후 **부분 재시도** → 소유권 격리 확인.

| 항목 | 결과 |
|---|---|
| 영상원고(scene_sentences_json) 존재 | 확인 |
| TTS 생성 소요시간 | 9.5초(9문장) |
| 문장 수 / 전부 성공 | 9 / 9 |
| 문장별 길이 0초 없음 | 확인(2.72s ~ 3.62s) |
| 문장별 wav 실제 파일 크기>0, ffprobe 재생 가능 | 9/9 확인 |
| 전체 합성 WAV ffprobe 길이 | 31.134초, codec=pcm_s16le |
| SRT 생성 상태 | success, 9개 큐 |
| SRT 마지막 종료시각 vs 오디오 길이 오차(drift) | 7.1×10⁻¹⁵초(사실상 0) — 허용오차 0.5초 이내 |
| SRT 파싱(`parse_srt`) | 성공, 큐 개수 일치(9) |
| 화자 표시([여성]/[남성]) SRT 텍스트에 없음 | 확인 |
| 문장 1개 강제 실패 → 부분 재시도 | 성공(status=success, 길이 3.065초로 복원) |
| 다른 사용자의 TTS 페이지/오디오/SRT 접근 | 전부 307 리다이렉트(차단) |
| 소유자의 오디오/SRT 접근 | 200, 실제 바이트 수신(오디오 2.75MB, SRT 753B) |
| DB `integrity_check` | ok |
| DB `foreign_key_check` | 위반 0건 |

"서버 재시작 후 상태 유지"는 이번 검증에서 매 단계가 이미 완전히 새로운 파이썬 프로세스(따라서 새로운 DB 연결)로 실행되었고, 파일과 DB 행이 다음 단계에서도 그대로 읽혔으므로 구조적으로 충족된다. 실제 브라우저용 개발 서버(포트 8031, PID 7736)는 6A 업무일지에서 기록한 것과 같은 권한 문제로 이번 세션에서 재시작하지 못했다 — 코드는 이미 반영되어 있으므로 사용자가 서버를 재시작하면 즉시 최신 코드로 동작한다.

## 9. 미완료/의도적으로 축소한 항목

- 영어 단어·약어 발음 처리는 최소 수준이다(Supertonic 멀티링구얼 모델이 한국어 문장 속 영어를 어느 정도 자체 처리하지만, 별도 발음 사전은 만들지 않았다).
- 화자/속도/톤/쉼 UI 설정 화면은 이번 범위에 넣지 않았다(현재는 마이페이지의 `voice_preference`(여성/남성)만 반영, 속도·쉼 간격은 `SUPERTONIC_DEFAULT_SPEED`/`SUPERTONIC_SENTENCE_GAP_SECONDS` 상수로 고정). 관리자/사용자 설정 UI는 다음 단계에서 필요 시 추가한다.
- 완전한 무음 자동 볼륨 정규화(라우드니스 표준화)는 다루지 않았다 — 단계 8에서 배경음악과 믹싱할 때 필요하면 추가한다.

## 10. Git 상태

관련 파일만 커밋 예정: `app/tts/`, `app/subtitle/`, `app/media/`, `app/config.py`, `app/constants.py`, `app/db/migrations.py`, `app/db/repository.py`, `app/main.py`, `app/templates/content_job_tts.html`, `app/templates/content_job_channels.html`(TTS 페이지 링크 추가), `requirements.txt`, `.gitignore`(temp/ 추가), 이 업무일지.

`runtime/models/supertonic/`(다운로드된 모델 가중치)는 `runtime/`이 이미 `.gitignore`에 있어 커밋되지 않는다.

별도로 존재하는 `WORK_LOGS/2026-07-29_단계9이후_UIUX_관리자편의성_고도화_상세작업지시.md`는 이번 세션이 만든 파일이 아니므로(다른 세션/사용자가 추가한 것으로 추정) 이번 커밋에 포함하지 않았다.
