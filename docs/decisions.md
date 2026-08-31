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
  복구하고 두 image와 attestation이 모두 확인되기 전에는 GitHub Release를 만들지 않는다.
  `v0.1.0`에서 두 image와 네 attestation의 GitHub API·OCI registry 검증을 완료했다.
- 관련: `d7e600c`, `ed83890`, `f5e059d`.

## D-028. Image attestation과 GitHub Release 불변성을 별도로 판정

- 결정: digest·Sigstore attestation 검증 성공만으로 GitHub Release를 immutable이라고 표시하지
  않는다. `v0.1.0`은 Release API의 `immutable: false`를 그대로 기록한다. repository의 release
  immutability는 2026-08-30 활성화하고, 차기 release부터 draft를 완성한 뒤 publish한다.
- 이유: image provenance는 특정 registry digest의 출처를 증명하지만 GitHub Release의 tag와
  asset 변경을 막지 않는다. GitHub 공식 정책상 immutability 활성화는 미래 release에만 적용돼
  이미 발행한 release를 소급 보호하지 않는다.
- 대안: attestation을 release lock으로 간주, 기존 release 삭제·재생성, 한계를 기록하지 않음.
- 결과: repository API에서 `enabled: true`, `enforced_by_owner: false`를 확인했다. 설정은 미래
  release에만 적용되므로 `v0.1.0`에는 GitHub가 강제하는 tag·asset lock이 없다. 차기 release는
  draft asset과 note를 완성한 뒤 publish하고 Release API의 `immutable: true`를 별도로 검증한다.
