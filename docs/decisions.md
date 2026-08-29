# 주요 의사결정 기록

이 문서는 현재 코드와 commit 순서에서 확인되는 설계 결정을 ADR 요약 형식으로 기록한다.
모든 결정의 상태는 별도 표시가 없는 한 `Accepted`다.

## D-001. LLM 단독 요약 대신 근거 우선 hybrid 분석

- 결정: 전처리 → 규칙 분류 → 변경 연관 분석 → 선택적 LLM → 결과 검증 순서를 사용한다.
- 이유: 원문 전체 요약은 최초 오류와 연쇄 오류를 구분하기 어렵고 존재하지 않는 로그·파일을
  인용할 수 있다.
- 대안: 전체 로그를 LLM에 바로 전달하거나 규칙 엔진만 사용한다.
- 결과: LLM이 없어도 진단을 제공하며 evidence와 파일 경로를 검증할 수 있다. 반면 규칙과
  검증 코드를 별도로 유지해야 한다.
- 관련: `c5b7ecd`, `3796880`, `cd8f53a`.

## D-002. 실패 완료 이벤트만 비동기로 처리

- 결정: `workflow_run.completed` 중 `conclusion=failure`만 저장·enqueue하고 webhook은 즉시
  응답한다.
- 이유: 성공 실행 분석은 MVP 가치가 낮고 webhook 처리 시간을 외부 API·LLM 지연과 분리해야
  한다.
- 대안: 모든 workflow 상태 처리, webhook request 안에서 동기 분석.
- 결과: 입력량과 timeout 위험이 줄지만 진행 중 실행이나 성공 분석은 제공하지 않는다.
- 관련: `b55b8b4`, `bed9d38`.

## D-003. GitHub App installation token과 installation 단위 권한

- 결정: 저장소 접근에는 GitHub App token을, 사용자 로그인에는 OAuth token을 사용하고 분석
  조회는 공통 installation으로 제한한다.
- 이유: 장기 PAT보다 저장소 범위와 수명이 제한된 token이 최소 권한 원칙에 맞는다.
- 대안: 서비스 공용 PAT, repository 이름만 이용한 애플리케이션 권한 검사.
- 결과: App 설정이 복잡해지지만 저장소별 접근 격리를 명시적으로 검증할 수 있다.
- 관련: `cb53cad`, `acc5c86`, `8d1b4f0`.

## D-004. 마스킹을 저장·LLM 이전에 강제

- 결정: 로그뿐 아니라 patch, workflow와 실행 metadata도 사용 전에 같은 sanitizer를 거친다.
- 이유: secret은 로그 이외의 YAML, diff, branch 또는 runner 문자열에도 나타날 수 있다.
- 대안: LLM provider 직전에만 마스킹, provider의 데이터 보호에 의존.
- 결과: 원문 기반 재분석 가능성은 줄지만 노출 범위와 보관 위험을 낮춘다.
- 관련: `c5b7ecd`, `fad0526`.

## D-005. 최초 오류와 bounded chunk 선택

- 결정: 큰 로그를 chunk별로 먼저 마스킹하고 오류 신호가 있는 제한된 구간만 분석한다.
- 이유: 전체 입력은 비용·context 한도를 키우고 후속 오류가 최초 원인을 압도한다.
- 대안: 앞/뒤 고정 길이 truncate, 전체 로그 upload.
- 결과: 일반적인 오류 구간의 신호 밀도는 높아지지만 탐지 규칙에 없는 신호는 빠질 수 있다.
- 관련: `94d7dbf`, `af74c93`.

## D-006. Structured Outputs 이후에도 application 검증

- 결정: JSON schema 통과 여부와 별개로 evidence 포함 관계, 파일 존재와 규칙 충돌을
  검증한다.
- 이유: 구조가 올바른 응답도 내용상 근거가 없을 수 있다.
- 대안: schema validation만 수행.
- 결과: 환각을 차단하지만 유용해 보이는 제안도 수집 context에 근거가 없으면 폐기한다.
- 관련: `cd8f53a`.

