# PipeLens

PipeLens는 GitHub Actions 실패 로그를 단순 요약하지 않고, 로그와 실행 정보를 교차
검증해 근거가 있는 원인과 해결 방향을 제시하는 CI 진단 시스템입니다.

현재 저장소에는 첫 번째 실행 가능한 백엔드 수직 슬라이스가 들어 있습니다.

- `workflow_run.completed` webhook 수신 및 HMAC-SHA256 서명 검증
- 실패한 workflow만 수집하고 workflow run ID로 중복 분석 방지
- GitHub App installation token으로 실패 job과 로그 수집
- PR 변경 파일 또는 실패 commit의 diff와 실행 시점 workflow 수집
- ANSI/타임스탬프 제거 및 주요 secret/개인정보 마스킹
- 요구사항의 10개 실패 범주 규칙 기반 분류
- 로그 경로·파일명·오류 범주·변경 코드 식별자를 이용한 관련 파일 점수화
- 입력 로그에 실제로 존재하는 근거만 허용하는 결과 검증
- SQLite 분석 이력 API와 선택적인 GitHub Check 게시

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

## GitHub App 설정

Webhook URL은 `https://<host>/webhooks/github`, 이벤트는 **Workflow run**으로 설정합니다.
Webhook secret과 아래 환경변수를 구성해야 실제 로그를 가져올 수 있습니다.

```dotenv
PIPELENS_WEBHOOK_SECRET=...
PIPELENS_GITHUB_APP_ID=123456
PIPELENS_GITHUB_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n..."
PIPELENS_PUBLISH_CHECKS=true
```

GitHub App 권한은 Actions(read), Checks(read/write), Contents(read), Pull
requests(read/write), Metadata(read)를 사용합니다. Check 게시를 먼저 검증하지 않을 때는
`PIPELENS_PUBLISH_CHECKS=false`로 두어도 분석 결과가 API에 저장됩니다.

## API

- `POST /webhooks/github`: GitHub webhook endpoint
- `GET /api/analyses`: 최근 분석 목록
- `GET /api/analyses/{run_id}`: 분석 상세
- `GET /healthz`: 프로세스 상태

## 다음 구현 경계

현재 queue와 DB는 단일 프로세스 개발 환경용입니다. 다음 단계에서는 Redis 기반 worker와
PostgreSQL로 분리하고, 교체 가능한 LLM adapter, Prometheus 지표, React 대시보드 및
사용자 피드백을 추가합니다. 규칙 기반 진단은 LLM 장애 시에도 항상 fallback 결과로
유지합니다.
