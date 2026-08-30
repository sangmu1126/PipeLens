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

## 현재까지의 검증 방식

개발 과정에서 다음 gate가 누적됐다.

- Ruff 정적 lint
- 백엔드 단위·API·migration 테스트
- PostgreSQL과 Redis 실제 service 통합 테스트
- 10개 진단 fixture의 80% 정확도 gate
- Vitest 대시보드 사용자 흐름·접근성 테스트
- TypeScript와 Vite production build
- Prometheus config·규칙과 실제 server readiness, Compose config 검증
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