## D-007. 규칙 진단을 항상 fallback으로 유지

- 결정: 규칙 결과를 먼저 만들고 LLM 장애·검증 실패 시 그대로 제공한다.
- 이유: 외부 provider 가용성이 CI 진단 전체 가용성을 결정하면 안 된다.
- 대안: LLM 실패 시 분석 전체 실패.
- 결과: 설명 품질이 낮아질 수 있어도 사용자는 최소한 오류 범주·근거·수정 방향을 받는다.

## D-008. PR 우선, 그 외 Commit Check 게시

- 결정: PR이 있으면 코멘트, 없으면 Commit Check를 사용하고 run marker로 upsert한다.
- 이유: PR 대화에는 코멘트가 자연스럽고 branch 실행은 SHA에 붙는 Check가 추적하기 쉽다.
- 대안: 모든 결과를 Check 또는 새 코멘트로만 생성.
- 결과: GitHub API 경로가 둘이지만 재시도 시 중복 알림을 피한다.
- 관련: `49042a1`, `3d61ee3`.

## D-009. 외부 fork를 별도 trust domain으로 처리

- 결정: fork 입력은 LLM에 보내지 않고 PR이 없는 fork SHA에는 Check를 만들지 않는다.
- 이유: 공격자가 제어하는 로그·diff는 prompt injection과 정보 유출, 권한 있는 게시의 입력이
  될 수 있다.
- 대안: 모든 실패를 동일하게 처리, 마스킹만 신뢰.
- 결과: 외부 기여 분석은 제한되지만 규칙 기반 결과와 명시적 경고는 유지한다.
- 관련: `d6ea6b6`, `0e43a7e`, `819e994`.

## D-010. SQLite/PostgreSQL을 공유하는 SQLAlchemy 저장 계층

- 결정: 로컬 기본값은 SQLite, Compose와 운영 경로는 PostgreSQL로 두고 Alembic migration을
  공통 사용한다.
- 이유: 개발 진입 비용과 운영 동시성·내구성 요구를 함께 만족시킨다.
- 대안: 처음부터 PostgreSQL만 요구, 별도 저장 구현 두 개 유지.
- 결과: 빠른 로컬 실행이 가능하지만 두 dialect를 통합 테스트해야 한다.
- 관련: `1e6c50c`, `9e4005b`, `c037575`.

## D-011. Queue abstraction과 두 worker 모드

- 결정: 동일 protocol 아래 메모리 queue와 Redis queue를 제공한다.
- 이유: 로컬 단일 프로세스 단순성과 운영 분리·확장을 동시에 지원한다.
- 대안: Celery 같은 별도 framework, Redis만 지원.
- 결과: 외부 framework 의존은 줄었지만 ack, retry, lease와 recovery를 직접 구현·검증한다.
- 관련: `bed9d38`.

## D-012. Lease만이 아니라 heartbeat와 fencing 사용

- 결정: Redis processing lease, worker heartbeat, orphan recovery와 DB attempt token을 함께
  사용한다.
- 이유: lease 만료는 작업을 회수할 수 있지만 이전 worker의 늦은 쓰기·게시를 막지 못한다.
- 대안: visibility timeout만 사용, 전역 lock.
- 결과: 여러 worker가 복구 가능하고 stale attempt의 부작용을 막지만 상태 전이에 token 검사가
  필요하다.
- 관련: `6eecb8d`부터 `b800c16`.

## D-013. DB-first enqueue와 reconciliation

- 결정: 분석 레코드를 먼저 저장하고 queue 전달 실패는 webhook 재전달과 startup scan으로
  복구한다.
- 이유: DB와 Redis를 가로지르는 원자 transaction은 없으며, webhook delivery를 잃는 것보다
  중복 없는 재적재가 안전하다.
- 대안: enqueue 후 DB 저장, distributed transaction.
- 결과: DB가 source of truth가 되고 잠깐의 전달 공백은 허용하되 복구 가능하다.
- 관련: `df87f23`, `643b6cf`.