- 근거: [GitHub immutable releases](https://docs.github.com/code-security/concepts/supply-chain-security/immutable-releases),
  [preventing release changes](https://docs.github.com/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes).

## D-029. 1인 저장소도 PR과 7개 check를 관리자까지 강제

- 결정: `main` 변경은 PR을 통과해야 하며 CI 5개와 CodeQL 2개 context를 GitHub Actions app에
  고정해 필수화한다. 최신 `main` 재검증, conversation 해결과 선형 이력을 요구하고 관리자
  우회, force push와 삭제를 막는다. 승인 인원은 0명으로 둔다.
- 이유: 직접 push는 review와 gate가 완료되기 전에 기준 branch를 바꿀 수 있다. 반면 현재
  저장소는 단일 maintainer이므로 1명 승인을 요구하면 자신의 PR을 스스로 승인할 수 없어
  정상 변경도 불가능하다.
- 대안: 관리자 우회 허용, 승인 1명 강제, status check만 요구하고 PR은 선택, ruleset 사용.
- 결과: 모든 `main` 변경은 자동 검증 가능한 PR 이력으로 남는다. job 이름 변경은 protection
  context와 함께 단계적으로 이전해야 하며, 사람 승인이 필요한 조직 규모가 되면 승인 수를
  별도로 높여야 한다.
- 근거: [GitHub protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
  [branch protection REST API](https://docs.github.com/rest/branches/branch-protection#update-branch-protection).

## D-030. Compose service image는 읽을 수 있는 tag와 manifest-list digest를 함께 고정

- 결정: PostgreSQL, Redis, Prometheus와 Grafana image를 `tag@sha256:digest`로 참조한다.
  digest는 amd64와 arm64를 포함하는 상위 manifest list를 사용하고 CI가 `compose.yaml`의
  모든 명시적 image에 digest가 있는지 검사한다. 업데이트는 별도 `docker-compose`
  Dependabot 생태계가 매주 제안한다.
- 이유: tag만 사용하면 같은 commit도 실행 시점에 따라 다른 image를 받을 수 있다. 반대로
  platform별 digest를 고정하면 개발자의 arm64 환경과 CI의 amd64 환경에 서로 다른 선언이
  필요하다. tag를 함께 남기면 PostgreSQL 17·Redis 7 같은 호환성 경계도 review diff에서
  읽을 수 있다.
- 대안: mutable tag 유지, platform별 digest 분리, tag 없이 digest만 사용, 수동 업데이트.
- 결과: Compose 실행 입력은 여러 architecture에서 하나의 불변 참조로 재현된다. 새 image를
  digest 없이 추가하면 backend CI가 실패하며, tag 또는 digest 변경은 Dependabot PR에서 전체
  gate를 거친다. Redis와 Prometheus runtime 검증은 Compose 참조를 직접 사용한다. Dockerfile
  base image와 PostgreSQL GitHub Actions service container는 별도 업데이트 경계로 남는다.
- 근거: [Docker image digests](https://docs.docker.com/dhi/explore/security-concepts/digests/),
  [Dependabot options reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
- 관련: `776fa1c`, `1b1b4ba`.

## D-031. Prometheus는 최신 minor보다 지원 중인 LTS line을 추적

- 결정: Prometheus 3.5.0에서 3.13.2 LTS로 전환하고, Compose Dependabot은 3.13 line의
  patch와 digest만 자동 제안하도록 major·minor 업데이트를 제외한다. CI는 Compose의 고정
  image 참조를 단일 원본으로 읽어 `promtool` 설정·규칙 검사와 실제 server readiness를
  수행한다.
- 이유: 공식 지원 표에서 3.5의 지원 종료일은 2026-07-31이고 3.13은 2027-07-31까지
  bug·security fix를 받는다. 최신 3.14는 일반 6주 minor release지만 3.13 LTS는 기능 변경을
  제한하면서 1년간 유지된다. 3.13.2에는 `golang.org/x/text`, gRPC 보안 수정과 disk-full
  상황의 query tracker 충돌 방지가 포함된다.
- 대안: Dependabot PR #22의 3.14.0을 그대로 병합, 3.5 최신 patch만 적용, 모든 minor를 계속
  자동 제안.
- 결과: runtime과 검증 도구가 같은 immutable image를 사용하며 patch는 자동화하되 다음 LTS
  전환은 release note와 설정 호환성을 다시 검토한다. 현재 설정은 변경된 experimental duration
  expression, remote write, service discovery와 query API option을 사용하지 않는다.
- 근거: [Prometheus long-term support](https://prometheus.io/docs/introduction/release-cycle/),
  [Prometheus 3.13.0](https://github.com/prometheus/prometheus/releases/tag/v3.13.0),
  [Prometheus 3.13.2](https://github.com/prometheus/prometheus/releases/tag/v3.13.2).
- 관련: [PR #29](https://github.com/sangmu1126/PipeLens/pull/29),
  [대체한 PR #22](https://github.com/sangmu1126/PipeLens/pull/22), `5a034d5`, `72038fa`.

## D-032. Redis server는 floating major보다 Extended support line을 추적

- 결정: Redis 7.4에서 8.2 Extended line으로 전환하고, Compose Dependabot은 8.2의 patch와
  digest만 자동 제안하도록 major·minor 업데이트를 제외한다. backend CI는 별도 mutable
  service image를 사용하지 않고 Compose가 해석한 digest 참조를 직접 pull·기동해 queue
  integration test를 수행한다.
- 이유: Dependabot PR #23의 `redis:8-alpine`은 조회 시점에 8.10.1 Standard를 가리키며 이후
  minor도 자동으로 바뀐다. 공식 지원 표에서 8.2는 2030-09-01까지 Extended 지원되지만 8.10은
  EOL이 확정되지 않았다. 8.2.9는 `EVAL` ACL key 검사, 악성 RDB와 blocked-client 처리의
  memory-safety 보안 수정을 포함하고 현재 Lua queue script와 직접 관련된다.
- 대안: PR #23의 floating `8-alpine` 병합, Redis 7.4 Extended 유지, CI service의 mutable
  `redis:7-alpine`만 8로 변경.
- 결과: Compose runtime과 CI integration이 같은 multi-platform digest를 사용한다. Redis
  8.2.9의 linux/amd64·linux/arm64 manifest, healthcheck와 redis-py 8.1 RESP3 기반 queue의
  enqueue·blocking dequeue·lease·orphan recovery를 검증한다. 다음 Extended line 전환은 지원
  기간, release note와 실제 데이터 upgrade/restore drill을 다시 검토한다.
- 라이선스: 기존 Redis 7.4는 RSALv2/SSPLv1 dual-license였고 Redis 8은 여기에 OSI 승인
  AGPLv3 선택지를 추가한 tri-license다. 공식 image를 수정 없이 내부 service로 사용하며 Redis
  자체를 managed service로 제공하지 않는다. 배포 형태가 바뀌면 별도 법률 검토가 필요하다.
- 근거: [Redis version management](https://redis.io/docs/latest/operate/oss_and_stack/install/version-mgmt/),
  [Redis 8 upgrade guide](https://redis.io/docs/latest/operate/oss_and_stack/install/upgrade/),
  [Redis licenses](https://redis.io/legal/licenses/),
  [Redis 8.2.9](https://github.com/redis/redis/releases/tag/8.2.9).
- 관련: [PR #34](https://github.com/sangmu1126/PipeLens/pull/34),
  [대체한 PR #23](https://github.com/sangmu1126/PipeLens/pull/23), `fd286c2`, `9bc43ee`.

## D-033. PostgreSQL major 전환은 새 volume과 논리 복원으로 검증

- 결정: PostgreSQL 17에서 18.6으로 전환하되 기존 `postgres-data`를 직접 재사용하지 않고
  18 전용 `postgres18-data`를 `/var/lib/postgresql`에 연결한다. CI는 Compose의 고정 18
  image를 실제 integration에 사용하고, 별도 17·18 volume 사이의 `pg_dump`/`pg_restore`,
  표본 데이터와 `alembic check`를 매번 검증한다. Dependabot은 18의 patch·digest만 자동
  제안하고 다음 major는 수동 검토한다.
- 이유: PostgreSQL major data directory는 직접 호환되지 않으며 Docker Official Image도 18부터
  `PGDATA`와 volume target을 바꿨다. 같은 named volume을 새 target에 연결하면 17 data를
  보존한 채 별도 18 cluster가 초기화돼 빈 database를 정상 전환으로 오인할 수 있다.
- 대안: Dependabot PR #24를 그대로 병합, 같은 volume 이름과 기존 `/var/lib/postgresql/data`
  mount 유지, CI에서 빈 PostgreSQL 18에 migration만 적용, `pg_upgrade`만 지원.
- 결과: upgrade revision을 처음 기동해도 기존 17 volume은 보존된다. 운영자는 쓰기를 멈추고
  database backup을 새 18 volume에 복원한 뒤 서비스를 열어야 한다. CI drill은 현재 schema와
  합성 데이터만 다루므로 production 규모의 backup 내구성·복원 시간·rollback 훈련은 별도다.
- 근거: [PostgreSQL 18 release notes](https://www.postgresql.org/docs/18/release-18.html),
  [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/),
  [Docker Official Image: postgres](https://hub.docker.com/_/postgres).
- 관련: [PR #36](https://github.com/sangmu1126/PipeLens/pull/36),
  [대체한 PR #24](https://github.com/sangmu1126/PipeLens/pull/24), `3a13cff`, `791cabb`,
  [업그레이드 절차](postgres-18-upgrade.md).

## D-034. Grafana major 전환은 같은 volume의 storage migration으로 검증

- 결정: Grafana 12.1에서 13.2로 전환하고 CI가 같은 임시 `grafana-data` volume을 두 image에
  순서대로 연결한다. 12에서 생성한 비관리 dashboard 보존, 기존 file provisioning dashboard,
  Prometheus datasource UID와 익명 Viewer 접근을 13에서 확인한다. Dependabot은 지원 중인
  13.x minor·patch를 계속 제안하되 다음 major는 수동 검토한다.
- 이유: 기존 CI는 dashboard JSON 문법만 확인해 Grafana가 provisioning을 읽거나 persistent
  SQLite를 migration할 수 있는지 검증하지 않았다. Grafana 13은 folder와 dashboard를 unified
  storage로 옮기므로 기동 성공만으로 데이터 보존과 downgrade 안전성을 보장할 수 없다.
- 대안: Dependabot PR #21을 그대로 병합, 빈 Grafana 13 기동만 smoke test, Grafana 12 유지,
  major와 minor를 모두 자동 제외.
- 결과: 현재 dashboard와 datasource가 실제 Grafana 13.2에서 익명 Viewer에게 제공되고 12의
  database dashboard가 migration 뒤 유지되는지를 매 PR에서 검증한다. 13에서 12로 되돌릴 때는
  stale legacy table을 읽지 않도록 upgrade 전 backup을 복원해야 한다. CI의 작은 합성 volume은
  production backup·restore와 browser rendering 증적을 대신하지 않는다.
- 근거: [Grafana 13.0 upgrade guide](https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v13.0/),
  [Grafana upgrade strategy](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/),
  [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
- 관련: [PR #38](https://github.com/sangmu1126/PipeLens/pull/38),
  [대체한 PR #21](https://github.com/sangmu1126/PipeLens/pull/21), `70e788d`, `0ee59e2`,
  [업그레이드 절차](grafana-13-upgrade.md).

## D-035. 정식 GHCR image와 attestation은 영구 보존하고 삭제를 자동화하지 않음

- 결정: API·대시보드의 모든 SemVer release image, manifest digest와 연결된 SLSA
  provenance·CycloneDX SBOM attestation을 기간 제한 없이 보존한다. 월별 읽기 전용 감사는 두
  package의 release tag 집합, tag 형식과 digest-attestation 연결을 검증하되 삭제 권한을 갖지
  않는다. 실패한 부분 게시만 30일 격리와 참조 검사를 거쳐 version ID 단위로 수동 정리한다.
- 이유: 이전 image는 rollback 입력이며 attestation은 그 digest의 provenance와 inventory를
  증명한다. 나이 또는 개수만 기준으로 자동 삭제하면 immutable release가 참조하는 artifact와
  OCI attestation을 분리할 수 있다. 현재 release workflow는 `latest`나 개발 tag를 만들지 않아
  정식 release를 회전 삭제해서 얻는 이익도 작다.
- 대안: 최근 N개만 보존, 일정 기간 뒤 모든 untagged version 자동 삭제, 감사 없이 무기한 보존.
- 결과: 현재 `v0.1.0`과 두 package의 digest attestation tag가 자동 감사 기준선을 통과한다.
  registry tag API가 노출하지 않는 untagged version은 분기별 Packages UI·REST inventory로
  보완한다. 정책 변경 전에는 외부 archive와 rollback 보존 기간을 먼저 결정해야 한다.
- 근거: [GitHub package 삭제와 복원](https://docs.github.com/packages/learn-github-packages/deleting-and-restoring-a-package),
  [Packages REST API](https://docs.github.com/rest/packages/packages).
- 관련: `e4551ef`, [PR #41](https://github.com/sangmu1126/PipeLens/pull/41),
  [GHCR 보존 정책](ghcr-retention.md).

## D-036. Worker 확장은 합성 backlog와 실제 Redis lease 만료를 함께 검증

- 결정: backend CI의 고정 Redis에서 worker replica 4개가 합성 job 200개를 처리하게 한다.
  별도 worker가 job 하나를 claim한 뒤 ack하지 않는 장애를 만들고 2초 lease 만료 후 정확히 한
  번 복구되는지 확인한다. 모든 job은 정확히 한 번 완료돼야 하며 시작 60초, 완료 120초 SLO와
  lease+5초 복구 상한을 적용한다.
- 이유: mock queue와 단일 orphan 통합 테스트는 replica 간 분배, maintenance 경쟁, backlog 중
  lease 갱신과 최종 dedupe 정리를 함께 증명하지 못한다. 반대로 전체 GitHub·LLM pipeline 부하는
  외부 rate limit과 비용이 필요하므로 queue orchestration 회귀와 분리해야 한다.
- 대안: 단일 worker throughput만 측정, lease key를 즉시 삭제하는 단일 job 테스트만 유지,
  production E2E가 준비될 때까지 부하 검증을 생략.
- 결과: CI가 replica별 처리량, 최대 시작·완료 latency, 복구 latency와 recovery metric을
  machine-readable JSON으로 남긴다. 합성 pipeline과 in-process replica이므로 container resource
  limit, network partition, PostgreSQL pool과 provider latency를 포함한 production soak test는
  별도로 남는다. 병합 후 CI에서 200개를 49/50/50/51로 분산 처리했고 orphan 1개를 2.060초에
  복구해 최대 2.071초 안에 모두 완료했다.
- 관련: `800e531`, [PR #43](https://github.com/sangmu1126/PipeLens/pull/43),
  [Worker replica drill](worker-replica-drill.md).

## D-037. Alert routing은 실제 webhook까지 검증하되 기본 receiver는 무전송

- 결정: Prometheus가 다섯 rule을 Alertmanager 0.33.1에 전달하게 하고, Alertmanager는 UTF-8
  strict mode에서 grouping·inhibition·silence를 담당한다. 기본 `local-observer` receiver에는
  외부 integration을 두지 않는다. CI는 합성 firing rule을 별도 webhook receiver까지 전달해
  payload와 양쪽 API 상태를 검증한다.
- 이유: config 문법과 readiness만으로는 Prometheus discovery, alert 전송, route matcher와
  notification POST가 이어지는지 알 수 없다. 반면 repository에 실제 호출 URL이나 token을 넣으면
  secret 유출과 개발 환경의 오호출 위험이 생긴다.
- 대안: Alertmanager 없이 Grafana만 관측, config 정적 검사만 수행, 개발 Compose에서 실제 Slack
  또는 PagerDuty channel을 기본 receiver로 사용.
- 결과: 외부 secret 없이 전체 routing 경로를 반복 검증하면서 실제 채널 연결은 production
  secret manager와 staging 호출 증적이 필요한 별도 완료 조건으로 남는다. 0.x minor는 breaking
  가능성이 있어 0.33 patch만 자동 추적한다. 개발 Compose는 단일 replica이므로 HA gossip을
  끄며, production 다중 replica는 별도의 peer·network·deduplication 설계가 필요하다.
- 근거: [Alertmanager configuration](https://prometheus.io/docs/alerting/latest/configuration/),
  [Prometheus alerting configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/),
  [Alertmanager high availability](https://prometheus.io/docs/alerting/latest/high_availability/),
  [Alertmanager 0.33.1](https://github.com/prometheus/alertmanager/releases/tag/v0.33.1).
- 관련: `9b1c25d`, 안정화 `d49e9f7`, [PR #45](https://github.com/sangmu1126/PipeLens/pull/45),
  [PR #48](https://github.com/sangmu1126/PipeLens/pull/48),
  [Alertmanager 절차](alertmanager.md).

## D-038. 외부 GitHub Action은 release tag를 확인한 full commit SHA로 실행

- 결정: 모든 `.github/workflows`의 외부 `uses:` 참조를 40자리 commit SHA로 고정하고 사람이
  읽을 수 있는 release version을 주석으로 남긴다. local action과 `docker://` 참조만 예외로
  허용하며 backend CI가 모든 YAML workflow를 검사해 mutable tag·branch를 차단한다.
- 이유: major·version tag는 저장소 관리자나 공격자에 의해 다른 commit으로 이동할 수 있다.
  workflow는 source, package token과 release 권한을 다루므로 실행 code를 review한 commit과
  일치시켜야 한다.
- 대안: GitHub·verified creator action만 tag 허용, release workflow만 SHA 고정, repository
  설정만으로 pinning을 강제하고 저장소 내부 검사를 두지 않음.
- 결과: CI, CodeQL, release와 GHCR 감사의 외부 action 참조가 모두 immutable해지고 Dependabot
  update는 SHA와 version 주석을 함께 검토하는 PR로 유지된다. 저장소 설정의 SHA 강제 정책은
  관리자 UI/API 권한과 별도로 확인해야 한다.
- 근거: [GitHub Actions secure use reference](https://docs.github.com/en/actions/reference/security/secure-use),
  [GitHub Actions repository settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository).
- 관련: `ops/ci/verify_action_pinning.py`.

## D-039. OAuth token 암호화 키는 primary-first key ring으로 교체

- 결정: `PIPELENS_TOKEN_ENCRYPTION_KEY`를 새 암호화에 쓰는 primary로 두고, 쉼표로 구분한
  `PIPELENS_TOKEN_ENCRYPTION_FALLBACK_KEYS`는 복호화에만 사용한다. fallback으로 읽은 token은
  인증 시 primary로 즉시 재암호화한다. rolling deployment는 기존 primary+새 fallback을 먼저
  전체 배포한 뒤 새 primary+기존 fallback으로 전환한다.
- 이유: 단일 Fernet key를 즉시 바꾸면 DB의 기존 GitHub OAuth token을 해독할 수 없어 모든
  session이 예고 없이 끊긴다. 반대로 fallback을 영구 유지하면 폐기한 key의 노출 범위가 줄지
  않는다. 양쪽 key를 먼저 배포하고 session TTL 뒤 이전 key를 제거하면 혼합 version rollout과
  기존 session을 모두 다룰 수 있다.
- 대안: 교체 때 모든 session 즉시 폐기, DB의 모든 token을 일괄 offline migration, 이전 key를
  기한 없이 유지.
- 결과: 새 로그인은 항상 primary를 사용하며 기존 session은 접근 시 점진적으로 이동한다.
  이전 key 제거 시 아직 해독할 수 없는 session은 삭제된다. 실제 secret manager 연결과
  production rotation drill은 별도 외부 완료 조건으로 유지한다.
- 근거: [cryptography MultiFernet](https://cryptography.io/en/latest/fernet/),
  [GitHub App private key 관리](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps),
  [GitHub App webhook 사용](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/using-webhooks-with-github-apps),
  [GitHub App webhook 재전달](https://docs.github.com/en/rest/apps/webhooks).
- 관련: `src/pipelens/auth.py`, [비밀값과 키 교체](secrets-and-rotation.md).
