# 개발 연혁

## 기록 범위

이 문서는 Git commit graph와 현재 코드를 기준으로 2026-08-28부터 2026-08-29까지의 개발
흐름을 재구성한다. 커밋 메시지에서 확인되지 않는 개인적 동기는 기록하지 않는다. 아래
hash는 모두 `main` 이력에 존재한다.

## 2026-08-28: 핵심 수직 슬라이스

### 저장소와 실행 가능한 골격

- `a1fd71d Initial commit`: GitHub에서 MIT `LICENSE`만 포함한 원격 저장소가 먼저 생성됐다.
- `e291337 chore: bootstrap PipeLens backend`: FastAPI 애플리케이션, 설정, 기본 테스트와
  Python packaging을 추가했다.

첫 구현 목표는 넓은 UI나 운영 기능보다 webhook을 받아 진단 결과를 만드는 실행 가능한
백엔드 경로였다.

### 근거 우선 분석 코어

- `c5b7ecd`: 로그 정제, secret 마스킹, 최초 오류 추출, 규칙 분류와 근거 검증을 추가했다.
- `b55b8b4`: 실패한 `workflow_run` webhook과 GitHub 로그 수집을 연결했다.
- `76bfe20`: delivery/run 중복 처리와 저장 동작을 테스트로 고정했다.
- `3796880`: PR·commit 변경 파일과 실패 로그의 연관 점수화를 추가했다.
- `cd8f53a`: 교체 가능한 LLM adapter, Structured Outputs, ground 검증과 fallback을 추가했다.
- `a74d414`: webhook·분석·오류 범주·redaction·LLM 지표를 Prometheus로 노출했다.

이 단계에서 제품 핵심 문장인 “요약이 아니라 로그·코드·workflow를 교차 검증하는 진단”이
구현 구조로 확정됐다.

### 비동기 실행과 영속성

- `bed9d38`: 메모리/Redis queue abstraction과 독립 worker를 도입했다.
- `1e6c50c`: 메모리 저장을 SQLAlchemy 계층으로 교체했다.
- `9e4005b`: PostgreSQL, Alembic migration과 Compose service를 추가했다.
- `80f9803`: 정확도·제안 해결 여부 피드백 저장을 추가했다.

로컬에서는 SQLite·메모리 queue를 유지하면서 Compose에서는 PostgreSQL·Redis를 쓰는 두
실행 모드를 갖게 됐다.

### 대시보드와 사용자 경계

- `87dbbfb`: React 분석 이력·상세 대시보드를 추가했다.
- `cb53cad`: GitHub OAuth 로그인, 암호화된 token과 session을 추가했다.
- `acc5c86`: 분석 API를 사용자의 installation 접근 범위로 제한했다.
- `8d1b4f0`: 대시보드에 로그인·App 설치 흐름을 연결했다.

### GitHub 게시와 fork 보안

- `49042a1`: workflow run ID marker를 이용한 멱등 Check 게시를 추가했다.
- `3d61ee3`: PR 연결 실행에는 PR 코멘트를 게시하도록 확장했다.
- `7c37954`: GitHub 게시물에 분석 상세 페이지 딥링크를 추가했다.
- `d6ea6b6`: head/base 저장소를 비교해 외부 fork를 판별했다.
- `0e43a7e`: 외부 fork의 로그·diff·workflow를 LLM과 안전하지 않은 Check 게시에서
  격리했다.
- `819e994`: 같은 trust boundary를 대시보드와 게시 결과에 표시했다.

### 실행 위치 정밀화

- `6e71995`: 실패 job 안의 실패 step과 runner 정보를 수집했다.
- `ecc7aef`: 실패 step을 저장 결과와 UI에 표시했다.

## 2026-08-29: 신뢰성·운영성 완성

### 비교 범위와 분석 이력

- `3388c61`: PR이 없을 때 직전 성공 실행 이후의 변경을 비교하도록 확장했다.
- `fa3d0fa`: baseline SHA와 비교 범위를 결과에 노출했다.
- `2bc04d9`, `5d2c9a3`: 여섯 분석 단계의 시작·완료·실패 이력을 저장하고 pipeline에
  연결했다.
- `c753a9b`: 단계 진행 상태와 소요 시간을 대시보드에 표시했다.

### 큰 로그와 정량 평가

- `94d7dbf`: 큰 로그를 chunk 단위로 마스킹하고 오류 구간을 선택하는 전처리를 추가했다.
- `af74c93`: chunk 전처리를 실제 pipeline과 metrics에 연결했다.
- `60670ca`: 10개 요구 오류 범주의 고정 평가 fixture와 runner를 추가했다.
- `b05e687`: GitHub Actions에서 80% 정확도 기준을 필수 gate로 만들었다.

### 외부 API 재시도

- `0a83ada`: 최대 횟수·지연 상한이 있는 지수 backoff와 jitter 정책을 추가했다.
- `b7fbf6c`: GitHub와 OpenAI의 일시적 408, 429, 5xx에 정책을 적용했다.
- `5c78f37`: `Retry-After`, rate-limit 판별, 설정과 retry metrics를 확장했다.

403 전체를 재시도하지 않고 GitHub rate-limit 근거가 있을 때만 재시도하며, quota·billing
등 사용자 조치가 필요한 응답은 빠르게 실패하도록 구분했다.

### Redis lease, 복구와 fencing

- `6eecb8d`: worker별 processing queue와 lease를 도입했다.
- `1197d5d`: heartbeat 유지와 만료된 orphan 작업 복구를 추가했다.
- `df87f23`: run ID queue 중복 제거를 추가했다.
- `643b6cf`: DB 저장과 queue 전달 사이 장애를 startup/webhook reconciliation으로 복구했다.
- `b9766ac`: 분석 attempt token을 저장하는 fencing을 추가했다.
- `b800c16`: superseded pipeline이 상태 변경이나 GitHub 게시를 계속하지 못하게 했다.

