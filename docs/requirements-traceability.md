# MVP 요구사항 추적성

이 문서는 최초 PipeLens 프로젝트 명세의 기능 요구사항 FR-01~FR-11과 비기능 요구사항을 현재
구현·자동 검증·외부 인수 증적에 연결한다. 기준은 2026-09-09 `main`이며, 상세 운영 상태는
[검증 및 운영 준비 현황](readiness.md)을 함께 본다.

## 상태 정의

| 상태 | 의미 |
| --- | --- |
| 구현·자동 검증 완료 | 요구 동작이 코드에 있고 로컬 또는 CI 회귀 검증이 존재함 |
| 외부 인수 필요 | 코드와 증적 도구는 있으나 실제 계정·공개 endpoint·production 자원 결과가 없음 |
| 미구현 | 요구 동작 또는 이를 판정할 수단이 없음 |

자동 검증 완료는 실제 서비스 완료와 다르다. GitHub App, 공개 HTTPS, production data·secret·알림
채널과 장시간 부하는 저장소가 소유하지 않는 환경에서 별도 증적을 만들어야 한다.

## 기능 요구사항

| ID | 요구사항 | 구현 위치 | 자동 검증 | 현재 판정 |
| --- | --- | --- | --- | --- |
| FR-01 | GitHub App 설치·installation token·최소 권한·연동 상태 | `src/pipelens/auth.py`, `src/pipelens/github.py`, `src/pipelens/main.py` | `tests/test_auth.py`, `tests/test_github.py`, `tests/test_security.py` | 구현·자동·[#61 실제 App acceptance](acceptance-runs/2026-09-08-github-app-consolidated.json) 완료 |
| FR-02 | 실패한 `workflow_run`만 감지하고 job·step 식별, run 중복 방지 | `src/pipelens/main.py`, `src/pipelens/github.py`, `src/pipelens/store.py`, `src/pipelens/queue.py` | `tests/test_webhook.py`, `tests/test_queue.py`, `tests/test_store.py` | 구현·자동·실제 delivery 재전달 완료 |
| FR-03 | 실패 로그 수집, ANSI·timestamp 제거, 오류 구간·최초 오류·청크 처리 | `src/pipelens/github.py`, `src/pipelens/preprocessing.py`, `src/pipelens/classifier.py` | `tests/test_github.py`, `tests/test_preprocessing.py`, `tests/test_classifier.py` | 구현·자동 검증 완료 |
| FR-04 | token·key·JWT·header·password·email 마스킹, 원문 비보존 | `src/pipelens/sanitizer.py`, `src/pipelens/pipeline.py` | `tests/test_sanitizer.py`, `tests/test_pipeline.py`, `tests/test_security.py` | 구현·자동 검증과 실제 seeded-secret persistence·게시 무노출 완료 |
| FR-05 | 명세의 10개 실패 범주와 근거·신뢰도·step·규칙 제공 | `src/pipelens/classifier.py`, `src/pipelens/models.py`, `evaluation/scenarios.json` | `tests/test_classifier.py`, `tests/test_evaluation.py`, CI `pipelens-evaluate --minimum-accuracy 0.8` | 구현·자동 검증 완료, 고정 fixture 13/13 |
| FR-06 | PR/commit, 이전 성공 이후 변경, 오류 경로와 diff·workflow 연관 분석 | `src/pipelens/github.py`, `src/pipelens/relevance.py`, `src/pipelens/pipeline.py` | `tests/test_github.py`, `tests/test_relevance.py`, `tests/test_pipeline.py` | 구현·자동 검증 완료 |
| FR-07 | 구조화된 LLM 입력·응답, 교체 가능한 provider와 모델·prompt 기록 | `src/pipelens/llm.py`, `src/pipelens/diagnosis.py`, `src/pipelens/pipeline.py` | `tests/test_llm.py`, `tests/test_diagnosis.py`, `tests/test_pipeline.py` | 구현·자동 검증과 대표 latency·429·503 retry soak 완료. 실제 provider 품질·token·비용은 운영 재측정 |
| FR-08 | 근거 필수, 실제 log·file 존재 검증, 부족·충돌 처리와 fallback | `src/pipelens/diagnosis.py`, `src/pipelens/pipeline.py` | `tests/test_diagnosis.py`, `tests/test_pipeline.py`, `tests/test_relevance.py` | 구현·자동 검증 완료 |
| FR-09 | PR comment 또는 Commit Check에 요약·근거·관련 파일·제안·상세 링크 게시 | `src/pipelens/publication.py`, `src/pipelens/github.py`, `src/pipelens/pipeline.py` | `tests/test_publication.py`, `tests/test_github.py`, `tests/test_pipeline.py` | 구현·자동 검증과 실제 comment·Check 게시·upsert 완료 |
| FR-10 | 저장소별 실행·상태·분류·진단·시간·feedback·GitHub 링크 dashboard | `src/pipelens/main.py`, `src/pipelens/store.py`, `frontend/src/App.tsx` | `tests/test_analysis_api.py`, `frontend/src/App.test.tsx`, `frontend/e2e/oauth-dashboard.spec.ts` | 구현·자동 검증 완료. production 접근은 [#62](https://github.com/sangmu1126/PipeLens/issues/62) |
| FR-11 | 정확도·부분 정확도·부정확·해결 여부 feedback 저장과 지표화 | `src/pipelens/models.py`, `src/pipelens/store.py`, `src/pipelens/main.py`, `frontend/src/App.tsx` | `tests/test_feedback_api.py`, `tests/test_store.py`, dashboard build | 구현·자동 검증 완료 |

## 비기능 요구사항

| 영역 | 요구와 구현 | 자동 증거 | 남은 외부 증거 |
| --- | --- | --- | --- |
| 보안 | HMAC webhook, encrypted OAuth token, installation 접근 격리, LLM 전 마스킹, untrusted fork 격리, production fail-closed 설정 | `tests/test_webhook.py`, `tests/test_auth.py`, `tests/test_sanitizer.py`, `tests/test_security.py`, `tests/test_pipeline.py`, CodeQL·secret scan·dependency review | 실제 GitHub 경계 완료. production HTTPS [#62](https://github.com/sangmu1126/PipeLens/issues/62), secret manager [#65](https://github.com/sangmu1126/PipeLens/issues/65) |
| 성능 | 비동기 queue·worker, run dedupe, 시작 60초·완료 120초 SLO 기록 | `tests/test_queue.py`, `tests/test_worker.py`, CI 200-job drill, [1시간 worker soak](acceptance-runs/2026-09-09-worker-soak/README.md) | launch 모델 완료; 실제 traffic이 1 job/s를 넘으면 재산정 |
| 신뢰성 | GitHub/LLM retry, Redis ack·lease recovery, 단계 이력, LLM 실패 시 규칙 fallback, stale attempt fencing | `tests/test_http_retry.py`, `tests/test_worker.py`, PostgreSQL·Redis integration, [launch 규모 recovery](acceptance-runs/2026-09-08-recovery-scale/README.md), [worker fault soak](acceptance-runs/2026-09-09-worker-soak/README.md) | 운영량 증가 시 provider·network·recovery 기준 재산정 |
| 관측성 | 성공·지연·범주·LLM token/cost·feedback·redaction·queue·SLO Prometheus 지표와 Grafana dashboard | `tests/test_metrics.py`, `tests/test_pipeline.py`, `tests/test_feedback_api.py`, Prometheus rule·Grafana provisioning CI | 실제 incident receiver와 acknowledgement [#64](https://github.com/sangmu1126/PipeLens/issues/64) |

## 서비스 완료를 막는 외부 인수 조건

| 우선순위 | Issue | 완료 증거 |
| --- | --- | --- |
| P0 완료 | [#61 실제 GitHub App E2E](https://github.com/sangmu1126/PipeLens/issues/61) | [strict evidence](acceptance-runs/2026-09-08-github-app-consolidated.json): 실제 PR·branch 실패, comment·check upsert, SLO, secret·fork 격리 |
| P0 | [#62 공개 HTTPS OAuth·webhook](https://github.com/sangmu1126/PipeLens/issues/62) | TLS·HSTS, secure session, callback·forwarding, signed webhook |
| P1 완료 | [#63 production 규모 recovery](https://github.com/sangmu1126/PipeLens/issues/63) | [strict evidence](acceptance-runs/2026-09-08-recovery-scale/evidence.json): launch 대표 규모 PostgreSQL·Grafana RTO/RPO, read-only cutover·보존 source rollback |
| P1 | [#64 Alertmanager 실채널](https://github.com/sangmu1126/PipeLens/issues/64) | firing·resolved, grouping·dedupe·inhibition, rotation·retry |
| P1 | [#65 secret manager](https://github.com/sangmu1126/PipeLens/issues/65) | workload identity, file injection, Fernet·외부 credential rotation |
| P1 완료 | [#66 production worker soak](https://github.com/sangmu1126/PipeLens/issues/66) | [strict evidence](acceptance-runs/2026-09-09-worker-soak/evidence.json): 1시간 resource·provider·fault telemetry, SLO와 capacity 승인 |

각 절차의 strict JSON verifier와 redaction 규칙은 이미 저장소에 있다. example이나 짧은 합성 CI
결과만으로 issue를 닫지 않으며, 승인된 acceptance 원본과 공개 가능한 SHA-256·비민감 식별자를
함께 남긴다.

## 변경 관리

- 요구사항 동작이 바뀌는 PR은 이 표의 구현 위치·자동 증거·판정을 함께 갱신한다.
- 새 기능 요구사항은 안정된 ID를 부여하고 최소 하나의 자동 검증 또는 명시적인 외부 인수 조건에
  연결한다.
- `구현·자동 검증 완료`와 `외부 인수 필요`를 합쳐서 `완료`로 축약하지 않는다.
- 배포·운영 결과는 [readiness](readiness.md), 설계 선택은 [decisions](decisions.md), 시간순 작업은
  [development history](development-history.md)에 각각 기록한다.