## D-014. 직전 성공 실행을 non-PR baseline으로 사용

- 결정: PR diff가 없으면 같은 workflow·branch의 직전 성공 SHA 이후 변경을 비교한다.
- 이유: 단일 실패 commit만 보면 여러 commit에 걸친 회귀 원인을 놓칠 수 있다.
- 대안: 항상 head commit 하나, 기본 branch 전체 diff.
- 결과: 관련 범위가 실제 회귀 구간에 가까워지지만 성공 이력이 없으면 baseline 없이 진행한다.
- 관련: `3388c61`, `fa3d0fa`.

## D-015. 단계 이력과 사용자 관점 SLO를 함께 저장

- 결정: pipeline 내부 시간뿐 아니라 webhook 레코드 생성부터 첫 시작·완료까지 측정한다.
- 이유: worker 실행이 빨라도 queue 대기가 길면 사용자가 느끼는 서비스는 느리다.
- 대안: 함수 실행 시간만 측정.
- 결과: 60초 시작, 120초 완료 기준을 queue wait와 total latency로 판정할 수 있다.
- 관련: `2bc04d9`부터 `7a4ff97`.

## D-016. Offset 대신 cursor pagination

- 결정: `(created_at, run_id)`를 opaque cursor로 인코딩한다.
- 이유: 새 분석이 앞에 추가되는 이력에서 offset은 페이지 중복·누락을 만들 수 있다.
- 대안: page/offset.
- 결과: 안정적인 순회가 가능하지만 임의 페이지 이동은 제공하지 않는다.
- 관련: `beed7fc`, `bf0691f`.

## D-017. 고정 실패 fixture를 제품 품질 gate로 사용

- 결정: 10개 요구 범주를 재현하는 고정 로그에서 범주와 최초 원인 근거를 채점하고 80%를 CI
  최소값으로 둔다.
- 이유: 일반 unit test 통과만으로 진단 품질 회귀를 감지할 수 없다.
- 대안: 수동 데모, 범주 함수만 단위 테스트.
- 결과: MVP 완료 기준이 자동화되지만 실제 저장소 분포를 대표하는 지속적인 fixture 확장이
  필요하다.
- 관련: `60670ca`, `b05e687`.

## D-018. 외부 API retry를 bounded policy로 제한

- 결정: `Retry-After` 우선, jitter exponential backoff, 시도 횟수와 최대 지연을 설정한다.
- 이유: 무제한 retry는 worker lease와 사용자 SLO를 해치며 quota·billing 오류는 기다려도
  해결되지 않는다.
- 대안: 즉시 실패, 모든 4xx/5xx 재시도.
- 결과: 일시 장애는 흡수하면서 사용자 조치가 필요한 오류는 빠르게 드러낸다.
- 관련: `0a83ada`, `b7fbf6c`, `5c78f37`.

## D-019. 운영 보안 설정을 fail-fast 검증

- 결정: production에서 HTTPS public URL, 인증, Secure cookie, 최소 32자 webhook/session
  secret과 별도 token 암호화 key를 강제한다.
- 이유: 안전하지 않은 기본값으로 서비스가 조용히 기동되는 것을 막는다.
- 대안: warning만 출력, 배포 문서에만 요구사항 기재.
- 결과: 초기 설정은 더 엄격하지만 misconfiguration이 트래픽을 받기 전에 실패한다.
- 관련: `5b399d3`.

## D-020. 컨테이너 build context allowlist와 non-root runtime

- 결정: Dockerfile이 COPY하는 파일만 context에 포함하고 API·대시보드 모두 명시적 비권한
  USER로 실행한다.
- 이유: `.env`, `.git`, 가상환경과 의존성 디렉터리 전송을 막고 container compromise의
  기본 권한을 줄인다.
- 대안: `.gitignore`에 의존, root runtime 유지.
- 결과: 새 build 입력을 추가할 때 `.dockerignore`도 갱신해야 하며 Nginx는 8080을 사용한다.
- 관련: `b7d6833`, `e6ee9d8`, `92e11f8`.