이 순서는 단순 재시도에서 멈추지 않고, multi-worker에서 발생할 수 있는 “lease가 끝난 이전
worker가 뒤늦게 성공하는 문제”까지 다룬 기록이다.

### 실행 context와 SLO

- `83e3046`: workflow name, branch, runner labels와 실패 step을 수집했다.
- `fad0526`: 실행 context를 마스킹 후 저장했다.
- `d7f4e95`: 대시보드에 실행 context를 표시했다.
- `0582041`: 최초 분석 시작, 완료, queue wait와 전체 latency를 저장했다.
- `99dea64`: 60초 시작·120초 완료 SLO 결과와 histogram을 기록했다.
- `7a4ff97`: latency breakdown을 대시보드에 표시했다.

### readiness와 관측 스택

- `adc7c3f`: DB와 queue를 검사하는 `/readyz`를 추가했다.
- `420d437`: API readiness 이후 대시보드를 시작하도록 Compose dependency를 조정했다.
- `c037575`: PostgreSQL·Redis 통합 테스트를 추가했다.
- `8462d52`: CI에 실제 PostgreSQL·Redis service 검증을 추가했다.
- `aeeba38`: 서비스 중단, SLO 위반과 queue backlog Prometheus rule을 정의했다.
- `6afc3cb`: Grafana datasource·dashboard provisioning을 추가했다.

### 분석 탐색 UX와 접근성

- `bd6c290`, `4777924`: 분석 목록과 대시보드에 status/category/repository 필터를 추가했다.
- `beed7fc`, `bf0691f`: cursor pagination과 과거 결과 추가 로딩을 구현했다.
- `7c5e21f`, `41ce378`: 주요 대시보드 사용자 흐름 테스트를 만들고 CI gate에 포함했다.
- `fa8fd5e`, `c515877`: label, landmark, live region과 키보드 탐색 semantics를 개선하고
  회귀 테스트를 추가했다.

### 원격 이력 합류와 호환성 수정

- `777c8ad`: 로컬 개발 이력과 GitHub에서 먼저 만들어진 `a1fd71d` LICENSE 이력을 merge했다.
  서로 다른 root history 때문에 단순 push가 되지 않았고, LICENSE 이력을 보존하는 merge로
  해결했다.
- `5d50434`: Python 3.12에서 store type annotation 평가 시점을 늦춰 호환성을 복구했다.
- `8b14e83`: 중복 installation dependency 제약을 제거했다.

### CI·보안·의존성 유지보수

- `bdef6f6`: GitHub Actions runtime major를 갱신했다.
- `5b399d3`: production에서 HTTPS, 인증, Secure cookie와 충분한 secret을 fail-fast 검증했다.
- `c036e58`: API와 Nginx 응답 보안 헤더를 추가했다.
- `8bfb840`: pip, npm, GitHub Actions Dependabot 주간 업데이트를 구성했다.
- `cea7bde`부터 `673be92`: Alembic, Pydantic Settings, pytest 계열, Vite, React plugin,
  PyJWT와 FastAPI 업데이트를 각각 분리 반영했다.
- `fd6d141`: TypeScript 7/Vite 8 빌드를 위해 Vite client type 선언을 명시했다.
- `6a5d2ea`: Python과 JavaScript/TypeScript CodeQL 분석을 추가했다.
- `6fc8d83`: API·대시보드 Dockerfile 실제 빌드를 CI에 추가했다.
- `b7d6833`: allowlist `.dockerignore`로 secret·개발 산출물을 build context에서 제외했다.
- `e6ee9d8`: API 이미지를 `pipelens` 비권한 사용자로 전환하고 CI가 최종 USER를 검사하게
  했다.
- `92e11f8`: 대시보드를 NGINX 비권한 이미지와 8080 포트로 전환하고 실제 HTTP smoke test를
  추가했다.
- `d72d4da`: API와 대시보드 Dockerfile의 base image를 Dependabot 주간 업데이트 대상에
  추가하고 대시보드의 Node·Nginx 변경을 하나의 검증 가능한 PR로 묶었다.
- `4d371c6`: Python 지원 범위를 3.12 이상 3.15 미만으로 명시하고 3.14 호환성 job과 API
  컨테이너 `/readyz` smoke test를 CI에 추가했다.

## 현재까지의 검증 방식

개발 과정에서 다음 gate가 누적됐다.

- Ruff 정적 lint
- 백엔드 단위·API·migration 테스트
- PostgreSQL과 Redis 실제 service 통합 테스트
- 10개 진단 fixture의 80% 정확도 gate
- Vitest 대시보드 사용자 흐름·접근성 테스트
- TypeScript와 Vite production build
- Prometheus config와 Compose config 검증
- API·대시보드 컨테이너 빌드, 최종 USER 검사와 대시보드 HTTP smoke test
- Python·JavaScript/TypeScript CodeQL

## 아직 기록할 수 없는 것

다음은 코드나 자동화는 존재하지만 실제 외부 환경 결과가 아직 저장소 이력에 없다.

- GitHub App을 실제 저장소에 설치한 종단 간 실행
- 실제 실패 workflow에 대한 PR 코멘트·Commit Check 게시 결과
- 실제 OpenAI 호출의 품질·token·비용 결과
- production HTTPS 환경의 OAuth callback과 webhook 수신
- 장시간·고동시성 부하에서 60초/120초 SLO 달성률
- 첫 version tag, GitHub Release와 registry 이미지

이 항목은 완료로 간주하지 않으며 [검증 및 운영 준비 현황](readiness.md)에서 후속 작업으로
관리한다.
