# 개발 연혁

## 기록 범위

이 문서는 Git commit graph와 현재 코드를 기준으로 2026-08-28부터 2026-08-30까지의 개발
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
- `95b9970`: 새 Python 3.14 compatibility와 API 기동 gate를 통과한 뒤 API runtime image를
  `python:3.14-slim`으로 갱신했다.

## 2026-08-30: runtime 지원 경계 정리

- `1f90715`: 대시보드 package에 Node 22·24 LTS 지원 범위를 명시하고 Dependabot이 LTS 전환
  전 Node major를 자동 제안하지 않도록 했다. CI의 Node 22와 Docker build의 Node 24가 지원
  범위 양 끝을 각각 검증한다.
- `afff1ec`: 새 정책으로 재생성된 Dependabot PR #17에서 Node 24는 유지하고 Nginx
  unprivileged runtime만 `1.29-alpine`에서 `1.31-alpine`로 갱신했다. 전체 CI, container
  non-root·HTTP smoke test와 CodeQL 통과 뒤 squash merge했다.
- `e6016f0`: 개발 전용 lint 도구 Ruff의 최소 버전을 0.8에서 0.16.4로 올렸다. 최신 `main`
  기반 PR에서 전체 CI와 CodeQL을 통과했고, 로컬 Ruff 0.16.5 검사, 백엔드 105개 테스트와
  진단 fixture 10/10을 추가 확인한 뒤 squash merge했다.
- `47d2c60`: GitHub·OpenAI client와 retry 계층이 사용하는 HTTPX의 최소 버전을 0.27에서
  0.28.1로 올렸다. 제거된 `app`·`proxies` 인자를 사용하지 않음을 확인하고 관련 client,
  retry와 API 테스트 38개 및 최신 `main` 전체 CI·CodeQL 통과 뒤 squash merge했다.
- `a117d2b`: API·worker metrics에 사용하는 Prometheus client의 최소 버전을 0.21에서
  0.26.0으로 올렸다. 독립 CollectorRegistry 사용을 확인하고 metrics·pipeline·worker·webhook
  테스트 18개와 진단 fixture 10/10, 최신 `main` 전체 CI·CodeQL 통과 뒤 squash merge했다.
- `2ab347d`: cryptography major 업데이트 전에 GitHub App private key의 escaped newline 복원,
  RS256 JWT 서명과 공개키 검증을 직접 수행하는 회귀 테스트를 추가했다.
- `448565c`: Fernet token 암호화와 GitHub App JWT 서명에 사용하는 cryptography의 지원
  범위를 44–46에서 50.0.1–50로 갱신했다. OAuth/Fernet·GitHub client·production 설정 테스트
  27개와 진단 fixture 10/10, 최신 `main` 전체 CI·CodeQL 통과 뒤 squash merge했다.
- `b8c5cf2`: SQLite·PostgreSQL 저장 계층과 Alembic이 사용하는 SQLAlchemy 최소 버전을
  2.0에서 2.0.52로 올렸다. 로컬 SQLite 포함 106개 테스트와 GitHub Actions의 실제
  PostgreSQL 17 migration·analysis lifecycle integration, 전체 CI·CodeQL 통과 뒤 squash
  merge했다.
- `ec7105c`: API·대시보드 이미지를 빌드한 직후 fixable HIGH/CRITICAL OS·language package
  취약점을 차단하는 Trivy gate를 추가했다. Action은 v0.36.0의 검증된 commit SHA로 고정했다.
  첫 실행은 대시보드 Alpine과 API Debian의 OpenSSL `CVE-2026-14456`, API image에 남은
  msgpack `GHSA-6v7p-g79w-8964`와 setuptools `CVE-2025-47273`을 검출해 의도대로 실패했다.
- `89ffa86`: API image build에서 Debian 보안 업데이트를 적용하고 설치가 끝난 뒤 runtime에
  불필요한 pip·setuptools를 제거했다. 대시보드 runtime에는 Alpine 보안 업데이트를 적용했다.
  같은 gate 재실행에서 두 이미지가 취약점 scan, non-root USER 검사와 HTTP readiness/smoke
  test를 모두 통과했다.
