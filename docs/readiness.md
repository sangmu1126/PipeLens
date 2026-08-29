# 검증 및 운영 준비 현황

## 1. 상태 요약

기준 시점: **2026-08-30**, 기능 기준 commit `1f90715`.

| 영역 | 상태 | 근거 |
| --- | --- | --- |
| MVP 기능 코드 | 완료 | root `README.md` 기능 목록과 자동 테스트 |
| 고정 진단 평가 | 통과 | 10/10, 100%; CI 최소 기준은 80% |
| 백엔드 테스트 | 통과 | 로컬 105 passed, integration 2 skipped; CI에서 service integration 별도 통과 |
| Python 호환성 | 통과 | 3.12 전체 integration, 3.14 단위·API 105개와 진단 평가 10/10 |
| 대시보드 테스트 | 통과 | Node 22 CI, Node 24 로컬 검증, Vitest 4/4와 Vite production build |
| API·대시보드 이미지 | 통과 | 실제 Docker build, 최종 non-root USER 검사 |
| 대시보드 컨테이너 기동 | 통과 | CI에서 Nginx 기동 후 내부 8080 HTTP smoke test |
| 정적 보안 분석 | 통과 | Python·JavaScript/TypeScript CodeQL, open alert 0 |
| 실제 GitHub App E2E | 미검증 | 공개 HTTPS·App credentials가 필요한 외부 검증 |
| production 배포 | 미완료 | Compose는 있으나 release·registry·TLS·backup 절차 없음 |
| `main` 보호 | 미설정 | branch protection 404, repository ruleset 빈 목록 |

최근 검증 실행:

