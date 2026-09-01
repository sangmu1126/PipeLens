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
- `73e4641`: SQLAlchemy의 PostgreSQL dialect가 사용하는 `psycopg[binary]` 최소 버전을
  3.2에서 3.3.4로 올렸다. [공식 설치 지원 범위](https://www.psycopg.org/psycopg3/docs/basic/install.html)가
  Python 3.10–3.14와 PostgreSQL 10–18이므로 PipeLens의 Python 3.12–3.14·PostgreSQL 17을
  포함한다. [3.3 release note](https://www.psycopg.org/psycopg3/docs/news.html)의 adapter startup
  race, 장기 uptime 환경의 spurious connection timeout, quoted enum adaptation과
  `executemany()` status message 수정을 검토했으며 PipeLens는 새 template-string query API를
  사용하지 않는다.
- 로컬은 psycopg와 psycopg-binary 3.3.4, binary implementation과 bundled libpq 18을 확인하고
  전체 106개 테스트를 통과했다. 최신 `main`으로 rebase한 PR #26의 CI `33294950950`은
  CPython 3.12용 binary wheel을 설치해 전체 106개 테스트와 실제 PostgreSQL 17·Redis 통합
  2개를 통과했고 Python 3.14 compatibility, API image readiness와 CodeQL도 성공했다. 병합 후
  `main` CI `33295005385`와 CodeQL `33295005394`도 다시 성공했다.
- `3b0b203`: ASGI server `uvicorn[standard]`의 최소 버전을 0.30에서 0.52.4로 올렸다.
  [공식 release notes](https://www.uvicorn.org/release-notes/)에서 0.32의 Python 3.13 지원,
  0.38의 Python 3.14 지원과 0.40의 Python 3.9 지원 종료를 확인했다. PipeLens 지원 범위는
  Python 3.12 이상 3.15 미만이므로 하한 종료의 영향이 없고 3.14 지원은 현재 API runtime과
  일치한다.
- 0.30 이후 제거된 WatchGod reload와 `Config.setup_event_loop`, deprecated `ServerState`,
  worker 재시작·TLS option은 사용하지 않는다. Dockerfile은 `pipelens.main:app`, host와 port만
  전달하며 reload·다중 worker·직접 TLS를 활성화하지 않는다. 0.50부터 기본 WebSocket 구현이
  `websockets-sansio`로 바뀌었지만 현재 WebSocket route가 없고, 0.52의 experimental `zttp`
  HTTP 구현도 명시적으로 선택하지 않아 기존 `auto` HTTP 경로를 유지한다.
- 로컬과 CI가 실제로 해석한 조합은 Uvicorn 0.52.4, httptools 0.8.0, websockets 17.1이다.
  최신 `main`으로 rebase한 [PR #25](https://github.com/sangmu1126/PipeLens/pull/25)의 CI
  `33295968358`은 Python 3.12 전체 106개 테스트, PostgreSQL 17·Redis 통합 2개, Python
  3.14 compatibility, API image 취약점 0건과 실제 `/readyz` 기동을 통과했다. CodeQL
  `33295968363`도 성공했고 병합 후 `main` CI `33296035915`와 CodeQL `33296035880`에서 같은
  커밋을 다시 검증했다.
- `7258f5c`: 비동기 분석 queue가 사용하는 redis-py 최소 버전을 5.2에서 8.1.0으로 올렸다.
  [redis-py 6.0 release](https://github.com/redis/redis-py/releases/tag/v6.0.0)의 standalone
  retry 기본값, SSL hostname 검증, 제거된 `charset`·`errors` 인자와
  [7.0 release](https://github.com/redis/redis-py/releases/tag/v7.0.0)의 cluster·Sentinel 변경을
  검토했다. PipeLens는 standalone plain Redis URL과 `decode_responses=True`만 사용하며
  cluster, Sentinel, TLS client option이나 제거 인자를 사용하지 않는다.
- [redis-py 8.0 release](https://github.com/redis/redis-py/releases/tag/v8.0.0)부터 기본 wire
  protocol은 RESP3지만 기존 RESP2-compatible Python response shape가 기본으로 보존된다.
  PipeLens가 사용하는 `PING`, `EVAL`, `BRPOPLPUSH`, transaction pipeline, `SMEMBERS`, `LLEN`과
  close 경로를 실제 integration test로 확인해 별도 `protocol=2` 고정 없이 RESP3 기본값을
  채택했다. socket·connect timeout은 5초, connection pool은 100개, retry는 exponential
  jitter 10회가 새 기본값이다. worker의 blocking pop timeout은 항상 1초라 socket timeout보다
  짧지만, 고동시성에서 pool·retry가 만드는 지연은 아직 production 부하 검증 대상이다.
- Compose digest가 가리키는 server는 Redis 7.4.11이며 redis-py 8.1의 공식 지원 범위인 Redis
  7.2 이상에 포함된다. [8.1 release](https://github.com/redis/redis-py/releases/tag/v8.1.0)의
  async maintenance notification과 신규 command는 현재 사용하지 않는다. 최신 `main`으로
  rebase한 [PR #27](https://github.com/sangmu1126/PipeLens/pull/27)의 CI `33299569088`은
  redis-py 8.1.0으로 Python 3.12 전체 106개 테스트와 Redis 7.4·PostgreSQL 17 통합 2개,
  Python 3.14 전체 106개, API image 기동과 redis package 취약점 0건을 확인했다. CodeQL
  `33299569060`, 병합 후 `main` CI `33299653576`과 CodeQL `33299653632`도 같은 변경을
  검증했다.
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
  release에는 소급 적용할 수 없다.

### GitHub Release 불변성 활성화

- 2026-08-30 repository 설정 API를 먼저 조회해 release immutability가 `enabled: false`임을
  확인했다. 기존 `v0.1.0`도 `draft: false`, `immutable: false`였다.
- 공식 문서의 미래 release만 보호한다는 적용 범위를 확인한 뒤 repository 설정 API로 불변성을
  활성화했다. 재조회 결과는 `enabled: true`, `enforced_by_owner: false`였다.
- 기존 release를 삭제하거나 다시 만들지 않았다. `v0.1.0`은 계속 `immutable: false`로 기록하고,
  차기 release부터 note와 asset을 draft에서 완성한 뒤 한 번만 publish하도록 운영 절차를 바꿨다.
- 차기 release 완료 조건에는 Release API의 `immutable: true`와 자동 release attestation 확인을
  포함했다. GHCR image attestation과 GitHub Release 불변성은 계속 별도 증적으로 판정한다.

### GHCR 보존 정책과 월별 감사

- 공개 registry를 직접 조회하니 API·대시보드 package 모두 `v0.1.0`과 release digest에 연결된
  `sha256-<digest>` attestation tag 하나씩만 가지고 있었다. 두 SemVer 집합과 digest 연결은
  일치했다.
- 정식 SemVer image, digest와 SLSA provenance·CycloneDX SBOM OCI attestation을 기간 제한 없이
  보존하기로 했다. `latest`나 개발 tag를 게시하지 않으므로 개수·나이 기반 자동 삭제는 rollback
  과 공급망 증적을 잃는 위험에 비해 이익이 작다고 판단했다.
- `e4551ef`: 공개 pull token으로 두 package의 tag 집합과 각 release manifest digest를 읽고,
  SemVer 대응·예상 밖 tag·attestation 누락과 고아 tag를 판정하는 감사기와 단위 테스트 6개를
  추가했다. 월별 workflow는 `contents: read`만 가지며 삭제 API를 호출하지 않는다.
- registry tag API에 나타나지 않는 untagged version은 분기별 Packages UI·REST inventory로
  보완한다. 실패한 부분 게시를 발견해도 30일 격리, 참조 검사와 version ID 기록 없이 삭제하지
  않으며 GitHub의 삭제 후 30일 복구 경계를 운영 절차에 포함했다.
- [PR #41](https://github.com/sangmu1126/PipeLens/pull/41)의 CI `33322207726`과 CodeQL
  `33322207722`가 통과한 뒤 구현 `e4551ef`와 문서 `eb9724f`를 rebase merge했다. 병합된
  `main`에서 수동 감사 `33322294819`를 실행해 두 package의 `v0.1.0`과 digest attestation
  연결이 GitHub-hosted runner에서도 통과함을 확인했다.

### Worker replica 부하와 lease 장애 복구

- 기존 검증은 Redis job 하나의 lease key를 직접 지우고 다른 queue가 복구하는 수준이었다.
  여러 worker가 backlog를 나눠 처리할 때의 processing list 경쟁, 실제 TTL 만료, 중복 처리와
  사용자 SLO는 함께 측정하지 않았다.
- `800e531`: 합성 요청 200개 중 하나를 `abandoned` worker가 claim한 뒤 ack하지 않고, 독립 Redis
  connection·processing list·lease를 가진 replica 4개가 나머지와 회수된 job을 처리하는 CI
  drill을 추가했다. lease 2초와 heartbeat 0.5초를 실제 시간으로 사용한다.
- 모든 run의 시작·완료가 정확히 한 번인지, replica가 모두 작업에 참여했는지, recovery metric이
  1인지, pending·dedupe가 비었는지 검증한다. 최대 시작 60초·완료 120초와 orphan lease+5초를
  상한으로 적용하고 결과를 JSON으로 남긴다.
- 합성 pipeline은 job당 10ms만 사용하고 container resource limit, 실제 GitHub·LLM,
  PostgreSQL pool과 network partition은 다루지 않는다. 이 경계는 production soak/load 후속
  작업으로 유지한다.
- [PR #43](https://github.com/sangmu1126/PipeLens/pull/43)의 첫 CI `33323312380`에서 200개가
  replica별 49/50/50/51개로 분배됐다. 실제 TTL 만료 뒤 orphan 1개를 2.096초에 회수했고 최대
  시작 2.096초, 완료 2.107초로 60초/120초 SLO와 정확한 1회 처리·최종 queue drain을 통과했다.
  CodeQL `33323312384`도 성공했다.
- 구현 `800e531`, 절차 `1ddce3e`, 첫 증적 `49a7a76`을 rebase merge했다. 병합 후 CI
  `33323532906`은 같은 분배에서 orphan을 2.060초에 복구하고 최대 2.071초에 완료했으며 CodeQL
  `33323532969`도 성공했다.

### Alertmanager routing과 webhook 통합 검증

- 기존 Prometheus에는 다섯 alert rule이 있었지만 Alertmanager endpoint가 없었다. rule 문법과
  Prometheus readiness만 확인해 alert가 notification receiver까지 전달되는지는 검증하지 못했다.
- 공식 최신 stable 0.33.1 image의 multi-platform digest와 amd64·arm64를 확인했다. 신규 설치
  권고에 맞춰 UTF-8 strict mode를 사용하고 0.x minor는 자동 업데이트하지 않도록 경계를 뒀다.
- `9b1c25d`: Compose에 digest-pinned Alertmanager, persistent volume과 readiness를 추가하고
  Prometheus가 `alertmanager:9093`으로 rule을 전송하게 했다. 기본 receiver는 외부 integration이
  없어 개발 실행이 실제 호출을 만들지 않는다.
- CI drill은 격리 network에서 `vector(1)` critical alert를 firing하고 Prometheus→Alertmanager→
  일회성 webhook receiver의 JSON POST를 확인한다. Prometheus API의 firing, Alertmanager API의
  active 상태와 payload label·annotation까지 검증한 뒤 container, network와 payload를 정리한다.
- 실제 PagerDuty·incident.io·Slack 등 조직 채널은 token을 repository에 저장하지 않고
  production secret manager로 주입해야 한다. staging firing/resolved 호출과 acknowledgment
  증적 전에는 외부 채널 연결을 완료로 기록하지 않는다.
- [PR #45](https://github.com/sangmu1126/PipeLens/pull/45)의 첫 CI `33325807628`에서는 fixture
  config가 mount된 단일 probe 파일 대신 production rule glob을 가리켜 Prometheus가 rule 0개로
  기동했고 webhook 수신이 시간 초과됐다. fixture의 `rule_files`를 실제 mount 경로로 교정해
  실패 원인을 구현 commit에 autosquash했다.
- 재실행 CI `33325903043`은 `amtool` config 2개, `promtool` config 1개·rule 1개를 확인하고
  합성 alert가 Prometheus→Alertmanager→webhook 경로를 통과했음을 기록했다. payload와 두 API
  상태를 검증했으며 CodeQL `33325903025`를 포함한 필수 gate 7개가 모두 성공했다. 이후 drill에
  Compose가 선언한 `amtool config show` healthcheck 명령 검증도 추가했다. 최종 CI
  `33326106111`과 CodeQL `33326106102`가 이 보강을 포함해 다시 성공했다.
- rebase merge 후 `main` CI `33326887437`은 Alertmanager가 기본 HA gossip settle에 10초를
  사용한 뒤 30초 절대 제한 안에 webhook을 보내지 못해 실패했다. 단일 replica에서 기본
  clustering을 유지할 이유가 없으므로 공식 권고대로 `--cluster.listen-address=`를 적용하고,
  receiver 제한을 60초로 늘려 느린 runner에서도 전체 경로 자체를 판정하도록 교정했다.
- 안정화 구현 `d49e9f7`과 문서 `d1d4079`는
  [PR #48](https://github.com/sangmu1126/PipeLens/pull/48)에 rebase merge됐다. 병합 후 `main` CI
  `33327158576`은 라우팅 단계를 포함한 전체 gate를 통과했고 CodeQL `33327158575`도 성공했다.
- GitHub Actions SHA 고정 PR #51의 첫 CI `33361428377`에서는 두 service가 즉시 준비됐지만
  webhook payload가 60초 안에 도착하지 않았다. 기존 실패 출력은 container log뿐이라
  Prometheus 평가, Alertmanager 수신과 host webhook 전달 중 정지 구간을 구분할 수 없었다.
- `5764bc3`: receiver가 socket을 bind했다는 준비 신호를 기다리고 전체 상한을 180초로 늘렸다.
  Prometheus readiness와 합성 alert의 firing, Alertmanager의 active 상태를 각각 독립된 제한으로
  순서대로 검사하며, 상태 실패에는 마지막 API 응답과 해당 container log를 남긴다. predicate
  회귀 테스트 4개를 추가했고 로컬 전체 결과는 121 passed, 2 skipped였다. 로컬 Docker daemon은
  실행 중이지 않아 실제 종단 간 결과는 PR #51 CI에서 판정했다. run `33361752707`에서
  Prometheus firing, Alertmanager active와 webhook payload를 순서대로 확인해 통과했다.

### Ruff 0.16.5와 setup-python 7 유지보수

- [PR #46](https://github.com/sangmu1126/PipeLens/pull/46)은 개발 lint 하한을 Ruff 0.16.4에서
  0.16.5로 올렸다. preview category·기본 규칙 변경은 현재 비-preview 선택 규칙에 영향을 주지
  않았고 로컬 Ruff 0.16.5, 전체 115개 테스트와 최신 `main` 기반 CI `33327919399`·CodeQL
  `33327919385`를 통과했다. `d80ecff`로 squash merge한 뒤 `main` CI `33328022359`와 CodeQL
  `33328022350`도 성공했다.
- [PR #47](https://github.com/sangmu1126/PipeLens/pull/47)은 Python 3.12 backend와 Python 3.14
  compatibility job의 `actions/setup-python`을 v7.0.0으로 좁히고, GHCR 감사 workflow는 공식
  release commit `5fda3b95a4ea91299a34e894583c3862153e4b97`로 고정했다. v7의 Node 24 runtime과 제거된
  `pip-install` 입력을 검토했으며 PipeLens는 해당 입력을 사용하지 않는다.
- PR CI `33328357773`과 CodeQL `33328357775`가 두 Python 경로를 통과했고, PR branch의 수동
  GHCR 감사 `33328451609`는 SHA 고정 action으로 공개 package inventory를 조회했다. `9735a11`로
  squash merge한 뒤 `main` CI `33328478789`, CodeQL `33328478782`와 수동 GHCR 감사
  `33328498258`이 모두 성공했다. 이 처리로 open Dependabot PR은 0개가 됐다.

### GitHub Actions immutable reference 정책

- CI와 CodeQL에는 `actions/checkout@v7`, `actions/setup-python@v7.0.0`,
  `actions/setup-node@v7`, `github/codeql-action/*@v4`처럼 이동 가능한 참조 10개가 남아 있었다.
  release와 GHCR 감사 workflow의 기존 SHA 고정과 공급망 경계가 일관되지 않았다.
- 공식 repository의 release tag를 직접 조회해 checkout 7.0.1, setup-python 7.0.0,
  setup-node 7.0.0과 CodeQL action 4.37.9가 가리키는 full commit SHA를 확인했다. workflow에는
  SHA를 실행 참조로 쓰고 version을 주석으로 보존했다.
- 새 `ops/ci/verify_action_pinning.py`는 `.yml`과 `.yaml`의 모든 외부 `uses:`를 검사한다.
  local action과 `docker://`만 예외로 두며 branch, major tag와 semver tag는 파일·행 번호와 함께
  실패시킨다. 정상 SHA·local·container와 두 mutable 형식을 회귀 테스트로 고정했다.
- 구현, 정책 문서, Alertmanager 드릴 안정화, 진단 기록과 PR 증적을 역할별 commit으로
  [PR #51](https://github.com/sangmu1126/PipeLens/pull/51)에 분리했다. 최종 CI
  `33361752707`은 action pinning gate에서 모든 외부 참조가 full SHA임을 확인하고, 보강된
  Prometheus→Alertmanager→webhook 경로를 포함한 5개 job을 통과했다. CodeQL
  `33361752698`의 Python·JavaScript/TypeScript 분석도 모두 성공했다.
- 다섯 commit은 `201c924`, `4ed3508`, `6eaeab3`, `aeb174f`, `3ac158a`로 rebase merge됐다.
  병합 후 `main` CI `33362037504`는 immutable action으로 5개 job과 action pinning gate,
  Alertmanager 경로를 다시 통과했고 CodeQL `33362037525`의 두 언어 분석도 성공했다.

### 비밀값 inventory와 OAuth token 암호화 키 교체

- production 안전 설정은 별도 Fernet key를 요구했지만 단일 key만 읽었다. key를 바꾸면 DB에
  저장된 기존 GitHub user access token을 해독하지 못해 해당 session이 모두 삭제되는 구조였고,
  secret별 교체 순서나 침해 대응 runbook도 없었다.
- `11f1f0d`: primary와 쉼표 구분 fallback Fernet key ring을 추가했다. 새 token은 항상 primary로
  암호화하며, 인증 중 primary 실패 후 fallback 복호화가 성공하면 같은 token을 primary로 즉시
  다시 저장한다. 일치하는 fallback이 없거나 평문이 유효한 UTF-8이 아니면 기존 보안 경계대로
  session을 삭제한다.
- 구·신 instance가 섞이는 rollout을 위해 기존 primary+새 fallback을 먼저 전체 배포하고, 이후
  새 primary+기존 fallback으로 뒤집은 뒤 session TTL과 rollback 기간 후 이전 key를 제거한다.
  회귀 테스트는 fallback session 유지·재암호화, fallback 없는 이전 token 폐기와 key ring의
  공백·중복 처리를 확인한다. 로컬 전체 결과는 124 passed, 2 skipped였다.
- [비밀값과 키 교체](secrets-and-rotation.md)에 GitHub App, webhook, OAuth, OpenAI, PostgreSQL,
  Redis와 Alertmanager credential inventory, 교체 순서, rollback, 침해 조사와 증적 체크리스트를
  기록했다. 실제 secret manager와 production rotation drill은 외부 완료 조건으로 남긴다.
- 구현과 운영 문서, PR 검증 증적을 역할별 commit으로
  [PR #53](https://github.com/sangmu1126/PipeLens/pull/53)에 분리했다. CI `33363411829`는
  Python 3.12의 새 session migration 테스트를 포함한 backend, Python 3.14 compatibility,
  PostgreSQL·Redis integration, 두 container와 dashboard를 모두 통과했다. CodeQL
  `33363411722`의 두 언어 분석도 성공했다.
- 세 commit은 `3941b29`, `ba019f9`, `e445933`으로 rebase merge됐다. 병합 후 `main` CI
  `33363711257`은 전체 5개 job과 token migration 회귀를 다시 통과했고 CodeQL
  `33363711311`의 Python·JavaScript/TypeScript 분석도 성공했다.

### API v1 계약과 deprecation 경계

- dashboard JSON API는 `/api/*` 무버전 경로만 사용해 breaking 변경을 병렬 도입하거나 consumer
  migration 기간을 표현할 수 없었다. FastAPI runtime OpenAPI도 repository에서 review하거나
  drift를 차단하지 않았다.
- `3589df1`: `/api/v1`에 me, analyses 목록·상세와 feedback endpoint를 정식 제공하고 dashboard와
  backend 테스트를 모두 v1으로 전환했다. 기존 path는 같은 handler를 호출하는 deprecated alias로
  유지하며 OpenAPI `deprecated: true`, RFC 9745 `Deprecation` timestamp와 정책 link를 반환한다.
- 생성 script가 정렬된 `docs/openapi.json`을 만들고 backend CI가 runtime schema와 byte 단위로
  비교한다. v1·legacy operation 표시와 runtime deprecation header를 별도 회귀 테스트로 고정했다.
  로컬 결과는 backend 126 passed, 2 skipped, dashboard 4 passed와 production build 성공이었다.
- [API versioning 정책](api-versioning.md)은 additive·breaking 변경, enum·behavioral contract,
  v2 병렬 운영, legacy alias의 최소 180일 공지와 Sunset 승인 조건, OpenAPI review 절차를 정의한다.
- 구현, 정책과 PR 증적을 역할별 commit으로
  [PR #55](https://github.com/sangmu1126/PipeLens/pull/55)에 분리했다. CI `33364795817`은
  OpenAPI drift gate와 backend 126개 테스트, Python 3.14, dashboard, 두 container와 service
  integration을 통과했고 CodeQL `33364795825`의 두 언어 분석도 성공했다.
- 세 commit은 `490f1f1`, `6f3291a`, `2bba688`로 rebase merge됐다. 병합 후 `main` CI
  `33365087414`는 OpenAPI contract check와 전체 5개 job을 다시 통과했고 CodeQL
  `33365087411`의 Python·JavaScript/TypeScript 분석도 성공했다.

### 실제 Chromium OAuth·대시보드 흐름

- 기존 Vitest 4개는 로그인 전 화면, 목록 pagination·filter와 axe 접근성을 JSDOM에서
  검증했지만 top-level OAuth redirect, browser cookie jar, Vite proxy와 callback navigation은
  실행하지 않았다.
- `430cdb7`: Playwright 1.62.1과 Chromium E2E를 추가했다. Vite와 실제 FastAPI application을
  함께 띄우고 제어된 OAuth provider가 authorization code, user와 installation 응답만 제공한다.
  브라우저는 로그인 전 화면, 서명 state·callback URL, HttpOnly·SameSite=Lax session,
  인증된 대시보드와 logout 뒤 cookie 삭제를 연속 검증한다.
- 최초 시도에서 로컬 system Python에 uvicorn이 없어 project `.venv`와 CI `PYTHON` 경계를
  분리했다. 이후 GitHub URL route glob이 실제 로그인 페이지로 빠지는 비결정성을 확인해,
  외부 network interception 대신 같은 test server의 OAuth 승인 화면으로 대체했다. Vitest가
  Playwright spec을 함께 수집한 문제는 기본 exclude를 보존하면서 `e2e/**`를 분리해 해결했다.
- 로컬 검증은 Chromium E2E 1 passed, Vitest 4 passed, backend 126 passed·2 skipped, Ruff,
  committed OpenAPI 일치와 Vite production build를 통과했다. 실제 GitHub 자격증명, 공개 HTTPS와
  Secure cookie는 자동화 완료로 표시하지 않고 P0 인수 테스트로 유지한다.
- 재현 명령, CI 단계, mock 범위와 유지보수 규칙은 [브라우저 E2E](browser-e2e.md)에 기록했다.
- 구현과 판단 문서는 [PR #57](https://github.com/sangmu1126/PipeLens/pull/57)에서 분리했다. CI
  `33385076481`은 Ubuntu dashboard job의 Python 3.12·Node 22, Chromium E2E 1개, Vitest 4개와
  production build를 비롯한 전체 5개 job을 통과했다. CodeQL `33385076451`의 Python·
  JavaScript/TypeScript 분석도 성공했다.

### Docker Desktop arm64 로컬 재검증

- `main` `7e1c5b1`에서 Docker Desktop 29.6.2의 8 CPU·약 8GB arm64 engine을 확인했다.
  기존 문서의 “로컬 Docker daemon 미실행”은 당시 개발 시점의 사실로 유지하고, 새 검증을
  별도 후속 증적으로 추가했다.
- PostgreSQL 17→18은 migration 9개, 표본 custom-format dump/restore와 `alembic check`를
  통과했다. Grafana 12.1→13.2는 같은 volume의 probe dashboard, provisioned dashboard 8개
  panel, Prometheus datasource와 익명 Viewer API를 보존했다.
- Prometheus 3.13.2→Alertmanager 0.33.1→local webhook 경로가 config·rule, firing·active 상태와
  payload 전달을 통과했다. PostgreSQL 18과 Redis 8.2 실제 service integration 2개도 성공했다.
- worker 4 replica는 200 job을 49/50/50/51로 처리하고 orphan 1개를 2.117초에 복구했다.
  최대 완료는 2.128초였으며 정확히 한 번 처리와 최종 queue drain을 만족했다.
- current source로 만든 `pipelens-api:local-7e1c5b1`과
  `pipelens-dashboard:local-7e1c5b1` arm64 image는 각각 `pipelens`, `nginx` 사용자와 API
  readiness·dashboard 내부 8080 응답을 통과했다.
- PostgreSQL·Grafana script의 첫 로컬 실행은 system PATH에 `python`·`alembic`이 없어
  실패했으나 전용 임시 resource는 정리됐다. `.venv/bin`을 PATH 앞에 둔 재실행이 성공했다.
  통합 service는 고정 port·이름을 피하고 `mktemp` 이름과 Docker 임의 loopback port를 사용해
  기존 로컬 데이터와 격리했다. 종료 뒤 임시 container·volume이 없음을 확인했다.
- 환경, image ID, 실행 결과와 production 경계는
  [Docker Desktop 로컬 통합 검증](local-docker-validation.md)에 기록했다.

### `main` 변경 통제

- 최신 녹색 commit `037e55b`에서 GitHub Actions app이 만든 CI 5개와 CodeQL 2개 context를
  확인하고 모두 `main` 필수 status check로 등록했다.
- PR, 최신 branch 검증, conversation 해결, 선형 이력과 관리자 적용을 강제하고 force push와
  branch 삭제를 막았다. 단일 maintainer 교착을 피하기 위해 승인 인원만 0명으로 유지했다.
- 설정 직후 직접 `main` 문서 push를 계속하지 않고 `docs/main-protection` branch로 전환해
  [PR #18](https://github.com/sangmu1126/PipeLens/pull/18)에서 첫 보호된 변경 흐름을 시작했다.
- PR #18은 check 대기 중 `BLOCKED`, 7개 필수 context 성공 뒤 `CLEAN`으로 전환됐고
  `c1e5bc7`로 squash merge됐다. merge된 `main`의 전체 CI `33288653155`와 CodeQL
  `33288653056`도 성공했으며 API 재조회에서 protection 설정이 그대로 유지됨을 확인했다.

### Compose image 공급망

- `776fa1c`: Compose에서 직접 실행하는 PostgreSQL 17, Redis 7, Prometheus 3.5.0과 Grafana
  12.1.0을 조회 시점의 multi-platform manifest-list digest로 고정했다. 네 digest 모두
  linux/amd64와 linux/arm64 manifest를 포함함을 `docker buildx imagetools inspect`로
  확인했다. CI는 Compose가 해석한 모든 명시적 image가 `tag@sha256:<64 hex>` 형식인지
  검사하므로 이후 외부 image가 mutable tag로 추가되는 것을 차단한다.
- `1b1b4ba`: Dockerfile을 읽는 기존 `docker` 설정과 별도로 공식 지원 생태계인
  `docker-compose`를 Dependabot에 등록했다. 매주 월요일 10:15(Asia/Seoul)에 최대 4개 PR을
  열어 digest 재게시나 service version 변경을 전체 CI·CodeQL 검토 흐름으로 보낸다.
- tag는 호환성 계열과 review 가독성을 위해 유지하고 digest가 실제 실행 content를 고정한다.
  단일 platform digest 대신 manifest-list digest를 사용해 arm64 개발 환경과 amd64 CI가 같은
  선언에서 각 platform image를 선택하도록 했다. Dependabot은 이미 digest가 있는 참조의
  tag·digest 업데이트를 처리하며, CI 정책은 digest가 제거된 제안을 거부한다.
- 세 변경은 [PR #20](https://github.com/sangmu1126/PipeLens/pull/20)에서 역할별 commit을
  유지하는 rebase 방식으로 `main`에 병합했다. PR의 CI `33292405622`와 CodeQL `33292405611`,
  병합 후 `main`의 CI `33292468235`와 CodeQL `33292468225`가 모두 성공했다.
- 새 생태계 등록 직후 Dependabot이 Grafana 13, Prometheus 3.14, Redis 8과 PostgreSQL 18을
  각각 PR #21–#24로 제안해 탐지·PR 생성 경로도 확인됐다. Grafana·Redis·PostgreSQL은 major,
  Prometheus는 여러 minor를 건너뛰는 runtime upgrade이므로 자동 병합하지 않고 service별
  호환성 검증을 거쳐 따로 판정한다.

### Prometheus 3.13 LTS 전환

- Dependabot PR #22는 Prometheus 3.5.0에서 최신 3.14.0으로 바로 올렸지만 그대로 병합하지
  않았다. 공식 지원 주기상 일반 minor는 다음 6주 주기 뒤 bugfix가 중단될 수 있는 반면
  3.13 LTS는 2027-07-31까지 bug·security fix를 받기 때문이다.
- [PR #29](https://github.com/sangmu1126/PipeLens/pull/29)에서 3.13.2 LTS의 multi-platform
  digest `sha256:508729e0e2d18e11fd742a5a5ca70e557b940a93948c3c95fd0123a6fd538b69`로
  전환했다. manifest에 linux/amd64와 linux/arm64가 모두 있음을 원격 조회로 확인했다.
- 3.13.0의 credentials cross-host redirect 차단과 UI 보안 수정, 3.13.2의
  `golang.org/x/text`·gRPC 보안 수정 및 disk-full query tracker 충돌 방지를 검토했다. 현재
  설정·규칙·Grafana query는 변경된 experimental duration expression, remote write,
  service discovery나 query API option을 사용하지 않는다.
- CI run `33293111339`는 Compose의 digest 참조를 직접 읽어 image를 내려받고 Prometheus 설정
  1개와 alert rule 5개를 `promtool`로 통과시킨 뒤 실제 server가 Ready 상태가 되는 것까지
  확인했다. 같은 PR의 CodeQL run `33293111348`과 나머지 필수 gate도 모두 성공했다.
- Dependabot은 Prometheus의 major·minor를 제외하고 3.13의 patch와 digest만 제안한다. 다음
  LTS line 전환은 공식 지원 기간과 release note, 실제 config·readiness 검증 뒤 수동으로 연다.
- 이 구현은 `5a034d5`(LTS image·readiness gate), `72038fa`(LTS update 경계),
  `6aeb4ad`(판단·검증 문서)의 세 commit으로 [PR #29](https://github.com/sangmu1126/PipeLens/pull/29)에
  rebase merge됐다. 병합 후 `main` CI `33293260308`과 CodeQL `33293260317`도 성공했으며,
  새 ignore 정책이 적용되자 대체된 3.14 제안 PR #22는 자동으로 닫혔다.

### Redis 8.2 Extended 전환

- Dependabot PR #23의 `redis:8-alpine` digest는 Redis 8.10.1 Standard를 가리켰다. major tag는
  이후 minor도 자동으로 이동하고 8.10의 EOL은 아직 미정인 반면, Redis 8.2는 공식 Extended
  line으로 2030-09-01까지 지원되므로 제안을 그대로 병합하지 않았다.
- `fd286c2`: GitHub Actions의 별도 mutable `redis:7-alpine` service를 제거했다. backend CI가
  Compose config의 Redis image를 단일 원본으로 읽어 digest를 pull하고 container health를
  확인한 뒤 실제 PostgreSQL·Redis integration test를 실행하고 항상 container를 정리한다.
- `9bc43ee`: Compose를 Redis 8.2.9 multi-platform manifest-list digest
  `sha256:30abb90e62f14b737010746def3ba99cc79fe19dcdb3d37b41f21fc62e7da19d`로
  전환했다. 원격 manifest에서 linux/amd64와 linux/arm64를 확인했으며 Dependabot은 8.2의
  patch·digest만 추적한다.
- 8.2.9의 `EVAL` ACL key 검사 우회, 악성 RDB memory corruption, blocked-client use-after-free
  보안 수정을 검토했다. PipeLens는 queue 원자성을 위해 Lua `EVAL`을 사용하므로 patch를
  포함하는 이점이 있다. Redis 8이 통합한 Search·JSON·TimeSeries·Bloom과 신규 Stream·Bitmap
  command는 사용하지 않아 queue data model은 list·set·string으로 유지된다.
- [PR #34](https://github.com/sangmu1126/PipeLens/pull/34)의 최종 CI `33300129032`는 Compose의
  정확한 digest를 pull·기동하고 redis-py 8.1 RESP3로 enqueue, blocking dequeue, heartbeat,
  orphan recovery와 acknowledge를 Redis 8.2에서 통과시켰다. 전체 106개 테스트, Python 3.14,
  image build와 CodeQL `33300129030`도 성공했다. 병합 후 `main` CI `33300182440`과 CodeQL
  `33300182403`에서 같은 runtime을 다시 검증했다. 로컬 Docker daemon은 실행 중이지 않아
  container test를 재현하지 못했고, registry manifest와 GitHub runner 결과를 근거로 삼았다.
- Redis 7.4와 8은 모두 RSALv2/SSPLv1 선택지를 제공하며 8은 AGPLv3 선택지를 추가한다. 공식
  image를 수정 없이 내부 queue로 사용하고 Redis 자체를 managed service로 제공하지 않는 현재
  배포 경계에서는 전환을 허용하되, 배포 형태 변경 시 라이선스를 다시 검토한다.
- 세 역할별 commit은 [PR #34](https://github.com/sangmu1126/PipeLens/pull/34)에 rebase merge됐고
  새 8.2 update 경계가 적용되자 floating 8.10 제안 PR #23은 자동으로 닫혔다.

### PostgreSQL 18 전환과 복원 경계

- Dependabot PR #24는 Compose image 한 줄만 PostgreSQL 17에서 18로 변경했다. 기존 CI의
  mutable `postgres:17-alpine` service는 제안된 image, PostgreSQL 18의 새 volume layout과
  major data migration을 검증하지 못했으므로 그대로 병합하지 않았다.
- 원격 manifest를 확인해 `postgres:18-alpine` digest
  `sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2`가 PostgreSQL
  18.6 Alpine이며 linux/amd64와 linux/arm64를 포함함을 확인했다. 공식 정책상 18은
  2030-11-14까지 지원되며 major 전환에는 dump/reload 또는 `pg_upgrade`가 필요하다.
- `3a13cff`: GitHub Actions의 별도 PostgreSQL 17 service를 제거하고 Compose digest를 실제
  integration 단일 원본으로 사용한다. 새 script는 고정된 17 source에 migration·표본 데이터를
  만들고 18 target으로 custom-format dump를 복원한 뒤 데이터와 `alembic check`를 검증한다.
- `791cabb`: Compose를 PostgreSQL 18.6 multi-platform digest로 전환하고 공식 image 18의
  새 volume target `/var/lib/postgresql`을 적용했다. 기존 `postgres-data`와 다른
  `postgres18-data`를 선언해 17 data를 보존하며 Dependabot은 다음 major를 자동 제안하지 않는다.
- 운영 절차는 쓰기 중단, database·globals backup, 새 volume 복원, Alembic과 대표 데이터
  검증 및 rollback 한계를 [PostgreSQL 18 업그레이드](postgres-18-upgrade.md)에 기록했다.
  로컬 Docker daemon이 실행 중이지 않아 container drill은 PR의 GitHub runner에서 판정한다.
- [PR #36](https://github.com/sangmu1126/PipeLens/pull/36)의 첫 CI `33301544816`은 18 image
  초기화 중 임시 server의 첫 readiness를 잡은 뒤 final server 재시작 틈에 `pg_restore`가
  접속해 실패했다. init 완료 log와 최종 `pg_isready`를 함께 요구하도록 대기를 강화했다.
  두 번째 CI `33302704142`에서는 복원과 표본 조회가 성공했지만 표본 전용 table을
  `alembic check`가 제거 대상으로 감지했다. 표본 값을 확인한 뒤 해당 table을 정리하고
  애플리케이션 schema만 비교하도록 순서를 교정했다. 두 수정은 CI 역할 commit에 autosquash했다.
- 최종 PR CI `33302816133`은 PostgreSQL 17에서 migration 9개와 표본 데이터를 생성하고
  PostgreSQL 18.6으로 복원한 뒤 `No new upgrade operations detected`를 확인했다. 이어 같은
  18 digest에서 PostgreSQL lifecycle과 Redis queue integration 2개, 전체 106개 테스트,
  Python 3.14, image build를 통과했고 CodeQL `33302816136`도 성공했다.
- 세 역할별 commit `3a13cff`, `791cabb`, `2a5ff15`는 rebase 방식으로 병합했다. `main` CI
  `33302884926`과 CodeQL `33302884947`이 같은 검증을 다시 통과했고 PostgreSQL 18 한 줄만
  바꾸던 Dependabot PR #24는 새 update 경계 적용 뒤 자동으로 닫혔다.

### Grafana 13 unified storage 전환

- Dependabot PR #21은 Grafana image 한 줄을 12.1.0에서 13.2.0으로 바꿨지만 기존 CI는 Compose
  digest 형식과 dashboard JSON 문법만 검사했다. 실제 Grafana 기동, file provisioning,
  익명 Viewer 접근과 기존 `grafana-data` migration은 검증하지 않아 그대로 병합하지 않았다.
- 공식 upgrade guide에서 13이 dashboard·folder를 legacy SQL table에서 unified storage로
  자동 migration하며 단순 downgrade 시 이전 Grafana가 stale table을 읽는다는 점을 확인했다.
  13.0.0 Git Sync migration 결함은 PipeLens가 해당 feature flag를 쓰지 않고 13.2.0으로 직접
  전환하므로 영향이 없다. 외부 plugin, Image Renderer와 숫자형 datasource API도 사용하지 않는다.
- `70e788d`: 고정 Grafana 12.1에 file provisioning을 적용하고 비관리 probe dashboard를 만든
  뒤 같은 임시 volume을 Compose의 현재 image로 승격한다. 13에서 health/version, probe 보존,
  PipeLens dashboard 8개 panel, Prometheus UID datasource와 anonymous API를 검증하고 항상
  임시 container·volume을 정리한다.
- `0ee59e2`: Compose를 Grafana 13.2.0 multi-platform manifest-list digest
  `sha256:3fd54ae1214669f8355f065ec9f6445d5279a3d77095ab048ca045685272429b`로 전환했다.
  원격 manifest에서 linux/amd64와 linux/arm64를 확인했고 다음 Grafana major만 Dependabot에서
  제외해 full-support 13.x의 minor·patch 제안은 유지한다.
- 정지 상태 volume backup, 전환 확인과 backup 기반 rollback 경계를
  [Grafana 13 업그레이드](grafana-13-upgrade.md)에 기록했다. 로컬 Docker daemon이 실행 중이지
  않아 실제 container migration은 PR의 GitHub runner에서 판정한다.
- [PR #38](https://github.com/sangmu1126/PipeLens/pull/38)의 CI `33303557311`은 정확한 12.1과
  13.2 digest를 pull하고 같은 SQLite volume을 순차 기동했다. health 응답의 두 version,
  12에서 만든 비관리 probe의 13 보존, file-provisioned PipeLens dashboard 8개 panel,
  Prometheus datasource UID·URL과 인증 없는 Viewer API 조회를 모두 통과했다. 전체 106개
  테스트, PostgreSQL·Redis integration 2개, Python 3.14와 image build도 성공했고 CodeQL
  `33303557289`가 통과했다.
- 세 역할별 commit `70e788d`, `0ee59e2`, `7a39980`은 rebase 방식으로 병합했다. `main` CI
  `33303638041`과 CodeQL `33303637927`이 Grafana migration을 포함한 전체 gate를 다시
  통과했고, Grafana image만 바꾸던 Dependabot PR #21은 새 major 제외 정책 적용 뒤 자동으로
  닫혔다. 이로써 첫 Compose image Dependabot 검토 사이클의 open PR은 0개가 됐다.

이 결정은 Node 26과 Nginx 1.31을 함께 올리던 Dependabot PR #11을 그대로 merge하지 않고,
Node 26은 공식 LTS 전환 뒤 별도로 검토하며 Nginx 변경만 PR #17로 다시 생성하도록 만들기
위해 내려졌다.

이 시점에 Docker 2개와 Python dependency 5개로 시작한 첫 Dependabot 검토 사이클은 모두
처리됐다. Node 26은 LTS 정책에 따라 제외했고 나머지는 검증 뒤 merge했으며, 함께 제안됐던
Nginx는 별도 PR로 분리했다.

### Alertmanager 최초 전달 경쟁 제거

- CI run `33365266972`와 `33388547313`은 Prometheus firing 확인 뒤 Alertmanager API가
  30초 동안 빈 목록을 반환해 최초 실행만 실패했고, 같은 revision의 재실행은 통과했다.
- readiness 뒤 즉시 rule을 관측하던 기존 순서는 notifier discovery와 rule evaluation의 독립
  시작 순서를 통제하지 않았다. 단순 timeout 확대는 경쟁을 숨기고 CI 시간을 늘리므로 선택하지
  않았다.
- Prometheus를 rule 없는 bootstrap config로 시작하고 `/api/v1/alertmanagers`의 active 대상을
  확인한 다음 검증된 합성 rule config를 `SIGHUP` reload하도록 변경했다. 이제 최초 firing은
  전달 대상이 준비된 뒤에만 만들어진다.
- discovery payload predicate의 성공·실패 단위 테스트 2개를 추가했다. Prometheus 3.13.2와
  Alertmanager 0.33.1의 고정 digest를 사용한 Docker Desktop arm64 검증은 변경 전 기준 1회와
  변경 후 연속 5회를 통과했다.
- PR #59의 첫 backend run `33390807339`은 Linux의 `mktemp -d`가 만든 `0700` 디렉터리를
  비-root Prometheus container가 읽지 못해 시작 전에 종료됐다. macOS Docker Desktop의 bind
  mount에서는 드러나지 않은 host 차이다. 임시 디렉터리를 설정 읽기에 필요한 `0755`로 명시해
  Linux와 macOS의 권한 계약을 같게 만들었다.
- 교정 후 PR CI run `33391726019`은 새 Alertmanager routing 경로와 전체 backend gate를
  재실행 없이 통과했다. CodeQL run `33391726030`, 두 container build, dashboard와 Python 3.14를
  포함한 필수 검사 7개가 모두 성공했다.

### Starlette TestClient의 httpx2 전환

- FastAPI 0.141.1이 설치한 Starlette 1.6.0은 `httpx2`가 없으면 기존 `httpx`를 사용하면서
  deprecation warning을 출력했다. Starlette는 1.2부터 httpx2 TestClient를 공식 지원한다.
- production의 GitHub·OpenAI HTTP client와 테스트 adapter는 변경 위험이 다르므로 함께
  전환하지 않았다. `httpx2>=2.12.0,<3`을 dev extra에만 추가하고 production `httpx` 의존성과
  import는 유지했다.
- Python 3.14 환경에서 `starlette.testclient`가 실제 `httpx2 2.12.0`을 선택함을 확인했다.
  integration 제외 백엔드 128개, Ruff와 dependency consistency가 통과했고 기존 Starlette
  fallback 경고는 사라졌다.
- [PR #60](https://github.com/sangmu1126/PipeLens/pull/60)의 CI run `33395140783`은 Python
  3.12 backend, Python 3.14 compatibility, dev extra를 설치하지 않는 production API image와
  dashboard를 포함한 전체 gate를 통과했다. CodeQL run `33395140791`도 성공했다.

### production readiness backlog의 GitHub 추적 전환

- readiness 문서에는 외부 환경이 필요한 P0/P1이 남아 있었지만 GitHub issue와 milestone은
  모두 비어 있어 담당 범위, 종료 조건과 증적을 상태로 추적할 수 없었다.
- `priority:p0`, `priority:p1`, `area:acceptance`, `area:operations` label과
  [`v0.2.0 Production readiness`](https://github.com/sangmu1126/PipeLens/milestone/1) milestone을
  생성했다.
- P0는 [실제 GitHub App E2E #61](https://github.com/sangmu1126/PipeLens/issues/61)과
  [공개 HTTPS OAuth·webhook #62](https://github.com/sangmu1126/PipeLens/issues/62)로 분리했다.
  P1은 [PostgreSQL·Grafana 복원 #63](https://github.com/sangmu1126/PipeLens/issues/63),
  [Alertmanager 실채널 #64](https://github.com/sangmu1126/PipeLens/issues/64),
  [secret rotation #65](https://github.com/sangmu1126/PipeLens/issues/65),
  [worker soak/load #66](https://github.com/sangmu1126/PipeLens/issues/66)으로 분리했다.
- 모든 issue에는 목적, 측정 가능한 acceptance criteria, 저장할 redacted evidence와 제외 범위를
  기록했다. milestone 생성 직후 상태는 open 6, closed 0이며 코드 구현만으로 닫지 않는다.
- [PR #67](https://github.com/sangmu1126/PipeLens/pull/67)의 CI run `33397547020`과 CodeQL
  run `33397546955`에서 문서 연결을 포함한 필수 검사 7개가 모두 성공했다.

### 실제 PipeLens CI 실패의 평가 fixture 환류

- 실제 Alertmanager 플래이크는 30초 관측 제한 뒤 `alert state not observed ... []`를
  출력했지만 기존 timeout 규칙은 일반적인 `timed out` 문구만 인식했다. 해당 문구를 좁은 timeout
  signal로 추가했다.
- PR #59의 첫 Linux 실패는 Prometheus 설정의 `permission denied`가 최초 원인이었고 cleanup의
  `Error response from daemon: No such container`가 뒤따랐다. 기존의 넓은 Docker daemon 규칙은
  후속 cleanup을 원인으로 오인할 수 있어 `No such container`를 Docker build 판정에서 제외했다.
- 두 로그는 실제 endpoint와 resource 이름을 합성값으로 바꾸고 secret 없이 최소 구간만
  `evaluation/logs/11-*`, `12-*`에 남겼다. 권한 실패는 지원 범주에 강제로 넣지 않고 `unknown`과
  `permission denied` 최초 근거를 기대한다.
- 평가 계약은 10개 요구 범주 합성 fixture와 실제 회귀 2건, 총 12건으로 확장됐다. 관련 단위
  테스트 15개, 전체 backend 130개와 평가 12/12가 Python 3.14에서 통과했다.
- [PR #68](https://github.com/sangmu1126/PipeLens/pull/68)의 CI run `33398998517`과 CodeQL
  run `33398998843`에서 Python 3.12·3.14 평가와 필수 검사 7개가 모두 성공했다.

### Python 3.15 prerelease의 조기 호환성 관측

- PEP 790의 2026-09-01 상태를 기준으로 Python 3.15 final은 2026-10-01 예정이며,
  GitHub Actions의 공식 Python version manifest에는 3.15.0 RC1이 제공된다.
- 정식 지원 범위 `>=3.12,<3.15`와 필수 Python 3.14 compatibility job은 유지했다. 새 Python
  3.15 preview는 setup-python의 prerelease 선택을 사용해 integration 제외 테스트, `pip check`와
  13개 진단 평가를 실행한다.
- preview 설치의 `--ignore-requires-python`은 아직 3.15를 제외하는 PipeLens root metadata를
  통과하기 위한 한정된 예외다. job을 advisory로 둬 prerelease의 upstream 변동이 지원 branch의
  병합을 막거나 의도적인 CI 실패 메일을 만들지 않게 했다.
- PR #69의 첫 preview job `99556485852`는 CPython 3.15.0 RC1 설치와 root metadata 생성을
  통과했지만 `psycopg-binary==3.3.4`에 CPython 3.15 배포본이 없어 dependency resolution에서
  중단됐다. 순수 `psycopg`으로 대체해 결과를 통과시키지 않고 지원 준비가 되지 않은 최초 근거로
  보존했다.
- job-level `continue-on-error`도 개별 check에는 failure를 표시하므로, 각 preview 단계의 outcome을
  수집해 warning과 Step Summary로 보고하는 구조로 교정했다. 따라서 호환성 공백은 보이지만 전체
  CI 실패나 실패 메일을 의도적으로 만들지는 않는다.
- 교정 후 [PR #69](https://github.com/sangmu1126/PipeLens/pull/69)의 CI run `33413394096`에서
  preview job `99558179867`은 경고를 남기고 check는 성공했다. backend, Python 3.14, dashboard와
  두 container build도 모두 통과했고 CodeQL run `33413394085`의 Python·JavaScript 분석도
  성공했다.
- final 출시 뒤에는 이 예외를 제거하고 PostgreSQL·Redis service integration까지 통과해야
  `<3.16` 지원 선언과 branch protection 승격을 검토한다.

### Python wheel resolution 실패의 평가 fixture 환류

- Python 3.15 preview의 실제 `psycopg-binary==3.3.4` 배포본 부재 로그에서 repository 경로와
  runner 세부 출력을 제거하고, 실행 단계·최초 resolver 오류·종료 상태만 남겼다.
- 기존 classifier는 pip의 `Could not find a version that satisfies`를 dependency 설치 실패로
  이미 좁게 인식한다. 새 범주나 패턴을 추가하지 않고 단위 테스트에서 requirement와 version이
  최초 근거로 보존되는지만 고정했다.
- 평가 세트는 요구 범주 합성 fixture 10건과 실제 PipeLens CI 회귀 3건, 총 13건으로 확장됐고
  로컬 Python 3.14에서 13/13을 통과했다.
- [PR #70](https://github.com/sangmu1126/PipeLens/pull/70)의 CI run `33420484937`에서 Python
  3.12 backend와 Python 3.14 compatibility가 새 평가 13/13을 통과했다. preview advisory,
  dashboard와 두 container build도 성공했고 CodeQL run `33420485072`의 두 언어 분석도
  통과했다.

### 공개 repository metadata와 P2 compatibility 추적

- 비어 있던 GitHub description을 package metadata와 같은 문구로 설정하고 제품 목적과 실제
  stack을 나타내는 topics 9개를 추가했다. repository URL을 homepage로 반복하지 않았으며 실제
  공개 HTTPS endpoint가 없는 상태를 숨기지 않도록 #62 완료 전까지 빈 값으로 유지한다.
- `priority:p2`와 `area:compatibility` label을 만들고
  [Python 3.15 GA 승격 #71](https://github.com/sangmu1126/PipeLens/issues/71)을 생성했다. final
  runtime, `psycopg-binary`, 전체 service integration, 지원 metadata와 branch protection 승격을
  acceptance criteria로 고정했다.
- Python 3.15는 production readiness를 막는 P0/P1이 아니므로 #71을 v0.2.0 milestone에 넣지
  않았다. 이로써 외부 운영 완료율과 향후 runtime 품질 확장을 분리했다.
- [PR #72](https://github.com/sangmu1126/PipeLens/pull/72)의 CI run `33423256610`에서 metadata
  정책 문서와 현재 상태가 backend, Python 3.14, dashboard와 두 container build를 통과했다.
  CodeQL run `33423256608`의 Python·JavaScript 분석도 성공했다.

### 비공개 보안 신고와 evidence-first 기여 접수

- repository API에서 private vulnerability reporting과 Dependabot vulnerability alerts가 꺼져
  있고, security updates도 disabled인 상태를 확인했다. 세 기능을 활성화한 뒤 private reporting
  `enabled: true`, vulnerability alerts HTTP 204, automated security fixes `enabled: true`와
  `paused: false`를 다시 조회했다.
- `SECURITY.md`는 취약점, 노출 credential, private workflow log와 개인정보를 공개 issue에 올리지
  않고 private advisory로 신고하도록 한다. 재현 정보도 최소·마스킹된 범위만 요구하고 실제 secret은
  먼저 폐기·교체하도록 명시했다.
- bug form은 재현, version, environment, 최초 오류와 공개 안전 확인을 필수화했다. feature form은
  문제·측정 결과·대안·완료 증적을 분리하고 blank issue를 껐다. PR template과 기여 가이드는 테스트,
  문서, 보안·개인정보 경계와 분리 커밋을 같은 접수 계약으로 연결한다.
- README의 평가 설명에 남아 있던 이전 수치도 실제 회귀 3건, 전체 fixture 13건으로 교정했다.
- 활성화 직후 Dependabot API에서 open alert 0건, Dependabot이 만든 open PR 0건을 확인했다.
- [PR #73](https://github.com/sangmu1126/PipeLens/pull/73)의 CI run `33424675679`에서 새 공개
  접수 파일과 문서가 backend, Python 3.14, dashboard와 두 container build를 통과했다. CodeQL
  run `33424675633`의 Python·JavaScript 분석도 성공했다.

### Contributor Covenant 행동강령 적용

- 공식 Contributor Covenant 저장소의 최신 release가 2.1이고 version 3 자료는 정식 release가
  아님을 확인해 2.1 원문과 attribution을 적용했다.
- maintainer profile에 공개 email이 없으므로 연락처를 만들거나 공개 issue를 사용하지 않았다.
  기존 private reporting channel이 confidential conduct report도 받도록 명시하고 title prefix로
  security vulnerability와 구분했다.
- correction, warning, temporary ban과 permanent ban의 단계적 enforcement 기준을 기여 가이드와
  repository governance에 연결했다.
- [PR #74](https://github.com/sangmu1126/PipeLens/pull/74)의 CI run `33425763571`에서 행동강령과
  governance 문서가 backend, Python 3.14, dashboard와 두 container build를 통과했다. CodeQL
  run `33425763569`의 Python·JavaScript 분석도 성공했다.

### repository generic secret 탐지 보강

- repository API에서 provider secret scanning과 push protection은 `enabled`, non-provider patterns와
  validity checks는 `disabled`임을 확인했다. 후자의 두 설정을 독립적으로 PATCH했지만 응답과 최종
  재조회 모두 `disabled`였고 open secret alert API는 HTTP 404였다. 개인 소유 공개 repository의
  현재 plan에서 Secret Protection 확장 기능이 제공되지 않는 상태로 판단했다.
- 기존 CI가 full commit SHA로 고정한 Trivy Action을 재사용해 현재 checkout을 `fs`/`secret` 전용으로
  검사하는 `Repository secret scan` job을 추가했다. 탐지 시 exit code 1로 PR을 차단하고 vulnerability
  DB나 container build에 결합하지 않아 gate의 목적과 실패 원인을 분리했다.
- GitHub의 provider pattern 전체 이력 탐지·push protection은 그대로 유지한다. 실제 secret-shaped
  fixture를 공개 Git 이력에 추가하지 않고 placeholder 정책과 false-positive 예외 기준을
  `SECURITY.md`에 명시했다.
- 새 context는 기존 보호 정책에 바로 넣지 않는다. PR의 첫 성공 실행으로 context를 생성한 뒤
  branch protection을 7개에서 8개 필수 check로 갱신하고, 이후 commit에서 보호가 실제로
  적용되는지 다시 검증한다.
- [PR #75](https://github.com/sangmu1126/PipeLens/pull/75)의 첫
  [CI run 33466619219](https://github.com/sangmu1126/PipeLens/actions/runs/33466619219)에서
  `Repository secret scan`이 18초에 성공했고 기존 backend, Python 3.14, dashboard와 두 container
  build도 통과했다. [CodeQL run 33466619215](https://github.com/sangmu1126/PipeLens/actions/runs/33466619215)의
  Python·JavaScript 분석도 성공했다.
- 새 check의 creator가 GitHub Actions `app_id: 15368`이고 conclusion이 `success`임을 commit check
  API로 확인한 뒤 required status checks에 같은 app ID로 추가했다. 최종 재조회는 `strict: true`와
  기존 7개 context 및 `Repository secret scan`, 총 8개를 반환했다.

### dependency 변경의 취약점 사전 차단

- Dependabot alerts·security updates는 활성화됐지만 PR dependency diff를 판정하는 필수 check는
  없었다. 공개 repository에서 무료로 지원되는 공식 Dependency Review Action을 독립 workflow로
  추가했다.
- 2026-05-08 공개된 최신 v5.0.0 tag가 가리키는 commit
  `a1d282b36b6f3519aa1f3fc636f609c47dddb294`를 API로 확인해 full SHA로 고정했다. v5의 Node 24
  runtime은 GitHub-hosted runner 조건을 충족한다.
- runtime과 development scope에서 새로 도입되는 `moderate` 이상 취약점만 차단한다. license 정책과
  OpenSSF scorecard는 이번 보안 gate의 실패 조건에서 제외해 서로 다른 판단을 섞지 않았다.
- 새 `Dependency review` context는 PR의 첫 성공과 GitHub Actions app 출처를 확인한 뒤 기존 8개에
  추가하고, 후속 commit으로 9개 필수 check가 실제 적용되는지 재검증한다.
- [PR #76](https://github.com/sangmu1126/PipeLens/pull/76)의
  [Dependency Review run 33467240944](https://github.com/sangmu1126/PipeLens/actions/runs/33467240944)는
  5초에 성공했다. [CI run 33467240895](https://github.com/sangmu1126/PipeLens/actions/runs/33467240895)의
  secret scan, backend, Python 3.14, dashboard와 두 container build 및
  [CodeQL run 33467240943](https://github.com/sangmu1126/PipeLens/actions/runs/33467240943)의 두 언어
  분석도 모두 통과했다.
- commit check API에서 `Dependency review`의 conclusion `success`, GitHub Actions
  `app_id: 15368`을 확인한 뒤 같은 출처로 required status checks에 추가했다. 최종 재조회는
  `strict: true`와 총 9개 context를 반환했다.

### vendor-neutral secret file 주입 경계

- #65의 실제 secret manager 선택에는 운영자 결정과 workload identity가 필요하지만, 문서가 이미
  허용한 read-only file 경로는 application에서 구현되지 않은 상태였다. 특정 vendor SDK나 resource
  ID를 선택하지 않고 9개 민감 설정에 대응하는 `PIPELENS_*_FILE` 입력을 추가했다.
- API와 worker는 시작 시 regular UTF-8 file을 읽어 기존 Settings field에 주입한다. direct 값과
  file을 함께 지정하거나 file이 누락·비정규·비 UTF-8·빈 값·1 MiB 초과이면 값이나 내용을 출력하지
  않고 시작을 거부한다. PEM 내부 newline을 보존하고 secret volume의 마지막 newline만 제거한다.
- 모든 9개 mapping, 실제 환경변수 source, production 검증 순서, 값·file 충돌과 각 fail-closed 경계를
  단위 테스트로 고정했다. runtime 자동 reload는 일관되지 않은 replica 상태를 만들 수 있어 지원하지
  않고 secret version 변경은 rolling deployment로 적용한다.
- 이 구현은 #65를 완료하지 않는다. 승인된 manager·workload identity, read-only 권한, 실제 Fernet
  3단계 rotation, 외부 credential 폐기와 redacted audit 증적은 issue acceptance criteria로 유지한다.
- 로컬 Ruff, 전체 테스트 `148 passed, 2 skipped`와 진단 평가 13/13을 통과했다.
  [PR #77](https://github.com/sangmu1126/PipeLens/pull/77)의
  [CI run 33468146876](https://github.com/sangmu1126/PipeLens/actions/runs/33468146876)은 새 설정 테스트,
  PostgreSQL·Redis integration, worker drill, secret scan, Python 3.14, dashboard와 두 container build를
  모두 통과했다. [Dependency Review run 33468146869](https://github.com/sangmu1126/PipeLens/actions/runs/33468146869)와
  [CodeQL run 33468146873](https://github.com/sangmu1126/PipeLens/actions/runs/33468146873)의 두 언어
  분석도 성공했다.

### production startup 계약 강화

- production 설정이 HTTPS·Secure cookie와 일부 secret만 확인해 GitHub App credential이 없거나
  SQLite·memory queue 기본값이어도 Settings 생성에 성공하는 공백을 확인했다. 외부 ingress 검증
  전에 잘못된 deployment가 healthy로 보이지 않도록 필수 runtime 계약을 시작 단계로 옮겼다.
- public URL은 credential, subpath, query와 fragment가 없는 HTTPS origin만 허용한다. GitHub App
  ID·private key·slug·OAuth client ID/secret, PostgreSQL psycopg URL과 Redis queue가 모두 있어야
  production API와 worker가 설정 검증을 통과한다.
- App ID는 양의 정수이고 database scheme은 `postgresql+psycopg`, queue backend는 `redis`, queue
  URL은 `redis` 또는 `rediss`인지 좁게 검사한다. secret file 입력은 먼저 해석되므로 direct 값과
  mount 방식이 동일한 production 계약을 사용한다.
- OpenAI provider와 GitHub 게시 flag는 규칙 기반 fallback과 #61의 단계적 검증을 위해 선택으로
  유지했다. 실제 hostname, TLS, callback·webhook과 credential 유효성은 #61·#62·#65를 닫기 전까지
  외부 미검증 상태다.
- [PR #78](https://github.com/sangmu1126/PipeLens/pull/78)에서
  [CI run 33468992166](https://github.com/sangmu1126/PipeLens/actions/runs/33468992166),
  [Dependency Review run 33468992135](https://github.com/sangmu1126/PipeLens/actions/runs/33468992135),
  [CodeQL run 33468992127](https://github.com/sangmu1126/PipeLens/actions/runs/33468992127)이 성공했다.
  CI에는 backend·dashboard, Python 3.14, 두 container build, repository secret scan과 advisory
  Python 3.15가 포함됐고 CodeQL 두 언어 분석도 통과했다.

### Dockerfile base image digest 정책

- Compose service image는 이미 digest로 고정했지만 source Dockerfile의 Python, Node와 Nginx
  `FROM`은 mutable tag만 사용하고 있었다. 결과 image scan·SBOM과 별개로 build 입력을 재현할 수
  있도록 세 reference를 tag와 OCI index digest 조합으로 바꿨다.
- 2026-09-01 Docker registry에서 `python:3.14-slim`은
  `sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9`,
  `node:24-alpine`은 `sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf`,
  `nginxinc/nginx-unprivileged:1.31-alpine`은
  `sha256:d9083fe47768377ef55dedafd67d4da7c2f2bc2bece7554954f29359deb0dce9`임을 확인했다.
  모두 amd64와 arm64 manifest를 포함하는 multi-platform index다.
- 새 정책 검사는 저장소의 `Dockerfile*`을 탐색하고 `--platform`, multi-stage alias와 `scratch`를
  구분한다. 외부 `FROM`은 읽을 수 있는 tag와 정확한 64자리 SHA-256 digest가 모두 있어야 하며,
  누락 시 파일·줄·reference를 출력한다. generated dependency tree는 탐색에서 제외한다.
- Docker Desktop arm64에서 고정 digest를 직접 pull해 API와 dashboard production image를 모두
  빌드했다. 이후에도 Dependabot의 두 Docker 생태계가 version·digest 갱신을 제안하며 모든 image
  build, smoke, 취약점 scan과 SBOM 검증을 거친다.
- [PR #79](https://github.com/sangmu1126/PipeLens/pull/79)의
  [CI run 33469692762](https://github.com/sangmu1126/PipeLens/actions/runs/33469692762)에서 새 pinning
  gate, amd64 API·dashboard build와 기존 전체 검증이 성공했다.
  [Dependency Review run 33469692736](https://github.com/sangmu1126/PipeLens/actions/runs/33469692736)과
  [CodeQL run 33469692739](https://github.com/sangmu1126/PipeLens/actions/runs/33469692739)의 두 언어
  분석도 통과했다.

### 공개 HTTPS acceptance preflight

- #62는 실제 hostname과 credential이 있어야 완료할 수 있지만 배포 직후 반복할 repository-native
  검증 도구는 없었다. platform을 선택하지 않고 public origin을 입력받는 read-only probe를 추가했다.
- HTTP endpoint는 exact HTTPS origin으로 301·308 영구 redirect해야 한다. HTTPS dashboard는 기본
  certificate·hostname 검증, 1년 이상 HSTS, CSP·Permissions·Referrer·nosniff·frame header를 모두
  통과해야 하며 `/readyz`는 database와 queue를 각각 `ok`로 보고해야 한다.
- OAuth 시작 응답은 GitHub HTTPS authorize endpoint, exact callback URI, non-empty state와
  Secure·HttpOnly·SameSite=Lax state cookie를 확인한다. JSON에는 state, cookie와 client ID 대신
  검증 boolean만 남겨 공개 issue나 승인된 운영 증적 위치에 안전하게 첨부할 수 있게 했다.
- unit test는 정상 redacted evidence, unsafe origin 4종, 짧은 HSTS와 state 없는 OAuth redirect를
  검증한다. 이 도구는 실제 login·installation·logout, signed webhook과 proxy forwarding을 수행하지
  않으므로 #62의 완료 상태는 바꾸지 않는다.
- [PR #80](https://github.com/sangmu1126/PipeLens/pull/80)의
  [CI run 33471055534](https://github.com/sangmu1126/PipeLens/actions/runs/33471055534)에서 Python 3.12
  전체 테스트, Python 3.14 호환성, 두 container build와 기존 운영 drill이 성공했다.
  [Dependency Review run 33471055528](https://github.com/sangmu1126/PipeLens/actions/runs/33471055528)과
  [CodeQL run 33471055578](https://github.com/sangmu1126/PipeLens/actions/runs/33471055578)의 두 언어
  분석도 통과했다.

### Worker soak/load machine-readable evidence 확장

- 기존 4-replica·200-job drill은 모든 job을 한 번에 넣고 max latency만 출력해 #66에서 요구하는
  arrival rate·burst·duration별 비교와 capacity 결과 축적에 부족했다. CI 기본 시나리오는 바꾸지
  않고 rate, burst, 합성 처리 latency와 JSON file output option을 추가했다.
- orphan job 한 건을 먼저 processing으로 옮긴 뒤 replica를 시작하고 나머지 arrival stream을
  주입한다. 남은 enqueue와 worker 처리를 겹쳐 rate-shaped stream의 앞쪽 queue wait가 부풀어
  오르는 측정 왜곡을 피했다. 미연결 Redis cleanup이 원래 connection error를 덮지 않도록 연결
  상태도 추적한다.
- 결과 schema는 checked timestamp와 입력 조건, enqueue·전체 관측 시간, throughput, p50·p95·p99
  시작·완료 latency, SLO 달성률, replica 분배, orphan 복구와 exactly-once·drain boolean을 포함한다.
- Docker Desktop arm64와 고정 Redis 8.2 digest에서 40 jobs, 20 jobs/s, burst 4, 30ms 처리와 replica
  4개를 실행했다. 각 replica 10건, orphan 복구 1.074초, p95 시작 0.008초, p95 완료 0.039초,
  21.698 jobs/s, 두 SLO 100%와 최종 drain을 확인하고 임시 Redis를 제거했다.
- 실제 CPU·memory 제한, PostgreSQL pool, provider latency·rate limit·transient failure와 network
  interruption은 이 합성 기준선에 포함하지 않으므로 #66은 계속 외부 인수 항목으로 유지한다.
- [PR #81](https://github.com/sangmu1126/PipeLens/pull/81)의
  [CI run 33518902192](https://github.com/sangmu1126/PipeLens/actions/runs/33518902192)에서 기존 기본값인
  4-replica·200-job burst drill과 Python 3.12 전체 테스트, Python 3.14 호환성, 두 container build가
  성공했다. [Dependency Review run 33518902120](https://github.com/sangmu1126/PipeLens/actions/runs/33518902120)과
  [CodeQL run 33518902328](https://github.com/sangmu1126/PipeLens/actions/runs/33518902328)의 두 언어
  분석도 통과해 선택적 rate shaping이 기존 CI 기준선을 바꾸지 않음을 확인했다.

### PostgreSQL production backup 복원 증적 기반

- #63의 실제 production 규모 실행 전, operator가 dump·restore 명령과 수동 기록을 조합해야 했고
  기존 CI upgrade drill은 합성 source를 즉시 만들고 제거해 외부 backup의 duration·checksum·RTO와
  대표 데이터 결과를 축적할 수 없었다.
- `ops/postgres/verify_restore.py`는 고정 PostgreSQL 18 image, 기존 이름 충돌 거부, read-only
  backup·password mount와 새 disposable volume을 강제한다. custom-format 목록을 먼저 읽고
  `pg_restore --exit-on-error` 뒤 PostgreSQL major, repository Alembic heads와 최소 대표 count를
  대조한다. 성공·실패 때 생성한 target만 정리한다.
- JSON에는 source revision과 write-freeze·backup 시각, 운영자가 측정한 backup duration·observed
  RPO, backup·database bytes와 SHA-256, restore·전체 recovery duration, RTO/RPO 판정과 무결성
  결과만 기록한다. backup/password 경로, database credential과 실제 record는 포함하지 않는다.
- Docker Desktop 29.6.2 arm64에서 합성 17,585-byte custom dump를 고정 PostgreSQL 18.6에 실제
  복원했다. restore 0.099초, 전체 recovery 4.928초, database 8,255,167 bytes, Alembic
  `20260829_0009`, analysis 1건과 자동 cleanup을 확인했다. 이는 도구 검증이며 production 규모
  RTO/RPO나 Grafana 복원 완료로 간주하지 않는다.
- [PR #82](https://github.com/sangmu1126/PipeLens/pull/82)의
  [CI run 33522859800](https://github.com/sangmu1126/PipeLens/actions/runs/33522859800)에서 전체 backend,
  Python 3.14, 두 container build와 기존 PostgreSQL·Grafana·worker drill이 성공했다.
  [Dependency Review run 33522859708](https://github.com/sangmu1126/PipeLens/actions/runs/33522859708)과
  [CodeQL run 33522859793](https://github.com/sangmu1126/PipeLens/actions/runs/33522859793)의 두 언어
  분석도 통과했다.

### Grafana production volume 복원 증적 기반

- #63의 Grafana 항목도 기존 12→13 CI migration과 별개로 stopped volume backup의 크기·checksum,
  복원 시간, persistent content와 접근 정책을 같은 형식으로 기록할 도구가 없었다.
- `ops/grafana/verify_restore.py`는 고정 Grafana 13 image와 새 volume만 사용하고 archive의 path
  traversal, link, device와 root `grafana.db` 누락을 거부한다. backup을 root로 추출해 UID 472로
  소유권을 맞춘 뒤 version·database health, dashboard·folder·datasource와 access policy를 API로
  확인하고 성공·실패 target을 정리한다.
- 첫 실제 복원 두 번은 source API에서 dashboard를 확인한 뒤 backup해도 provisioning directory가
  없는 target에서 `pipelens-operations`가 404였다. file provisioning이 volume DB와 별도 복구
  입력임을 확인해 current provisioning을 read-only mount하고, 최소 하나의 non-provisioned
  dashboard가 backup에서 보존돼야 성공하도록 바꿨다.
- 다음 실행은 content 검증 뒤 admin settings에서 403이었다. restored SQLite의 기존 admin password가
  새 `GF_SECURITY_ADMIN_PASSWORD`로 덮이지 않는 경계를 확인해 임의 password 환경변수를 제거하고
  승인된 admin password file을 API 요청에만 사용하도록 수정했다.
- Docker Desktop 29.6.2 arm64의 최종 실행은 43,036,207-byte archive, 707 members와
  119,991,857 uncompressed bytes를 복원했다. archive restore 1.461초, 전체 recovery 5.443초,
  `grafana.db` 1,642,496 bytes, provisioned·persistent dashboard, folder, Prometheus datasource,
  anonymous Viewer와 admin 차단, cleanup을 확인했다. production 규모·browser·rollback 증적은 아니다.
- [PR #83](https://github.com/sangmu1126/PipeLens/pull/83)의 첫 head에서
  [CI run 33549002512](https://github.com/sangmu1126/PipeLens/actions/runs/33549002512)은 Python 3.12
  전체 테스트, Python 3.14 호환성, 두 container build와 기존 운영 drill을 통과했다.
  [Dependency Review run 33549002707](https://github.com/sangmu1126/PipeLens/actions/runs/33549002707)과
  [CodeQL run 33549002653](https://github.com/sangmu1126/PipeLens/actions/runs/33549002653)의 Python·
  JavaScript/TypeScript 분석도 성공했다. 이 공개 실행은 합성 Grafana 복원 도구와 문서 변경의
  회귀가 없음을 증명하며 production volume 복원 결과를 대신하지 않는다.

### Alertmanager production 채널 증적 계약

- 기존 로컬 webhook drill은 Prometheus→Alertmanager 전달을 검증하지만 #64의 실제 receiver,
  acknowledgement, grouping·deduplication·inhibition·silence, credential rotation과 장애 retry를
  같은 형식으로 판정하거나 기록하지 못했다.
- provider API를 직접 호출하지 않고 Alertmanager, incident provider와 secret manager audit log를
  대조한 strict JSON timeline을 입력으로 받는 검증기를 추가했다. unknown field, 미래·역전 timestamp,
  공백·query가 있는 identifier, 1 MiB 초과 입력과 입력 자체를 output으로 덮어쓰는 경로를 거부한다.
- 결과는 group, 외부 incident ID, 사건 timestamp, delivery·acknowledgement·resolve·rotation·retry
  latency, exercise count와 개별 판정을 남긴다. owner·escalation policy 실제 identifier는 boolean으로
  축약하며 endpoint, token, routing key와 raw payload는 입력 계약 자체에 없다.
- 체크인한 example과 단위 테스트는 도구 계약만 검증한다. 실제 owner·policy 승인, secret manager
  주입, staging notification과 rotation/retry는 외부 증적이 없으므로 #64 완료로 표시하지 않았다.
- [PR #84](https://github.com/sangmu1126/PipeLens/pull/84)의 첫 head에서
  [CI run 33552382222](https://github.com/sangmu1126/PipeLens/actions/runs/33552382222)은 Python 3.12
  전체 테스트, Python 3.14 호환성, repository secret scan, 두 container build와 기존 운영 drill을
  통과했다. [Dependency Review run 33552382228](https://github.com/sangmu1126/PipeLens/actions/runs/33552382228)과
  [CodeQL run 33552382306](https://github.com/sangmu1126/PipeLens/actions/runs/33552382306)의 Python·
  JavaScript/TypeScript 분석도 성공했다. 이 결과는 증적 검증기 회귀만 확인하며 실제 receiver
  연결이나 notification 전달을 증명하지 않는다.

### Production secret manager와 credential rotation 증적 계약

- 기존 `*_FILE`과 Fernet key ring은 application 경계를 검증하지만 #65의 실제 manager inventory,
  workload identity 권한, 배포·폐기 timeline과 unavailable-secret incident를 같은 형식으로 판정하지
  못했다.
- vendor API와 cloud credential을 저장소에 결합하지 않고 manager·deployment·provider audit를
  정규화한 strict JSON 검증기를 추가했다. required credential 9개와 선택적 OpenAI key, workload,
  owner·version·rotation deadline, file/read-only 여부를 inventory로 대조한다.
- Fernet는 기존 primary+새 fallback, 새 primary+기존 fallback, lazy rewrap, 관찰 기간, fallback 제거와
  canary 순서를 강제한다. 외부 credential은 새 version 배포·canary·이전 version 폐기·재검증을,
  unavailable secret은 detection·incident·replacement·recovery와 fail-closed를 검증한다.
- redacted 결과에는 owner, identity와 version 원문 대신 boolean과 16자리 SHA-256 fingerprint만 남긴다.
  실제 secret, resource URL, manifest와 log 원문은 입력할 수 없다. example은 9개 check, detection
  10초와 recovery 120초를 통과하지만 합성 계약 검증이므로 #65는 열린 상태로 유지했다.

## 현재까지의 검증 방식

개발 과정에서 다음 gate가 누적됐다.

- Ruff 정적 lint
- 백엔드 단위·API·migration 테스트
- PostgreSQL과 Redis 실제 service 통합 테스트
- 13개 진단 fixture의 80% 정확도 gate
- Vitest 대시보드 사용자 흐름·접근성 테스트
- Playwright Chromium OAuth·session·dashboard·logout E2E
- TypeScript와 Vite production build
- Prometheus config·규칙과 실제 server readiness, Compose config 검증
- API·대시보드 컨테이너 빌드, 최종 USER 검사와 API readiness·대시보드 HTTP smoke test
- Dockerfile 외부 base image의 tag·multi-platform digest 고정 정책 검사
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