- `c4d362e`: 같은 실제 빌드 image에서 CycloneDX JSON SBOM을 생성하고 형식·component 존재를
  검증한 뒤 image별 CI artifact로 14일간 보관하도록 했다. 첫 성공 실행에서 내려받은 CycloneDX
  1.6 문서는 API 125개, 대시보드 71개 component를 포함했다. Trivy v0.36.0과
  `upload-artifact` v7.0.1은 검증한 commit SHA로 고정했다.
- `d7e600c`: `main`의 semantic version tag에서 API·대시보드 image를 검증한 뒤 GHCR에
  게시하고, 확정 digest에 SLSA provenance와 CycloneDX SBOM attestation을 서명하는 release
  workflow를 추가했다. mutable `latest`는 만들지 않고 version tag와 digest만 게시한다.
- `ed83890`: Python과 대시보드 manifest뿐 아니라 npm lockfile의 root·workspace version도
  release tag와 일치해야 게시하도록 검증 범위를 보강했다.
- `f5e059d`: 공식 attestation parser가 요구하는 CycloneDX serial number를 일반 CI와 release
  양쪽에서 사전 검증하도록 보강했다. 기존 CI artifact에도 실제 UUID가 있음을 확인했다.

### 첫 서명 릴리스

- annotated `v0.1.0` tag를 녹색 CI·CodeQL을 통과한 `320f6ae`에 고정했다.
- release run `33273157722`에서 tag/version/main ancestry와 API·대시보드의 취약점, SBOM,
  non-root, readiness/HTTP smoke gate가 모두 성공했다.
- API digest `sha256:112003409a48ce010538136489d85ee590ca964970253bc67700882624042c14`와
  대시보드 digest `sha256:3a05962e01285ed71fc7a9b0ead8ea90a9c63c706a072677258694d43f616296`를
  GHCR에 게시했다. 빈 Docker 인증 설정에서도 두 manifest를 조회했다.
- 각 digest의 SLSA provenance와 CycloneDX SBOM을 GitHub API와 GHCR OCI referrer 양쪽에서
  repository·signer workflow·source tag를 제한해 검증했다. 서명된 SBOM은 API 125개,
  대시보드 71개 component를 포함한다.
- 모든 검증 뒤 [PipeLens v0.1.0](https://github.com/sangmu1126/PipeLens/releases/tag/v0.1.0)을
  게시했다. release immutability를 미리 활성화하지 않아 API상 `immutable: false`이며 다음
  release 전에 별도 설정이 필요하다.

이 결정은 Node 26과 Nginx 1.31을 함께 올리던 Dependabot PR #11을 그대로 merge하지 않고,
Node 26은 공식 LTS 전환 뒤 별도로 검토하며 Nginx 변경만 PR #17로 다시 생성하도록 만들기
위해 내려졌다.

이 시점에 Docker 2개와 Python dependency 5개로 시작한 첫 Dependabot 검토 사이클은 모두
처리됐다. Node 26은 LTS 정책에 따라 제외했고 나머지는 검증 뒤 merge했으며, 함께 제안됐던
Nginx는 별도 PR로 분리했다.

## 현재까지의 검증 방식

개발 과정에서 다음 gate가 누적됐다.

- Ruff 정적 lint
- 백엔드 단위·API·migration 테스트
- PostgreSQL과 Redis 실제 service 통합 테스트
- 10개 진단 fixture의 80% 정확도 gate
- Vitest 대시보드 사용자 흐름·접근성 테스트
- TypeScript와 Vite production build
- Prometheus config와 Compose config 검증
- API·대시보드 컨테이너 빌드, 최종 USER 검사와 API readiness·대시보드 HTTP smoke test
- 실제 빌드 이미지의 fixable HIGH/CRITICAL OS·language package 취약점 gate
- 실제 빌드 이미지의 CycloneDX SBOM 생성·내용 검증·artifact 보관
- Python·JavaScript/TypeScript CodeQL

## 아직 기록할 수 없는 것

다음은 코드나 자동화는 존재하지만 실제 외부 환경 결과가 아직 저장소 이력에 없다.

- GitHub App을 실제 저장소에 설치한 종단 간 실행
- 실제 실패 workflow에 대한 PR 코멘트·Commit Check 게시 결과
- 실제 OpenAI 호출의 품질·token·비용 결과
- production HTTPS 환경의 OAuth callback과 webhook 수신
- 장시간·고동시성 부하에서 60초/120초 SLO 달성률

이 항목은 완료로 간주하지 않으며 [검증 및 운영 준비 현황](readiness.md)에서 후속 작업으로
관리한다.