## D-021. CI와 보안 검사를 서로 다른 gate로 유지

- 결정: 기능 CI, Docker build/smoke test와 CodeQL을 독립 workflow/job으로 실행한다.
- 이유: 실패 원인과 권한 범위를 분리하고 언어별 분석을 병렬화한다.
- 대안: 하나의 순차 job, 로컬 테스트만 수행.
- 결과: 실행 수는 늘지만 Python·TypeScript 분석, 실제 service 통합과 이미지 회귀를 독립적으로
  확인할 수 있다.
- 관련: `8462d52`, `41ce378`, `6a5d2ea`, `6fc8d83`.

## D-022. Dockerfile별 업데이트 경계와 대시보드 image grouping

- 결정: API와 대시보드 Dockerfile을 별도 Dependabot directory로 관리하고 대시보드의
  Node build image와 Nginx runtime image 업데이트는 한 PR로 묶는다.
- 이유: 두 Dockerfile은 build context와 검증 대상이 다르지만 대시보드의 build/runtime
  조합은 한 번의 production build와 smoke test로 함께 검증하는 편이 안전하다.
- 대안: base image 수동 업데이트, 모든 image를 각각 별도 PR로 생성.
- 결과: API image 변경은 독립적으로 검증되고 대시보드 image 조합은 원자적으로 검토된다.
  Compose에서만 참조하는 service image는 이 설정 범위에 포함되지 않는다.
- 관련: `d72d4da`.

## D-023. Python 지원 범위의 하한·상한 직전 검증

- 결정: 지원 범위를 `>=3.12,<3.15`로 명시하고 3.12에서 전체 service integration을,
  3.14에서 단위·API와 진단 평가를 실행한다. API image는 build와 USER 검사 뒤 실제
  `/readyz` 응답까지 확인한다.
- 이유: 모든 minor에서 무거운 PostgreSQL·Redis 통합 검사를 반복하지 않으면서 최소 지원
  버전과 최신 지원 버전의 packaging·runtime 호환성을 모두 확인해야 한다. Docker build
  성공만으로는 애플리케이션 import, SQLite 쓰기 권한과 queue readiness를 보장하지 않는다.
- 대안: Python 3.12만 지원·검사, 모든 3.12–3.14 조합에서 전체 integration 반복, image
  build만 검사.
- 결과: Python 3.13은 명시 범위에 포함되지만 양 끝 버전으로 호환성을 대표 검증한다.
  Python 3.15 지원은 dependency 호환성과 CI 추가 검토 후 별도로 연다.
- 관련: `4d371c6`.

## D-024. 대시보드 build runtime은 Node LTS만 지원

- 결정: 대시보드의 Node 지원 범위를 `^22.13.0 || ^24.0.0`으로 명시한다. 일반 CI는 지원
  하한인 Node 22를 검사하고 Docker production build는 최신 LTS인 Node 24를 사용한다.
  Dependabot은 Node의 semver-major 자동 업데이트를 무시하되 Nginx 업데이트는 계속
  제안하도록 한다.
- 이유: 2026-08-30 기준 Node 26은 Current release이며 공식 일정상 2026-10-28에 LTS로
  전환될 예정이다. production artifact를 만드는 build toolchain은 Current보다 LTS에서
  재현성과 dependency 지원을 확인하는 편이 안전하다.
- 대안: 항상 최신 Node major를 자동 반영, Node 24 image만 고정하고 지원 정책은 명시하지
  않음, 모든 지원 major에서 동일한 전체 CI 반복.
- 결과: Node major 전환은 LTS 승격 뒤 compatibility와 container build를 명시적으로 검토해야
  한다. Node major가 제외되어도 같은 Dependabot group의 Nginx 업데이트는 독립적으로 생성될
  수 있다.
