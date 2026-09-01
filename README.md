# PipeLens

PipeLens는 GitHub Actions 실패 로그를 단순 요약하지 않고, 로그와 실행 정보를 교차
검증해 근거가 있는 원인과 해결 방향을 제시하는 CI 진단 시스템입니다.

개발 과정과 현재 판단을 포함한 상세 기록은 [`docs/`](docs/README.md)에서 확인할 수
있습니다.

- [개발 연혁](docs/development-history.md)
- [현재 아키텍처](docs/architecture.md)
- [주요 의사결정 기록](docs/decisions.md)
- [검증 및 운영 준비 현황](docs/readiness.md)
- [컨테이너 릴리스 정책과 절차](docs/release.md)
- [PostgreSQL 18 업그레이드 절차](docs/postgres-18-upgrade.md)
- [Grafana 13 업그레이드 절차](docs/grafana-13-upgrade.md)
- [저장소 보호와 변경 절차](docs/repository-governance.md)
- [기여 가이드](CONTRIBUTING.md)
- [행동강령](CODE_OF_CONDUCT.md)
- [비공개 보안 신고 정책](SECURITY.md)

현재 저장소에는 첫 번째 실행 가능한 백엔드 수직 슬라이스가 들어 있습니다.

- `workflow_run.completed` webhook 수신 및 HMAC-SHA256 서명 검증
- 실패한 workflow만 수집하고 workflow run ID로 중복 분석 방지
- GitHub App installation token으로 실패 job·step과 로그 수집
- 실패 job의 workflow·branch·runner labels를 마스킹해 LLM 입력과 대시보드에 제공
- PR 변경 파일 또는 직전 성공 실행 이후 diff와 실행 시점 workflow 수집
- ANSI/타임스탬프 제거 및 주요 secret/개인정보 마스킹
- 대용량 로그의 청크별 마스킹·오류 구간 추출과 최초 규칙 오류 우선 판정
- 요구사항의 10개 실패 범주 규칙 기반 분류
- 로그 경로·파일명·오류 범주·변경 코드 식별자를 이용한 관련 파일 점수화
- 교체 가능한 LLM provider와 OpenAI Responses API Structured Outputs 지원
- LLM 근거·파일 경로·규칙 분류 충돌 검증 및 규칙 기반 fallback
- 입력 로그에 실제로 존재하는 근거만 허용하는 결과 검증
- Webhook·분석·오류 범주·마스킹·LLM 사용량과 비용의 Prometheus 지표
- 수집·정제·분류·연관·진단·게시 단계 이력과 대기·실행·전체 소요 시간 기록
- 메모리 또는 Redis queue와 ack·재시도를 지원하는 독립 분석 worker
- SQLAlchemy 기반 SQLite/PostgreSQL 저장 계층과 Alembic migration
- 분석 이력·근거·관련 diff·피드백과 run 딥링크를 제공하는 React 대시보드
- GitHub OAuth 로그인, 암호화된 사용자 토큰, installation 단위 분석 접근 제어
- 외부 Fork 실행 판별과 비신뢰 입력의 LLM·Commit Check 격리
- PR에는 멱등 코멘트, PR이 없는 실행에는 Commit Check로 진단 결과 게시

