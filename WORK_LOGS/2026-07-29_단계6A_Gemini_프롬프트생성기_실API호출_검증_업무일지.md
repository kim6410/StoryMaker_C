# StoryMaker_C 단계 6A — Gemini 프롬프트 생성기 실 API 호출 검증 업무일지

- 작업 일시: 2026-07-29 01:37 ~ 01:55 KST
- 작업 루트: `F:\StoryMaker_C`
- 참고 작업지시: `WORK_LOGS/2026-07-29_단계6A_Gemini_프롬프트생성기_실API호출_검증_작업지시.md`
- 결론 먼저: **작업지시 15장의 완료 기준을 전부 충족하지는 못했습니다.** 코드·검증·보안·회귀 항목은 모두 통과했지만, "실제 Gemini API 호출 성공 / 유효한 JSON 응답 수신 / 스키마 검증 성공"은 외부 요인(아래 6번)으로 아직 달성하지 못했습니다. 이 사실을 숨기지 않고 그대로 보고합니다.

## 1. 실제 호출한 Provider와 모델

- Provider: `gemini` (Google Generative Language API, `v1beta`)
- 모델: `gemini-2.0-flash` (환경변수 `GEMINI_MODEL` 미설정 시 기본값)
- 엔드포인트: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`
- API 키 출처: `config/.env`의 `GEMINI_API_KEY`는 비어 있고, 이 PC의 사용자 수준 Windows 환경변수 `GEMINI_API_KEY`가 대신 사용되고 있음을 확인했습니다(다른 세션이 설정한 것으로 추정). `app/config.py`는 `config/.env`에 값이 없으면 기존 OS 환경변수를 그대로 사용하도록 만들어 두었습니다.

## 2. 실제 API 호출 성공 여부

**성공하지 못했습니다.** 실제 네트워크 호출은 정상적으로 이루어졌고 Google 서버가 인증까지는 정상 처리했지만(키 자체는 유효), 매 호출마다 HTTP 429 `RESOURCE_EXHAUSTED`로 거부되었습니다. Google이 반환한 원인은 다음과 같습니다.

```
quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 0
quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier, limit: 0
quotaId: GenerateContentInputTokensPerModelPerMinute-FreeTier, limit: 0
```

즉 "일시적으로 요청이 많아서" 발생하는 429가 아니라, 이 키가 속한 Google Cloud 프로젝트의 무료 등급 할당량 자체가 **0**으로 설정되어 있습니다. 재시도로 해결되는 문제가 아니며, 다음 중 하나가 필요합니다.

- 해당 Google Cloud 프로젝트에 결제 계정을 연결해 유료 등급 할당량을 받거나
- 무료 등급 할당량이 정상 배정된 다른 `GEMINI_API_KEY`로 교체

코드·프롬프트·검증 로직의 문제가 아님을 별도 스크립트로 4개 모델(`gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-flash-latest`, `gemini-2.5-flash`)에 대해 직접 확인했고, `gemini-2.0-flash`만 이 키에 대해 "모델은 존재하지만 할당량 0"이라는 동일한 오류를 재현했습니다(나머지는 404로 아예 이 키에 노출되지 않는 모델).

## 3. 응답 JSON 검증 결과

실제 API 호출은 429에서 막혀 유효한 콘텐츠 JSON을 받아본 적이 없습니다. 대신 검증기(`app/ai/schema.py`)는 아래 15개 단위 테스트로 별도 검증했습니다(전부 PASS).

- 정상 JSON 파싱 + 코드펜스 제거 후 파싱
- 잘못된 JSON, 빈 문자열
- 필수 필드 누락, 최대 길이 초과, keywords 타입 오류
- API 키 문자열이 응답에 섞여 나올 경우 차단(유출 검사)

## 4. 정상 테스트 수 / 실패 테스트 수

| 구분 | 개수 | 내용 |
|---|---|---|
| Gemini Adapter 단위 테스트 | 8/8 PASS | api_key_missing(네트워크 호출 없음 확인 포함), timeout, network_error, authentication_failed(재시도 없음 확인), permission_denied, empty_response, blocked_response, 정상 파싱 |
| 검증기 단위 테스트 | 7/7 PASS | invalid_json ×2, 필수 필드 누락, 길이 초과, keywords 타입 오류, API 키 유출 차단, 코드펜스 정상 파싱 |
| 실제 HTTP E2E(회원가입→로그인→업체정보→작업생성→생성 호출) | 4/4 PASS | 각 단계가 실제 DB·세션을 거쳐 정상 동작 |
| 중복 요청 방지(동시 요청 2건) | 1/1 PASS(수정 후) | 아래 6번 참고 |
| 소유권 격리(다른 사용자가 남의 job_uid 접근) | 2/2 PASS | GET/POST 모두 `/content/new`로 리다이렉트, 생성 시도 자체가 발생하지 않음 |
| **실제 Gemini 콘텐츠 생성 성공** | **0/1** | 429 할당량 0으로 계속 실패(3번 참고) |

## 5. 오류 상태별 처리 결과

13개 오류 코드 중 아래는 실제로 값을 만들어 확인했습니다.

| 오류 코드 | 확인 방법 | 결과 |
|---|---|---|
| api_key_missing | 단위 테스트(키를 빈 문자열로 패치) | PASS, 네트워크 호출 자체가 발생하지 않음 확인 |
| authentication_failed | 단위 테스트(401 모킹) | PASS, 재시도 0회 확인 |
| permission_denied | 단위 테스트(403 모킹) | PASS |
| timeout | 단위 테스트(TimeoutException 모킹) | PASS, 재시도 2회 후 최종 실패 확인 |
| rate_limited | **실제 API 호출**(429) | PASS, 실제로 재현됨(3번) |
| provider_5xx | 코드 경로만 구현(모킹 테스트는 생략) | 미검증 |
| network_error | 단위 테스트(ConnectError 모킹) | PASS |
| invalid_json | 단위 테스트 | PASS |
| schema_validation_failed | 단위 테스트 4종 | PASS |
| empty_response | 단위 테스트 | PASS |
| blocked_response | 단위 테스트(promptFeedback.blockReason 모킹) | PASS |
| duplicate_request | **실제 동시 요청 2건** | PASS(수정 후, 6번 참고) |
| unknown_provider_error | 서비스 계층 예외 안전망(try/except)만 구현 | 미검증 |

## 6. 개발 중 발견하고 수정한 버그

실제 동시 요청 테스트에서 버그를 하나 발견해 즉시 수정했습니다.

- **증상**: 같은 프로젝트에 생성 요청 2개를 거의 동시에 보내면, 하나는 `duplicate_request`가 아니라 `unknown_provider_error`로 잘못 처리됨.
- **원인**: 중복 방지는 `content_generations(project_id)`에 `status='pending'`인 행이 1개만 있도록 하는 부분 유니크 인덱스로 구현했는데, SQLite가 이 위반을 알릴 때 오류 메시지에 인덱스 이름이 아니라 컬럼 이름만 담는 경우가 있었습니다(`UNIQUE constraint failed: content_generations.project_id`). 코드가 오류 메시지 문자열에 인덱스 이름이 포함되어 있는지로 중복 여부를 판별하고 있어서, 이 경우를 놓치고 일반 예외로 다시 던져버렸습니다.
- **수정**: `app/db/repository.py`의 `create_content_generation()`이 이 INSERT에서 나는 `sqlite3.IntegrityError`는 (이 테이블에 다른 유니크 제약이 없으므로) 메시지 내용과 무관하게 전부 `DuplicateGenerationError`로 처리하도록 변경했습니다.
- **재검증**: 수정 후 서버를 재기동하고 동시 요청 2건을 다시 보내 `duplicate_request` 1건 + 정상 처리(이번에는 `rate_limited`) 1건으로 정확히 분리되는 것을 실제 HTTP 응답으로 확인했습니다.

## 7. 중복 호출 방지 방식

- `content_generations(project_id)`에 `status='pending'`일 때만 걸리는 부분 유니크 인덱스(`idx_content_generations_pending_lock`)를 DB 제약으로 사용했습니다. 애플리케이션 레벨의 잠금(락 객체, Redis 등)이 아니라 DB 제약 자체가 최종 방어선이라 프로세스가 여러 개여도 안전합니다.
- 같은 프로젝트에 이미 `pending` 행이 있는 상태에서 새 생성 요청이 오면 `INSERT`가 `IntegrityError`로 실패하고, 이를 `DuplicateGenerationError`로 변환해 Gemini를 호출하지 않고 즉시 `duplicate_request`를 반환합니다.
- 생성 시작 이후에는 어떤 예외가 나더라도 반드시 `pending` 행을 `success`/`failed`로 확정하도록 `try/except`로 감쌌습니다(그렇지 않으면 잠금이 영구히 풀리지 않는 문제가 생김).

## 8. 생성·수정 파일

**신규**
- `app/integrations/__init__.py`, `app/integrations/gemini_client.py`
- `app/ai/__init__.py`, `app/ai/prompt_builder.py`, `app/ai/schema.py`, `app/ai/service.py`

**수정**
- `app/config.py` — `GEMINI_API_KEY`/`GEMINI_MODEL`/`GEMINI_API_BASE`/`GEMINI_REQUEST_TIMEOUT_SECONDS` 추가
- `app/constants.py` — Gemini 오류코드 13종, 재시도 정책 상수, `PROMPT_VERSION`/`RESPONSE_SCHEMA_VERSION` 추가
- `app/db/migrations.py` — migration 006(`content_generations`, `content_generation_results`)
- `app/db/repository.py` — 생성 이력·결과 저장 함수 6종, `DuplicateGenerationError`
- `app/main.py` — `POST /content/job/{job_uid}/generate`, 소유권 검사 공통화(`_get_owned_project_or_none`)
- `app/templates/content_job_status.html` — 생성 버튼, 오류 메시지, 결과 표시 영역 추가

## 9. DB migration

- migration 006 `content_generation` 적용 완료(서버 재기동 후 `schema_migrations`에서 확인).
- `content_generations`: provider/model/prompt_version/response_schema_version/status/http_status/error_code/retry_count/request_started_at/completed_at/latency_ms만 저장. **전체 프롬프트·전체 응답 원문은 어디에도 저장하지 않습니다**(작업지시 11장).
- `content_generation_results`: 검증을 통과한 정규화된 결과(title/summary/body/call_to_action/keywords_json/shortform_script)만 저장. 이번 라운드에서는 성공 사례가 없어 실제로 채워진 행은 없습니다.

## 10. 로그 노출 검사 결과

- `app/ai/*.py`, `app/integrations/*.py`에 `print(` 또는 로깅 호출이 **0건**(정적 검사로 확인, findstr 결과 매칭 없음) — 애초에 로그를 남기는 코드 자체가 없으므로 API 키·프롬프트·응답 전문이 로그로 나갈 경로가 없습니다.
- DB에도 프롬프트·응답 원문 컬럼이 없음(9번 항목의 스키마 참고).

## 11. 회귀 테스트 결과

- 인증 E2E: **13/13 PASS** (서버 재기동 후 재실행)
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: 위반 0건
- 음악 카탈로그: 61건 그대로 유지
- 마이페이지 업체정보 저장: 이번 테스트 계정으로 실제 저장·리다이렉트 확인(`saved=1`)

## 12. 미완료 항목 (작업지시 15장 기준 미충족)

- **실제 Gemini API 호출 성공** — 미달성(3번 사유)
- **유효한 JSON 콘텐츠 응답 수신** — 미달성(위와 동일 사유로 시도 자체가 불가)
- **스키마 검증 성공(실 응답 기준)** — 미달성(검증기 자체는 단위 테스트로 별도 검증했으나, 실 API 응답으로는 아직 확인 못함)
- `provider_5xx`, `unknown_provider_error` 두 오류 코드는 강제 재현 테스트를 하지 않았습니다(코드 경로만 존재).

## 13. 남은 위험

- 현재 `GEMINI_API_KEY`(OS 환경변수)로는 결제 계정 연결 또는 키 교체 전까지 실제 콘텐츠 생성이 원천적으로 불가능합니다.
- `provider_5xx`/`unknown_provider_error` 경로는 실제 트래픽에서 아직 검증되지 않았습니다.
- 이번 테스트로 생긴 테스트 계정(`e2e_gemini_*`, `e2e_intruder_*`, `e2e_dupfix_*`)과 그에 딸린 `failed` 상태 프로젝트가 DB에 남아 있습니다(실사용자 데이터 아님, 필요 시 정리 가능).

## 14. 커밋 / Push / 해시 일치

(커밋 실행 후 별도로 기록)

## 15. 다음 단계

사용자가 `GEMINI_API_KEY`의 할당량 문제(결제 연결 또는 키 교체)를 해결해 주시면, 이번에 만든 어댑터·검증기·서비스 계층은 코드 변경 없이 바로 실제 성공 케이스를 만들 수 있습니다. 그 확인이 끝나면 단계 6A를 완전히 종료하고 6B(SNS 8채널 출력 계약)로 넘어가겠습니다.
