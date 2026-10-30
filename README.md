# PipeLens

PipeLens는 GitHub Actions 실패를 **근거 중심으로 진단**하는 GitHub App입니다. 실패 로그를
단순 요약하지 않고 실패 job·step, 정제된 로그, 변경 diff, 실행 시점 workflow를 교차
검증해 입력에 실제로 존재하는 근거가 있는 원인과 해결 방향만 PR 코멘트나 Commit Check로
게시합니다.

- LLM 없이도 동작하는 규칙 기반 분류(11개 실패 범주, 보안 검사 차단 포함)와 선택적 OpenAI 보강
- 실패 commit의 실제 파일에 그대로 적용되는지 확인한 수정 diff만 제안 (규칙·LLM 공통 검증)
- 로그·diff·workflow의 secret/개인정보 마스킹, 외부 fork 입력 격리
- Redis worker replica, lease 복구, fencing token으로 중복·지연 실행 부작용 차단
- React 대시보드, installation 단위 접근 제어, Prometheus·Grafana·Alertmanager 관측

현재 버전은 **v0.2.0**입니다 ([릴리스 노트](https://github.com/sangmu1126/PipeLens/releases/tag/v0.2.0)).

## 목차

- [동작 방식](#동작-방식)
- [데모와 검증 증적](#데모와-검증-증적)
- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [빠른 시작](#빠른-시작)
- [테스트와 품질 검사](#테스트와-품질-검사)
- [GitHub App 설정](#github-app-설정)
- [신뢰 경계](#신뢰-경계)
- [신뢰성과 SLO](#신뢰성과-slo)
- [API](#api)
- [프로젝트 구조](#프로젝트-구조)
- [문서](#문서)

## 동작 방식

```mermaid
flowchart LR
    GH[GitHub webhook<br/>workflow_run.completed] --> API[FastAPI API]
    API --> DB[(SQLite / PostgreSQL)]
    API --> Q{Queue}
    Q -->|개발| MW[API 내장 memory worker]
    Q -->|Compose·운영| R[(Redis)] --> W[독립 worker]
    MW --> P[분석 파이프라인]
    W --> P
    P --> GHAPI[GitHub API<br/>로그·diff·게시]
    P -.->|trusted 입력만| LLM[OpenAI 선택]
    P --> DB
    UI[React 대시보드] --> API
```

1. **수신** — `POST /webhooks/github`가 HMAC-SHA256 서명을 검증하고 실패한
   `workflow_run`만 workflow run ID 기준으로 중복 없이 저장·큐에 적재한 뒤 `202`를 반환합니다.
   성공한 실행은 같은 브랜치·PR의 직전 실패를 `resolved`/`still_failing`으로 연결하고 복구
   시간을 기록합니다.
2. **분석** — worker가 6단계 파이프라인을 실행하고 단계별 이력과 소요 시간을 남깁니다.

   | 단계 | 내용 |
   | --- | --- |
   | `collecting` | installation token으로 실패 job·step·로그, PR 또는 직전 성공 이후 diff, 실행 시점 workflow 수집, 신뢰 수준 판정 |
   | `sanitizing` | ANSI·timestamp 제거, chunk 단위 마스킹, 오류 신호 주변 구간 추출 |
   | `classifying` | 최초 오류 신호를 우선하는 규칙 엔진으로 11개 범주 또는 `unknown` 판정 |
   | `correlating` | 로그 경로·파일명·코드 토큰·범주 친화도로 변경 파일 점수화 |
   | `diagnosing` | 규칙 진단을 먼저 만들고, `trusted` 입력이면 LLM Structured Outputs 결과를 근거·경로·분류 충돌 검증 후 채택. 수정 diff는 head SHA 파일에 적용되는지 검증된 것만 유지 |
   | `publishing` | PR이 있으면 멱등 PR 코멘트, 없으면 Commit Check 생성 또는 갱신 |

3. **확인** — 대시보드에서 근거, 관련 파일, 비교 SHA 범위, 해결 상태를 보고 정확도
   피드백을 남깁니다.

분류 범주: `test_failure`, `build_failure`, `dependency_installation_failure`,
`lint_or_formatter_failure`, `docker_build_failure`, `deployment_authentication_failure`,
`missing_environment_variable`, `timeout`, `resource_exhaustion`,
`github_actions_workflow_error`, `security_scan_failure` (해당 없음은 억지로 매핑하지 않고
`unknown`).

`security_scan_failure`는 Trivy·npm audit·pip-audit·Dependency Review의 HIGH/CRITICAL 취약점,
gitleaks 등의 secret 탐지, CodeQL·Semgrep 경고로 실행이 차단된 경우입니다. 스캐너 시작 안내나
발견 0건 같은 출력은 차단 신호로 보지 않으며, 하위 유형은 `security.vulnerability`,
`security.secret`, `security.code_scanning` 규칙 ID로 남습니다.

자세한 설계는 [아키텍처 문서](docs/architecture.md)를 참고하세요.

## 데모와 검증 증적

유료 도메인이나 OpenAI API 없이 핵심 흐름을 실제 GitHub에서 재현했습니다. 테스트 저장소의
workflow가 의도적으로 존재하지 않는 `pip==0.0.0`을 설치해 실패하면, PipeLens가 signed webhook을
받아 로그의 비밀값을 제거하고 `dependency_installation_failure`로 분류한 뒤 Commit Check를
게시합니다.

- [의도적 실패 실행](https://github.com/sangmu1126/PipeLens-acceptance/actions/runs/35074952820)
- [PipeLens가 게시한 Commit Check](https://github.com/sangmu1126/PipeLens-acceptance/runs/104725115425)
- [무료 공개 E2E 검증 기록](docs/acceptance-runs/2026-09-16-free-quick-tunnel.md)

이 검증은 실제 GitHub OAuth, App 설치, webhook 서명, worker 분석, 대시보드 접근 제어, Check
게시를 연결했습니다. 분석은 규칙 기반 fallback을 사용해 OpenAI 비용이 발생하지 않았고, 합성
`ghp_...` 문자열이 저장 결과와 게시물에 남지 않는 것도 확인했습니다. Cloudflare Quick Tunnel
주소는 시연마다 바뀌므로 고정 공개 데모 URL은 제공하지 않습니다. 고정 도메인, HSTS, 운영
secret manager, 실제 호출 알림 채널은 제품 배포 범위로 이 포트폴리오의 완료 조건에 포함하지
않습니다.

## 주요 기능

**수집과 정제**
- `workflow_run.completed` webhook 수신, HMAC-SHA256 서명 검증, run ID 기준 중복 방지
- 실패 job·step·로그와 workflow·branch·runner labels 수집(마스킹 후 LLM 입력·대시보드 제공)
- PR 변경 파일 또는 직전 성공 실행 이후 diff, 실행 시점 workflow 수집
- GitHub token, AWS key, JWT, Authorization header, API key, 비밀번호 환경변수, 이메일 마스킹
- 대용량 로그의 chunk별 마스킹과 오류 구간 추출 — 원본 로그 전체는 저장하지 않음

**진단**
- 최초 오류를 우선하는 11개 범주 규칙 분류와 관련 파일 점수화
- 교체 가능한 LLM provider와 OpenAI Responses API Structured Outputs
- 입력에 실제 존재하는 근거·파일 경로만 허용하고 규칙 분류와 충돌하면 규칙 진단 유지
- LLM 장애·검증 실패 시에도 규칙 기반 fallback 진단을 항상 보존

**검증된 수정 제안**
- pip `from versions` 목록이나 스캐너의 수정 버전처럼 로그가 정답을 알려 주는 경우 규칙으로 버전 변경 diff 생성
- 규칙·LLM diff 모두 head SHA의 실제 파일에 문맥까지 그대로 적용되는지 확인하고, 대상 외 파일·크기 초과·
  비밀값 포함 diff는 제외
- 로그를 통한 prompt injection에 대비해 원격 스크립트 실행, secret·토큰 참조, workflow 권한·트리거 변경을
  담은 diff를 거부하고, 적용 결과가 YAML·TOML·JSON으로 파싱되지 않으면 제외
- 해시가 고정된 lock 항목은 diff 대신 lock 재생성을 안내
- 저장소 쓰기 권한 없이 PR 코멘트로만 제안하며, 반영 여부는 다음 관련 실행의 해결 추적으로 측정

**게시와 대시보드**
- PR에는 숨은 run marker로 찾는 멱등 코멘트, PR이 없는 실행에는 Commit Check
- 다음 Workflow 완료를 연결해 성공 전환·계속 실패와 복구 시간 자동 추적
- 분석 이력·근거·관련 diff·단계 진행·피드백·run 딥링크를 제공하는 React 대시보드
- GitHub OAuth 로그인, Fernet 암호화 사용자 토큰, installation 단위 접근 제어

**운영**
- memory 또는 Redis queue, ack·재시도·lease 복구를 지원하는 독립 worker
- SQLAlchemy 기반 SQLite/PostgreSQL 저장 계층과 Alembic migration
- webhook·분석·범주·마스킹·queue·SLO·HTTP retry·LLM token/비용·수정 diff 검증 결과 Prometheus 지표
- Prometheus alert 규칙, Alertmanager routing, provisioned Grafana dashboard

## 기술 스택

| 영역 | 사용 기술 |
| --- | --- |
| Backend | Python 3.12–3.15, FastAPI, Pydantic Settings, httpx, PyJWT, cryptography(Fernet) |
| 저장·큐 | SQLAlchemy 2, Alembic, SQLite / PostgreSQL 18(psycopg 3), Redis 8 |
| Frontend | React 19, TypeScript, Vite, Vitest, Testing Library, axe-core, Playwright |
| 관측 | prometheus-client, Prometheus, Alertmanager, Grafana 13 |
| 배포·CI | Docker(digest 고정 base image), Docker Compose, GitHub Actions, CodeQL, GHCR(SBOM·SLSA provenance) |

## 빠른 시작

### 로컬 (SQLite + memory queue)

Python 3.12 이상 3.16 미만, 대시보드 개발에는 Node.js 22 또는 24가 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn pipelens.main:app --reload
```

기존 로컬 SQLite schema를 명시적으로 갱신하려면 `alembic upgrade head`를 실행합니다.

API 문서는 `http://localhost:8000/docs`에서 볼 수 있습니다. `/healthz`는 프로세스 생존,
`/readyz`는 데이터베이스와 분석 큐를 포함한 요청 처리 가능 여부를 확인합니다. 로컬에서 분석
API를 인증 없이 호출하려면 `PIPELENS_AUTH_REQUIRED=false`를 명시합니다(운영 모드에서는 거부).

### Docker Compose (PostgreSQL + Redis + 관측 스택)

```bash
cp .env.example .env
docker compose up --build
```

Compose는 PostgreSQL health check 후 `alembic upgrade head`를 실행하고 API와 독립 worker를
시작합니다. API healthcheck는 `/readyz`를 사용하며 대시보드는 API가 준비된 뒤 시작합니다.

| 서비스 | 주소 |
| --- | --- |
| 대시보드 | http://localhost:3000 |
| API 문서 | http://localhost:8000/docs |
| Worker 지표 | http://localhost:8001/metrics |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Grafana | http://localhost:3001 |

> [!WARNING]
> Compose의 Grafana는 로컬 관측용 익명 Viewer로 실행됩니다. 외부에 공개할 때는 반드시 인증을
> 별도로 구성하세요. Alertmanager 기본 receiver는 외부 호출을 보내지 않으므로 운영에서는
> [Alertmanager 절차](docs/alertmanager.md)에 따라 알림 채널을 연결합니다.

> [!IMPORTANT]
> 기존 PostgreSQL 17 volume이 있다면 [PostgreSQL 18 업그레이드 절차](docs/postgres-18-upgrade.md),
> Grafana 12 volume이 있다면 [Grafana 13 업그레이드 절차](docs/grafana-13-upgrade.md)를 먼저
> 따라 backup을 만들어야 합니다.

### 릴리스 이미지

정식 릴리스는 API와 대시보드 GHCR image를 제공합니다. 각 image는 취약점·non-root 기동 검사를
통과했고 SLSA provenance와 CycloneDX SBOM attestation이 digest에 연결돼 있습니다. 운영에서는
version tag보다 릴리스 노트에 기록된 immutable digest를 사용하세요
([v0.2.0](https://github.com/sangmu1126/PipeLens/releases/tag/v0.2.0),
[v0.1.0 증적](docs/releases/v0.1.0.md), [릴리스 절차](docs/release.md)).

## 테스트와 품질 검사

```bash
ruff check .
mypy
pytest -q
python ops/ci/verify_markdown_links.py
pipelens-evaluate --minimum-accuracy 0.8
pipelens-evaluate-patches
npm --prefix frontend test
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:e2e
npm --prefix frontend run build
```

CI는 지원 범위 하한인 Python 3.12에서 전체 통합 검사를, 상한 직전인 3.14에서 단위·API 호환성
검사를 실행하며 Ruff, mypy(strict), 백엔드·대시보드 테스트, Chromium OAuth E2E, 정확도
게이트, OpenAPI drift, action·Dockerfile pinning 검사를 함께 수행합니다. 브라우저 검증 범위는
[브라우저 E2E 문서](docs/browser-e2e.md)에 있습니다.

### 진단 정확도 평가

[`evaluation/scenarios.json`](evaluation/scenarios.json)에는 10개 요구 범주, 실제 PipeLens CI
실패 3건, 보안 검사 차단(이미지 취약점·npm audit·secret 탐지) 3건을 재현한 16개 고정 로그가
있습니다. 평가 러너는 예상 범주와 최초 원인 근거를 모두
채점하며 기본 통과 기준은 80%입니다.

```bash
pipelens-evaluate
pipelens-evaluate --json
```

### 수정 diff 평가

[`evaluation/patch_scenarios.json`](evaluation/patch_scenarios.json)은 로그, head 시점 파일, LLM 후보
diff를 묶은 14개 사례로 실제 파이프라인과 같은 `propose_and_verify_patches` 경로를 채점합니다. 규칙 diff
생성 4건, diff를 만들면 안 되는 3건, 정상 LLM diff 1건, 원격 스크립트·secret 참조·권한 확대·비밀값·
오래된 문맥·형식 손상 LLM diff 6건이며, 기대한 파일·적용 결과·거부 수·거부 사유가 모두 맞아야
통과합니다. 결과가 결정적이므로 CI 기준은 100%입니다.

```bash
pipelens-evaluate-patches
pipelens-evaluate-patches --json
```

### PostgreSQL·Redis 통합 테스트

외부 서비스 URL을 명시했을 때만 실행됩니다. 실수로 실제 DB를 migration하지 않도록 데이터베이스
이름은 반드시 `_test`로 끝나야 합니다.

```bash
PIPELENS_TEST_DATABASE_URL=postgresql+psycopg://pipelens:pipelens@localhost:5432/pipelens_test \
PIPELENS_TEST_REDIS_URL=redis://localhost:6379/0 \
pytest -q tests/integration
```

### Worker container smoke

Docker가 실행 중이면 실제 worker 컨테이너 4개, PostgreSQL pool, controlled provider와
worker·Redis 장애를 한 번에 검증합니다. 고유 이름의 container·network·volume만 만들고 종료 시
정리하며 결과 디렉터리는 덮어쓰지 않습니다. 1시간 profile과 산출물 해석은
[Worker replica drill](docs/worker-replica-drill.md)을 참고하세요.

```bash
python -m ops.worker.run_container_soak \
  --profile smoke \
  --output-dir /tmp/pipelens-worker-soak
```

## GitHub App 설정

| 항목 | 값 |
| --- | --- |
| Webhook URL | `https://<host>/webhooks/github` |
| 구독 이벤트 | **Workflow run** |
| Callback URL | `https://<host>/auth/github/callback` |
| Setup URL | `https://<host>/github/setup` |
| Request user authorization during installation | 끔 (로그인 후 설치 → Setup URL로 복귀하는 흐름) |
| 권한 | Actions(read), Checks(read/write), Contents(read), Pull requests(read/write), Metadata(read) |

### 환경변수

전체 목록은 [`.env.example`](.env.example)에 있습니다. 운영 예시는 다음과 같습니다.

```dotenv
PIPELENS_ENVIRONMENT=production
PIPELENS_WEBHOOK_SECRET=...
PIPELENS_GITHUB_APP_ID=123456
PIPELENS_GITHUB_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
PIPELENS_GITHUB_APP_SLUG=pipelens
PIPELENS_GITHUB_CLIENT_ID=...
PIPELENS_GITHUB_CLIENT_SECRET=...
PIPELENS_PUBLIC_URL=https://pipelens.example.com
PIPELENS_SESSION_SECRET=...
PIPELENS_TOKEN_ENCRYPTION_KEY=...
PIPELENS_TOKEN_ENCRYPTION_FALLBACK_KEYS=...
PIPELENS_SESSION_COOKIE_SECURE=true
PIPELENS_DATABASE_URL=postgresql+psycopg://...
PIPELENS_QUEUE_BACKEND=redis
PIPELENS_REDIS_URL=redis://...
PIPELENS_PUBLISH_CHECKS=true
PIPELENS_LLM_PROVIDER=openai          # none이면 규칙 기반 진단만 사용
PIPELENS_OPENAI_API_KEY=...
PIPELENS_OPENAI_MODEL=gpt-5.6
PIPELENS_LLM_INPUT_COST_PER_MILLION=0
PIPELENS_LLM_OUTPUT_COST_PER_MILLION=0
PIPELENS_HTTP_RETRY_MAX_ATTEMPTS=3
PIPELENS_HTTP_RETRY_BASE_SECONDS=1
PIPELENS_HTTP_RETRY_MAX_SECONDS=60
PIPELENS_ANALYSIS_START_SLO_SECONDS=60
PIPELENS_ANALYSIS_COMPLETION_SLO_SECONDS=120
PIPELENS_WORKER_LEASE_SECONDS=60
PIPELENS_WORKER_HEARTBEAT_SECONDS=15
```

Fernet 키는 다음 명령으로 생성합니다.

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

`PIPELENS_PUBLISH_CHECKS=false`로 두면 GitHub에 게시하지 않고 분석 결과만 API에 저장하므로 게시
전에 먼저 검증할 수 있습니다.

### 운영 모드 시작 검증

`PIPELENS_ENVIRONMENT=production`에서는 아래 조건 중 하나라도 어기면 API와 worker가 시작되지
않습니다. 겉보기만 정상인 운영 인스턴스를 만들지 않기 위한 fail-closed 정책입니다.

- 인증 활성화, Secure 세션 쿠키
- `PIPELENS_PUBLIC_URL`이 credential·path·query·fragment 없는 HTTPS origin
- 32자 이상의 webhook·세션 secret, 별도 Fernet 토큰 암호화 키
- GitHub App ID·private key·slug·OAuth client ID/secret 모두 설정
- `postgresql+psycopg` database URL과 Redis queue

### 비밀값 관리

- 민감 설정은 대응하는 `PIPELENS_*_FILE`에 읽기 전용 mount 경로를 지정할 수 있습니다
  (예: `PIPELENS_GITHUB_PRIVATE_KEY_FILE=/run/secrets/github-private-key`). direct 값과 file
  경로를 동시에 지정하면 시작을 거부합니다.
- OAuth token 암호화 키는 primary·fallback key ring으로 무중단 교체할 수 있으며, fallback key로
  읽은 token은 로그인 시 primary key로 다시 암호화됩니다.
- 지원 목록과 절차는 [비밀값 관리와 키 교체](docs/secrets-and-rotation.md), 실제 manager 증적은
  [production secret manager drill](docs/secret-manager-drill.md)에 있습니다.

API 응답에는 MIME sniffing·iframe 삽입·referrer·브라우저 권한을 제한하는 보안 헤더가 포함되고,
대시보드 Nginx는 같은 헤더와 Content Security Policy를 적용합니다. HSTS는 HTTPS를 종료하는
외부 프록시에서 설정해야 합니다. 공개 ingress 연결 후에는
[HTTPS acceptance](docs/https-acceptance.md)와
[GitHub App E2E 증적 절차](docs/github-app-acceptance.md)로 검증합니다.

## 신뢰 경계

외부 fork 실행이나 출처를 증명할 수 없는 입력은 LLM으로 보내지 않습니다. 대시보드에도 같은
신뢰 수준이 표시됩니다.

| 신뢰 수준 | 판정 조건 | LLM 전송 | GitHub 게시 |
| --- | --- | --- | --- |
| `trusted` | head 저장소가 base 저장소와 같음이 확인됨 | 허용 | PR 코멘트 또는 Commit Check |
| `untrusted_fork` | 외부 fork의 head 저장소가 base와 다름 | 차단(규칙 진단만) | PR을 확인할 수 있을 때 경고가 포함된 PR 코멘트만, fork SHA에 Check 생성 안 함 |
| `unverified` | 저장소 context 조회 실패, 불완전한 메타데이터 | 차단(규칙 진단만) | 모든 게시 차단 |

## 신뢰성과 SLO

- **Queue 중복 방지** — 큐 적재는 workflow run ID로 중복 제거되며 Redis에서는 run ID 등록과
  pending 적재가 원자적입니다. DB 기록 후 큐 장애가 나면 webhook 재전달이나 API 시작 시
  reconciliation이 `queued` 분석을 다시 적재합니다.
- **Worker lease** — Redis worker는 인스턴스별 processing 목록과 TTL lease를 사용합니다.
  heartbeat가 끊겨 lease가 만료된 작업만 다른 worker가 원자적으로 복구하므로 여러 replica를
  실행할 수 있습니다. `PIPELENS_WORKER_HEARTBEAT_SECONDS`는 `PIPELENS_WORKER_LEASE_SECONDS`보다
  충분히 작게 유지하세요.
- **Fencing token** — 복구된 작업은 새 attempt token을 받습니다. lease가 만료됐던 이전 worker가
  뒤늦게 재개되어도 token이 일치하지 않는 상태·단계 기록과 GitHub 게시는 거부됩니다.
- **HTTP 재시도** — GitHub·OpenAI의 408, 429, 일시적 5xx는 `Retry-After`를 우선하고, 없으면
  jitter가 포함된 지수 backoff로 재시도합니다. GitHub 403은 rate-limit으로 확인된 경우에만
  재시도하고 quota·billing 429는 즉시 실패합니다. 지연이 상한을 넘으면 현재 작업을 실패시킵니다.
- **SLO** — webhook 레코드 저장 시점부터 분석 시작 60초, 성공 완료 120초가 기본값입니다.
  `pipelens_queue_wait_seconds`, `pipelens_total_latency_seconds`, `pipelens_slo_results_total`,
  `pipelens_http_retries_total` 지표로 확인하고, Prometheus 규칙이 서비스 중단·SLO 위반·queue
  backlog를 Alertmanager로 전달합니다.

백업·복원 절차는 [PostgreSQL 복원 drill](docs/postgres-restore-drill.md)과
[Grafana 복원 drill](docs/grafana-restore-drill.md)에 있습니다.

## API

| Method | Path | 설명 |
| --- | --- | --- |
| `POST` | `/webhooks/github` | GitHub webhook endpoint |
| `GET` | `/auth/github/login` | GitHub OAuth 로그인 시작 |
| `GET` | `/auth/github/callback` | GitHub OAuth callback |
| `POST` | `/auth/logout` | 현재 세션 종료 |
| `GET` | `/github/install` | GitHub App 설치 화면으로 이동 |
| `GET` | `/github/setup` | 설치 완료 후 사용자 접근 권한 재검증 |
| `GET` | `/api/v1/me` | 로그인 사용자와 접근 가능한 installation |
| `GET` | `/api/v1/analyses` | 최근 분석 목록 (`category`·`status`·`repository` 필터, cursor pagination) |
| `GET` | `/api/v1/analyses/{run_id}` | 분석 상세 |
| `PUT` | `/api/v1/analyses/{run_id}/feedback` | 정확도·해결 여부 피드백 저장 |
| `GET` | `/healthz` | 프로세스 상태 |
| `GET` | `/readyz` | 데이터베이스·분석 큐 readiness |
| `GET` | `/metrics` | Prometheus exposition |

분석 API는 기본적으로 인증이 필요하며 사용자가 접근할 수 있는 GitHub App installation의 결과만
반환합니다. 목록의 다음 페이지 cursor는 `X-PipeLens-Next-Cursor` 응답 헤더로 전달됩니다.
무버전 `/api/*` 경로는 deprecated 호환 alias이며, 새 consumer는 `/api/v1`을 사용해야 합니다.
호환성·폐기 조건과 OpenAPI 계약([`docs/openapi.json`](docs/openapi.json))은
[API versioning 정책](docs/api-versioning.md)을 따릅니다.

## 프로젝트 구조

```text
src/pipelens/
  main.py           FastAPI 앱, 라우트, webhook 처리
  pipeline.py       6단계 분석 파이프라인 오케스트레이션
  github.py         GitHub App token, 로그·diff·workflow 수집
  preprocessing.py  로그 정제와 오류 구간 추출
  sanitizer.py      secret·개인정보 마스킹
  classifier.py     규칙 기반 실패 범주 분류
  relevance.py      변경 파일 관련도 점수화
  llm.py            LLM provider와 OpenAI Structured Outputs
  diagnosis.py      규칙·LLM 진단 결합과 근거 검증
  publication.py    PR 코멘트·Commit Check 게시
  queue.py          memory·Redis queue, lease 복구
  worker.py         독립 분석 worker (python -m pipelens.worker)
  store.py          SQLAlchemy 저장 계층
  auth.py           GitHub OAuth, 세션, 토큰 암호화
  config.py         설정 로딩과 운영 모드 검증
  metrics.py        Prometheus 지표
  evaluation.py     정확도 평가 러너 (pipelens-evaluate)
frontend/           React 대시보드, Vitest, Playwright E2E, Nginx 설정
migrations/         Alembic migration (0001–0010)
evaluation/         정확도 평가용 고정 로그와 시나리오
ops/                Prometheus·Alertmanager·Grafana 설정, CI 검증 스크립트, 복구·soak drill
tests/              단위·API·통합 테스트
docs/               아키텍처, 의사결정, 운영 절차, 인수 증적
```

## 문서

개발 과정과 운영 판단은 [`docs/`](docs/README.md)에 정리돼 있습니다.

- [개발 연혁](docs/development-history.md) · [아키텍처](docs/architecture.md) ·
  [주요 의사결정 기록](docs/decisions.md)
- [검증 및 운영 준비 현황](docs/readiness.md) ·
  [MVP 요구사항 추적성](docs/requirements-traceability.md)
- [GitHub App E2E 증적 절차](docs/github-app-acceptance.md) ·
  [컨테이너 릴리스 정책](docs/release.md) · [저장소 보호와 변경 절차](docs/repository-governance.md)
- [기여 가이드](CONTRIBUTING.md) · [행동강령](CODE_OF_CONDUCT.md) ·
  [비공개 보안 신고 정책](SECURITY.md)

## 범위 밖

Slack·Jira 연동, 자동 merge·재배포, GitHub Actions 외 CI 플랫폼, Kubernetes 런타임 분석은 현재
범위에 포함하지 않습니다.

## 라이선스

[MIT](LICENSE)