- 근거: [Node.js release schedule](https://github.com/nodejs/Release/blob/main/schedule.json).
- 관련: `1f90715`.

## D-025. 배포할 이미지 자체를 fixable HIGH/CRITICAL gate로 검사

- 결정: CI에서 API·대시보드 이미지를 빌드한 직후 Trivy로 OS와 language package 취약점을
  검사하고, 수정 버전이 존재하는 HIGH 또는 CRITICAL 항목이 하나라도 있으면 실패시킨다.
  Action은 검증된 release commit SHA로 고정하고 실제 기동 검사는 scan 통과 뒤 수행한다.
- 이유: Dockerfile과 dependency source만 검사하면 base image layer와 build toolchain이
  runtime에 남긴 패키지를 놓칠 수 있다. 실제 배포 단위에서 차단해야 같은 artifact의 non-root
  설정, 취약점과 기동 가능성을 한 흐름으로 검증할 수 있다.
- 대안: 모든 severity를 차단, 수정 여부와 관계없이 차단, 정기 scan만 실행, 결과만 업로드하고
  CI를 통과시킴.
- 결과: 현재 수정할 수 있는 고위험 항목은 즉시 차단한다. 아직 수정 버전이 없는 항목은 빌드를
  영구 정지시키지 않도록 gate에서 제외하므로 별도 관찰·대응 절차가 필요하다. mutable base
  tag의 최신 보안 패치를 반영하기 위해 Debian/Alpine package upgrade를 image build에 포함한다.
- 관련: `ec7105c`, `89ffa86`.

## D-026. 실제 빌드 이미지마다 CycloneDX SBOM을 CI 증적으로 보관

- 결정: 취약점 gate를 통과한 API·대시보드 image에서 모든 발견 package를 포함한 CycloneDX
  JSON SBOM을 생성한다. CI가 형식과 component 존재 여부를 검증하고 image별 artifact로 14일간
  보관한다. Trivy와 artifact upload Action은 모두 commit SHA로 고정한다.
- 이유: source dependency 목록만으로는 base image의 OS package와 build 뒤 runtime에 남은
  component를 재구성할 수 없다. 취약점 판정에 사용한 실제 image에서 machine-readable inventory를
  함께 남겨야 사후 조사와 release 자동화의 입력으로 재사용할 수 있다.
- 대안: repository manifest만 보관, SPDX 형식 사용, SBOM을 생성하지만 CI artifact로 남기지 않음.
- 결과: 모든 `main`·PR image build에서 단기 검증 증적을 얻는다. CI artifact는 release에 연결된
  영구 배포물이나 서명된 attestation이 아니므로, GHCR release workflow에서 digest에 결합한
  provenance와 장기 SBOM 게시가 별도로 필요하다.
- 관련: `c4d362e`.

## D-027. 검증 후 push하고 release digest에 두 attestation을 결합

- 결정: `main` 이력의 `vMAJOR.MINOR.PATCH` tag만 release 입력으로 허용하고 backend,
  dashboard와 npm lockfile version 일치를 강제한다. image는 취약점, SBOM, non-root와 기동
  검증을 모두 통과한 뒤 version tag 하나로 GHCR에 push한다. 확정 digest에는 SLSA provenance와
  CycloneDX SBOM attestation을 각각 GitHub OIDC/Sigstore로 서명한다.
- 이유: registry push 뒤 검사하면 이미 소비 가능한 취약 image가 생긴다. tag가 아니라 digest에
  source workflow와 inventory를 결합해야 배포 시 실제 검증한 artifact를 식별할 수 있다.
- 대안: `main` push마다 `latest` 게시, 검사보다 push 우선, 별도 장기 credential로 서명,
  provenance 또는 SBOM 중 하나만 attestation.
- 결과: release는 재사용하지 않는 version tag와 immutable digest를 기준으로 소비한다. `latest`는
  만들지 않으며 Action은 commit SHA로 고정한다. matrix의 부분 게시 가능성은 실패 job 재실행으로
  복구하고 두 image와 attestation이 모두 확인되기 전에는 GitHub Release를 만들지 않는다. 실제
  첫 tag 실행과 외부 검증은 아직 남아 있다.
- 관련: `d7e600c`, `ed83890`, `f5e059d`.