- [CI run 33252323077](https://github.com/sangmu1126/PipeLens/actions/runs/33252323077)
- [CodeQL run 33252323079](https://github.com/sangmu1126/PipeLens/actions/runs/33252323079)

## 2. 자동 검증 상세

### 백엔드 CI

1. Python 3.12 환경과 pip cache 구성
2. editable dev dependency 설치
3. `ruff check .`
4. 전체 `pytest -q`
5. 공식 `promtool`로 Prometheus 설정 검증
6. `docker compose config --quiet`와 Grafana dashboard JSON 검증
7. 실제 PostgreSQL 17·Redis 7 service에 대한 integration test
8. `pipelens-evaluate --minimum-accuracy 0.8`

별도 compatibility job은 Python 3.14에서 integration directory를 제외한 105개 테스트와
10개 진단 평가를 실행한다. 지원 범위는 `>=3.12,<3.15`이며 3.12는 하한 전체 통합 검증,
3.14는 상한 직전 호환성 검증을 담당한다. 로컬 3.14에서는 일부 dependency가 Python 3.16을
앞두고 제거될 asyncio API에 대한 deprecation warning을 출력하지만 테스트 결과에는 영향을
주지 않는다.

### 대시보드 CI

- 지원 범위 `^22.13.0 || ^24.0.0`의 하한인 Node.js 22
- `npm ci`
- Vitest 사용자 흐름·접근성 회귀 테스트
- TypeScript project build와 Vite production bundle

대시보드 Dockerfile은 지원 범위의 최신 LTS인 Node 24로 같은 production build를 실행한다.
Node Current release는 LTS 전환과 dependency compatibility 검토 전까지 자동 major update
대상에서 제외한다.

### 컨테이너 CI

- API와 대시보드 context를 matrix로 병렬 빌드한다.
- API image `Config.User`가 `pipelens`인지 검사한다.
- dashboard image `Config.User`가 `nginx`인지 검사한다.
- API container를 실제로 기동하고 SQLite 초기화·메모리 queue를 포함한 내부 `8000`의
  `/readyz` 응답을 확인한다.
- dashboard container에 `api` host를 제공해 실제로 기동하고 내부 `8080`의 `/` 응답을
  확인한다.
- allowlist `.dockerignore`는 API에 필요한 약 612KB, 대시보드에 필요한 약 180KB만
  context에 남기며 `.env`, Git metadata, `.venv`, `node_modules`와 이전 build output을
  제외한다. 크기는 2026-08-29 로컬 작업공간 측정값이며 파일 변화에 따라 달라질 수 있다.

### CodeQL

- `main` push
- `main` 대상 pull request
- 주 1회 schedule
- 수동 `workflow_dispatch`

Python과 `javascript-typescript`를 독립 matrix job으로 분석한다. workflow에는 code scanning
결과 업로드에 필요한 `security-events: write`와 소스 읽기 권한만 부여한다.

### Dependency 유지보수

Dependabot이 pip, npm, GitHub Actions와 API·대시보드 Dockerfile의 base image 업데이트를
매주 월요일 순차 실행한다. 대시보드의 Node·Nginx 변경은 한 PR로 묶어 동일한 image build와
smoke test를 함께 거치게 한다. Docker 설정을 처음 반영한 2026-08-29 검사에서 Docker 2개와
Python dependency 5개, 총 7개의 후속 PR이 생성됐다.

Docker PR은 자동 생성과 현재 CI가 성공했다는 이유만으로 바로 merge하지 않았다.

- [#10](https://github.com/sangmu1126/PipeLens/pull/10)은 API runtime을 Python 3.12에서
  3.14로 변경했다. Python 3.14 compatibility와 API image 기동 smoke test를 `main`에 먼저
  추가한 뒤 PR을 rebase했고, 모든 gate 통과 후 `95b9970`으로 squash merge했다.
- [#11](https://github.com/sangmu1126/PipeLens/pull/11)은 Node 24→26과 Nginx 1.29→1.31을
  함께 변경했지만 merge하지 않는다. 2026-08-30 기준 Node 26은 Current이며 공식 일정상
  2026-10-28에 LTS로 전환될 예정이므로 Node major 자동 업데이트를 제외했다. 설정 반영 뒤
  PR을 다시 생성해 Nginx 1.31 변경만 기존 image build·non-root·HTTP smoke gate로 검증한다.
- [#12–#16](https://github.com/sangmu1126/PipeLens/pulls)은 Ruff, HTTPX, Prometheus client,
  cryptography와 SQLAlchemy 최소 버전을 각각 갱신한다. 각 PR의 전체 검사가 끝난 뒤 독립
  호환성 변경으로 처리한다.

Compose에서만 참조하는 PostgreSQL, Redis, Prometheus와 Grafana image update, immutable
digest 고정은 아직 남은 공급망 작업이다.

## 3. 보안 통제 현황

### 구현·검증됨

- GitHub webhook HMAC-SHA256 검증
- GitHub App installation token 사용과 최소 권한 문서화
- OAuth state 검증, HttpOnly/SameSite session cookie
- 사용자 token Fernet 암호화 저장
- installation 단위 분석 접근 제어
- 로그·patch·workflow·실행 metadata 마스킹
- 외부 fork LLM 전송 차단과 게시 제한
- LLM evidence·파일 경로 검증과 규칙 fallback
- production 안전 설정 fail-fast
- API·Nginx 보안 응답 header
- API·dashboard non-root container
- Docker build context allowlist
- CodeQL과 pip·npm·Actions·Dockerfile dependency 자동 업데이트

### 미구현 또는 외부 설정 필요

- `main` branch protection/ruleset과 필수 status check
- container CVE scan과 severity gate
- SBOM, provenance/attestation과 서명된 release image
- immutable base image digest 정책
- production secret manager와 key rotation 절차
- TLS reverse proxy의 HSTS
- GitHub 조직 정책에 따른 secret scanning/push protection 확인
- 정기적인 OAuth session·암호화 key rotation 훈련

## 4. 실제 인수 테스트 계획

코드상 MVP 완료와 실제 서비스 완료를 구분하기 위해 다음 순서의 E2E가 필요하다.

1. 공개 HTTPS 환경에 API와 dashboard를 배포한다.
2. PostgreSQL·Redis migration과 readiness를 확인한다.
3. GitHub App에 Actions(read), Checks(read/write), Contents(read), Pull
   requests(read/write), Metadata(read)를 설정한다.
4. webhook, OAuth callback, setup URL과 production 환경변수를 연결한다.
5. 테스트 저장소에 App을 설치하고 로그인 사용자의 installation 목록을 확인한다.
6. PR workflow에서 의도적인 테스트 실패를 발생시킨다.
7. 60초 이내 분석 시작, 120초 이내 완료 여부를 확인한다.
8. secret fixture가 게시물, DB와 LLM provider request에서 마스킹됐는지 확인한다.
9. PR 코멘트의 근거·관련 파일·상세 링크와 재전달 시 upsert를 확인한다.
10. PR 없는 branch 실패에서 Commit Check를 확인한다.
11. 외부 fork 실패에서 LLM 호출이 없고 PR 경고만 게시되는지 확인한다.
12. GitHub/OpenAI 429·5xx, Redis worker 종료와 lease recovery를 fault injection으로 확인한다.
13. 대시보드 접근 격리와 feedback 저장을 확인한다.

이 결과는 실행 날짜, run ID, 게시 URL, latency와 발견된 문제를 별도 인수 테스트 기록으로
남겨야 한다.

## 5. 남은 작업 우선순위

### P0 — 서비스 완료 조건

1. 위 GitHub App E2E 인수 테스트 수행
2. `main` 보호와 CI·CodeQL 필수 status check 설정
3. 실제 공개 HTTPS 환경의 OAuth·webhook 검증

### P1 — 릴리스와 공급망

1. version tag와 GitHub Release 정책 정의
2. GHCR에 API·dashboard image를 build/push하는 release workflow 추가
3. container vulnerability scan, SBOM과 provenance 추가
4. Compose 전용 image 업데이트 자동화와 immutable digest 정책 결정

### P1 — 운영 신뢰성

1. PostgreSQL·Grafana volume backup과 restore drill
2. Alertmanager와 실제 호출 채널 연결
3. secret manager, key rotation과 incident response runbook
4. worker replica 부하·장애 복구와 SLO 검증

### P2 — 품질 확장

1. 실제 브라우저 기반 OAuth·dashboard E2E
2. 실제 저장소 실패 사례를 evaluation fixture로 지속 추가
3. Python 3.15 지원 시점과 dependency compatibility 결정
4. API schema versioning과 upgrade/deprecation 정책

## 6. 현재 GitHub 저장소 관리 상태

2026-08-29 조회 결과:

- visibility: public
- default branch: `main`
- open issues: 0
- open pull requests: 6 (`#11`–`#16`, Dependabot 검토 대기)
- releases: 0
- branch protection: 없음
- repository rulesets: 0
- open CodeQL alerts: 0
- repository description과 homepage: 비어 있음

열린 이슈가 없다는 것은 남은 작업이 없다는 뜻이 아니다. 위 P0/P1 항목을 GitHub issue 또는
milestone으로 옮겨 추적하는 작업이 필요하다.

## 7. 운영 전 체크리스트

- [ ] GitHub App 실제 설치와 E2E 증적
- [ ] production HTTPS와 HSTS
- [ ] `main` 필수 review/status check
- [ ] immutable release image
- [ ] container scan·SBOM·provenance
- [ ] secret manager와 rotation
- [ ] PostgreSQL backup/restore drill
- [ ] Alertmanager 연결
- [ ] 외부 fork 공격 입력 검증
- [ ] 부하 상태에서 시작 60초·완료 120초 SLO 검증
