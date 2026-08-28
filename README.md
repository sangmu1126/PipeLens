# PipeLens

PipeLens는 GitHub Actions 실패 로그를 단순 요약하지 않고, 로그와 실행 정보를 교차
검증해 근거가 있는 원인과 해결 방향을 제시하는 CI 진단 시스템입니다.

현재 저장소에는 첫 번째 실행 가능한 백엔드 수직 슬라이스가 들어 있습니다.

- `workflow_run.completed` webhook 수신 및 HMAC-SHA256 서명 검증
- 실패한 workflow만 수집하고 workflow run ID로 중복 분석 방지
- GitHub App installation token으로 실패 job·step과 로그 수집
- PR 변경 파일 또는 실패 commit의 diff와 실행 시점 workflow 수집
- ANSI/타임스탬프 제거 및 주요 secret/개인정보 마스킹
- 요구사항의 10개 실패 범주 규칙 기반 분류
- 로그 경로·파일명·오류 범주·변경 코드 식별자를 이용한 관련 파일 점수화
- 교체 가능한 LLM provider와 OpenAI Responses API Structured Outputs 지원
- LLM 근거·파일 경로·규칙 분류 충돌 검증 및 규칙 기반 fallback
- 입력 로그에 실제로 존재하는 근거만 허용하는 결과 검증
- Webhook·분석·오류 범주·마스킹·LLM 사용량과 비용의 Prometheus 지표
- 메모리 또는 Redis queue와 ack·재시도를 지원하는 독립 분석 worker
- SQLAlchemy 기반 SQLite/PostgreSQL 저장 계층과 Alembic migration
- 분석 이력·근거·관련 diff·피드백과 run 딥링크를 제공하는 React 대시보드
- GitHub OAuth 로그인, 암호화된 사용자 토큰, installation 단위 분석 접근 제어
- 외부 Fork 실행 판별과 비신뢰 입력의 LLM·Commit Check 격리
- PR에는 멱등 코멘트, PR이 없는 실행에는 Commit Check로 진단 결과 게시

## 로컬 실행

Python 3.12 이상이 필요합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn pipelens.main:app --reload
```

API 문서는 `http://localhost:8000/docs`, 상태 확인은 `/healthz`에서 볼 수 있습니다.

```bash
pytest
ruff check .
```

Docker를 사용한다면 `.env`를 만든 뒤 다음 명령으로 실행합니다.

```bash
docker compose up --build
```

대시보드는 `http://localhost:3000`, API 문서는 `http://localhost:8000/docs`에서
확인할 수 있습니다.

Compose는 PostgreSQL health check 이후 `alembic upgrade head`를 실행하고 API와 worker를
시작합니다. 로컬 SQLite schema를 명시적으로 갱신하려면 다음 명령을 사용합니다.

```bash
alembic upgrade head
```

## GitHub App 설정

Webhook URL은 `https://<host>/webhooks/github`, 이벤트는 **Workflow run**으로 설정합니다.
Callback URL은 `https://<host>/auth/github/callback`, Setup URL은
`https://<host>/github/setup`으로 지정합니다. 사용자가 먼저 PipeLens에 로그인한 뒤 App을
설치하고 Setup URL로 돌아오는 흐름이므로 **Request user authorization during
installation**은 끕니다.

Webhook secret과 아래 환경변수를 구성해야 실제 로그를 가져올 수 있습니다. 운영에서는
HTTPS를 사용하고 `SESSION_COOKIE_SECURE=true`로 설정해야 합니다. Fernet 키는
`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`로
생성할 수 있습니다.

```dotenv
PIPELENS_WEBHOOK_SECRET=...
PIPELENS_GITHUB_APP_ID=123456
PIPELENS_GITHUB_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
PIPELENS_GITHUB_APP_SLUG=pipelens
PIPELENS_GITHUB_CLIENT_ID=...
PIPELENS_GITHUB_CLIENT_SECRET=...
PIPELENS_PUBLIC_URL=https://pipelens.example.com
PIPELENS_SESSION_SECRET=...
PIPELENS_TOKEN_ENCRYPTION_KEY=...
PIPELENS_SESSION_COOKIE_SECURE=true
PIPELENS_PUBLISH_CHECKS=true
PIPELENS_LLM_PROVIDER=openai
PIPELENS_OPENAI_API_KEY=...
PIPELENS_OPENAI_MODEL=gpt-5.6
PIPELENS_LLM_INPUT_COST_PER_MILLION=0
PIPELENS_LLM_OUTPUT_COST_PER_MILLION=0
```

GitHub App 권한은 Actions(read), Checks(read/write), Contents(read), Pull
requests(read/write), Metadata(read)를 사용합니다. `PIPELENS_PUBLISH_CHECKS=true`이면 PR이
연결된 실행은 PR 코멘트로, PR이 없는 실행은 Commit Check로 게시합니다. 재시도 시 workflow
run ID로 기존 게시물을 찾아 갱신하므로 같은 분석이 중복 게시되지 않습니다. 게시를 먼저
검증하지 않을 때는 `PIPELENS_PUBLISH_CHECKS=false`로 두어도 분석 결과가 API에 저장됩니다.

외부 Fork의 head 저장소가 base 저장소와 다르면 해당 실행은 `untrusted_fork`로 기록합니다.
이 경우 로그·diff·Workflow는 LLM에 전송하지 않고 규칙 기반 진단만 수행합니다. PR 번호를
확인할 수 있으면 경고가 포함된 PR 코멘트만 게시하며, PR을 확인할 수 없는 fork SHA에는
Commit Check를 생성하지 않습니다. 대시보드에도 같은 신뢰 경계가 표시됩니다.

## API

- `POST /webhooks/github`: GitHub webhook endpoint
- `GET /auth/github/login`: GitHub OAuth 로그인 시작
- `GET /auth/github/callback`: GitHub OAuth callback
- `POST /auth/logout`: 현재 세션 종료
- `GET /github/install`: GitHub App 설치 화면으로 이동
- `GET /github/setup`: 설치 완료 후 사용자 접근 권한 재검증
- `GET /api/me`: 로그인 사용자와 접근 가능한 installation
- `GET /api/analyses`: 최근 분석 목록
- `GET /api/analyses/{run_id}`: 분석 상세
- `PUT /api/analyses/{run_id}/feedback`: 정확도·해결 여부 피드백 저장
- `GET /healthz`: 프로세스 상태
- `GET /metrics`: Prometheus exposition endpoint

## 다음 구현 경계

기본 `memory` queue는 API 프로세스 안에서 worker를 함께 실행합니다. Docker Compose는
Redis queue와 별도 worker를 사용하며 worker 지표를 `:8001/metrics`에서 제공합니다.
현재 processing 목록 복구는 단일 worker 배포를 기준으로 하며, 수평 확장 시에는 lease와
worker별 processing queue를 추가해야 합니다.
분석 API는 기본적으로 인증이 필요하며 사용자가 접근할 수 있는 GitHub App installation의
결과만 반환합니다. 로컬 API 테스트처럼 인증을 의도적으로 끄려면
`PIPELENS_AUTH_REQUIRED=false`를 명시합니다. 규칙 기반 진단은 LLM 장애 시에도 항상
fallback 결과로 유지합니다.