첫 [`v0.1.0` 릴리스](https://github.com/sangmu1126/PipeLens/releases/tag/v0.1.0)는 API와
대시보드 GHCR image를 제공한다. 각 image는 취약점·기동 검사를 통과했고 SLSA provenance와
CycloneDX SBOM attestation이 digest에 연결돼 있다. 운영에서는 version tag보다
[기록된 immutable digest](docs/releases/v0.1.0.md)를 사용한다.
소스 Dockerfile의 Python·Node·Nginx base image도 읽을 수 있는 tag와 multi-platform digest를
함께 고정하며 CI가 새 stage의 mutable reference를 차단한다.

## 로컬 실행

Python 3.12 이상 3.15 미만이 필요합니다. CI는 지원 범위의 하한인 3.12에서 전체 통합
검사를, 상한 직전인 3.14에서 단위·API 호환성 검사를 실행합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn pipelens.main:app --reload
```

API 문서는 `http://localhost:8000/docs`에서 볼 수 있습니다. `/healthz`는 프로세스 생존
여부를, `/readyz`는 데이터베이스와 분석 큐를 포함한 요청 처리 가능 여부를 확인합니다.

```bash
pytest
ruff check .
pipelens-evaluate --minimum-accuracy 0.8
npm --prefix frontend test
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:e2e
npm --prefix frontend run build
```

## MVP 정확도 평가

`evaluation/scenarios.json`에는 테스트·빌드·의존성·Lint·Docker·배포 인증·환경변수·
Timeout·리소스·Workflow 오류의 10개 요구 범주와 실제 PipeLens CI 실패 3건을 재현하는
13개 고정 로그가 있습니다. 평가 러너는 예상 범주와 최초 원인 근거를 모두 채점하며 기본 통과
기준은 완료 조건과 같은 80%입니다.

```bash
pipelens-evaluate
pipelens-evaluate --json
```

GitHub Actions CI에서도 Ruff, 전체 백엔드·대시보드 테스트, Chromium OAuth E2E, 80% 정확도
게이트와 대시보드 빌드를 함께 실행합니다. 브라우저 검증의 범위와 실제 GitHub 인수 테스트의
구분은 [브라우저 E2E 문서](docs/browser-e2e.md)에 기록합니다.

Docker를 사용한다면 `.env`를 만든 뒤 다음 명령으로 실행합니다.

```bash
docker compose up --build
```

대시보드는 `http://localhost:3000`, API 문서는 `http://localhost:8000/docs`,
Prometheus는 `http://localhost:9090`, Alertmanager는 `http://localhost:9093`, Grafana 운영
대시보드는 `http://localhost:3001`에서 확인할 수 있습니다. Compose의 Grafana는 로컬 관측용
익명 Viewer로 실행되므로
외부에 공개하는 배포에서는 반드시 인증을 별도로 구성해야 합니다.
기존 Grafana 12 volume을 보유한 환경은 13을 기동하기 전에
[Grafana 13 업그레이드 절차](docs/grafana-13-upgrade.md)에 따라 정지 상태 backup을 만들어야
합니다.
Prometheus는 API·Worker를 각각 수집하고 서비스 중단, 분석 시작·완료 SLO 위반,
큐 backlog 규칙을 Alertmanager로 전달합니다. 기본 receiver는 외부 호출을 보내지 않으므로
운영 배포에서는 [Alertmanager 절차](docs/alertmanager.md)에 따라 secret manager로 조직의 알림
채널을 연결해야 합니다.

PostgreSQL·Redis 통합 테스트는 외부 서비스 URL을 명시했을 때만 실행됩니다. 마이그레이션
실수를 방지하기 위해 데이터베이스 이름은 반드시 `_test`로 끝나야 합니다.

```bash
PIPELENS_TEST_DATABASE_URL=postgresql+psycopg://pipelens:pipelens@localhost:5432/pipelens_test \
PIPELENS_TEST_REDIS_URL=redis://localhost:6379/0 \
pytest -q tests/integration
```

Compose는 PostgreSQL health check 이후 `alembic upgrade head`를 실행하고 API와 worker를
시작합니다. 기존 PostgreSQL 17 volume을 보유한 환경은 18을 기동하기 전에 반드시
[PostgreSQL 18 업그레이드 절차](docs/postgres-18-upgrade.md)에 따라 dump/restore해야 합니다.
로컬 SQLite schema를 명시적으로 갱신하려면 다음 명령을 사용합니다.

```bash
alembic upgrade head
```

## GitHub App 설정

Webhook URL은 `https://<host>/webhooks/github`, 이벤트는 **Workflow run**으로 설정합니다.
Callback URL은 `https://<host>/auth/github/callback`, Setup URL은
`https://<host>/github/setup`으로 지정합니다. 사용자가 먼저 PipeLens에 로그인한 뒤 App을
설치하고 Setup URL로 돌아오는 흐름이므로 **Request user authorization during
installation**은 끕니다.
공개 ingress를 연결한 뒤에는 [HTTPS acceptance preflight](docs/https-acceptance.md)로 TLS,
HSTS, redirect, readiness와 OAuth 시작 경계를 redacted JSON으로 확인합니다.

Webhook secret과 아래 환경변수를 구성해야 실제 로그를 가져올 수 있습니다. 운영에서는
HTTPS를 사용하고 `SESSION_COOKIE_SECURE=true`로 설정해야 합니다. Fernet 키는
`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`로
생성할 수 있습니다.

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
PIPELENS_PUBLISH_CHECKS=true
PIPELENS_LLM_PROVIDER=openai
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

`PIPELENS_ENVIRONMENT=production`에서는 인증 활성화, 외부 URL의 HTTPS 사용, Secure 세션
쿠키, 32자 이상의 Webhook·세션 secret, 별도 Fernet 토큰 암호화 키를 시작 시 검증합니다.
외부 URL은 credential·path·query·fragment가 없는 origin이어야 합니다. GitHub App ID·private
key·slug·OAuth client ID/secret, `postgresql+psycopg` database URL과 Redis queue도 모두
필수이며 안전하지 않거나 개발용 기본 설정이 남아 있으면 API와 worker가 시작되지 않습니다.
OAuth token 암호화 키는 [비밀값 관리와 키 교체 절차](docs/secrets-and-rotation.md)에 따라
primary와 fallback key ring으로 무중단 교체할 수 있습니다. fallback key로 읽은 기존 token은
로그인 시 primary key로 다시 암호화됩니다.
민감 설정은 값을 process environment에 직접 넣는 대신 대응하는 `PIPELENS_*_FILE`에 읽기 전용
mount 경로를 지정할 수 있습니다. 예를 들어 `PIPELENS_GITHUB_PRIVATE_KEY_FILE=/run/secrets/github-private-key`
형식이며 direct 값과 file 경로를 동시에 지정하면 시작을 거부합니다. 지원 목록과 file 검증 규칙은
[비밀값 관리와 키 교체 절차](docs/secrets-and-rotation.md)에 있습니다.
API 응답에는 MIME sniffing·iframe 삽입·불필요한 referrer와 브라우저 권한 사용을 제한하는
보안 헤더가 포함됩니다. Compose 대시보드 Nginx는 같은 헤더와 Content Security Policy를
정적 파일 및 프록시 응답에 적용합니다. HSTS는 HTTPS를 종료하는 외부 프록시에서 설정해야
합니다.

GitHub App 권한은 Actions(read), Checks(read/write), Contents(read), Pull
requests(read/write), Metadata(read)를 사용합니다. `PIPELENS_PUBLISH_CHECKS=true`이면 PR이
연결된 실행은 PR 코멘트로, PR이 없는 실행은 Commit Check로 게시합니다. 재시도 시 workflow
run ID로 기존 게시물을 찾아 갱신하므로 같은 분석이 중복 게시되지 않습니다. 게시를 먼저
검증하지 않을 때는 `PIPELENS_PUBLISH_CHECKS=false`로 두어도 분석 결과가 API에 저장됩니다.

외부 Fork의 head 저장소가 base 저장소와 다르면 해당 실행은 `untrusted_fork`로 기록합니다.
이 경우 로그·diff·Workflow는 LLM에 전송하지 않고 규칙 기반 진단만 수행합니다. PR 번호를
확인할 수 있으면 경고가 포함된 PR 코멘트만 게시하며, PR을 확인할 수 없는 fork SHA에는
Commit Check를 생성하지 않습니다. 대시보드에도 같은 신뢰 경계가 표시됩니다.

GitHub와 OpenAI의 408, 429, 일시적 5xx 응답은 `Retry-After`를 우선하고, 없으면 jitter가
포함된 지수 backoff로 재시도합니다. GitHub의 403은 rate-limit 응답으로 확인된 경우에만
재시도하고, quota·billing처럼 사용자 조치가 필요한 429는 즉시 실패합니다. 지연이 설정
상한보다 길면 너무 일찍 다시 요청하지 않고 현재 작업을 실패시킵니다. 재시도 횟수는
`/metrics`의 `pipelens_http_retries_total`에서 확인할 수 있습니다.

분석 성능 SLO는 webhook 레코드가 저장된 시점을 기준으로 측정합니다. 기본값은 첫 분석
시작까지 60초, 성공적인 완료까지 120초이며 위 환경변수로 조정할 수 있습니다.
`/metrics`에서 `pipelens_queue_wait_seconds`, `pipelens_total_latency_seconds`,
`pipelens_slo_results_total`을 확인할 수 있습니다.

## API

- `POST /webhooks/github`: GitHub webhook endpoint
- `GET /auth/github/login`: GitHub OAuth 로그인 시작
- `GET /auth/github/callback`: GitHub OAuth callback
- `POST /auth/logout`: 현재 세션 종료
- `GET /github/install`: GitHub App 설치 화면으로 이동
- `GET /github/setup`: 설치 완료 후 사용자 접근 권한 재검증
- `GET /api/v1/me`: 로그인 사용자와 접근 가능한 installation
- `GET /api/v1/analyses`: 최근 분석 목록
- `GET /api/v1/analyses/{run_id}`: 분석 상세
- `PUT /api/v1/analyses/{run_id}/feedback`: 정확도·해결 여부 피드백 저장

무버전 `/api/*` 경로는 호환 alias로 유지하지만 deprecated다. 새 consumer는 `/api/v1`을 사용해야
하며 호환성·폐기 조건과 생성된 OpenAPI 계약은
[API versioning 정책](docs/api-versioning.md)을 따른다.
- `GET /healthz`: 프로세스 상태
- `GET /readyz`: 데이터베이스·분석 큐 readiness 상태
- `GET /metrics`: Prometheus exposition endpoint

## 다음 구현 경계

기본 `memory` queue는 API 프로세스 안에서 worker를 함께 실행합니다. Docker Compose는
Redis queue와 별도 worker를 사용하며 worker 지표를 `:8001/metrics`에서 제공합니다.
Redis worker는 인스턴스별 processing 목록과 TTL lease를 사용합니다. heartbeat가 끊겨
lease가 만료된 worker의 작업만 다른 worker가 원자적으로 pending queue에 복구하므로 여러
worker replica를 실행할 수 있습니다. `PIPELENS_WORKER_HEARTBEAT_SECONDS`는
`PIPELENS_WORKER_LEASE_SECONDS`보다 충분히 작게 유지해야 합니다.
Docker Compose에서 API healthcheck는 `/readyz`를 사용하며 대시보드는 API가 준비된
후에 시작합니다.
큐 적재는 workflow run ID로 중복 제거되며 Redis에서는 run ID 등록과 pending 적재가
원자적으로 수행됩니다. DB 기록 후 큐 장애가 발생하면 webhook 재전달이 해당 `queued`
분석을 다시 적재하고, API 시작 시에도 DB의 미처리 분석을 큐와 재조정합니다.
복구된 작업이 시작되면 새 attempt fencing token이 발급됩니다. lease가 만료됐던 이전
worker가 뒤늦게 재개되더라도 현재 token과 일치하지 않는 상태·단계 기록은 거부하며 GitHub
게시 단계에 도달하기 전에 중단합니다.
분석 API는 기본적으로 인증이 필요하며 사용자가 접근할 수 있는 GitHub App installation의
결과만 반환합니다. 로컬 API 테스트처럼 인증을 의도적으로 끄려면
`PIPELENS_AUTH_REQUIRED=false`를 명시합니다. 규칙 기반 진단은 LLM 장애 시에도 항상
fallback 결과로 유지합니다.
