# 검증 및 운영 준비 현황

## 1. 상태 요약

기준 시점: **2026-08-30**, 기능 기준 commit `f5e059d`, v0.1.0 source `320f6ae`.

| 영역 | 상태 | 근거 |
| --- | --- | --- |
| MVP 기능 코드 | 완료 | root `README.md` 기능 목록과 자동 테스트 |
| 고정 진단 평가 | 통과 | 10/10, 100%; CI 최소 기준은 80% |
| 백엔드 테스트 | 통과 | 로컬 106 passed, integration 2 skipped; CI에서 service integration 별도 통과 |
| Python 호환성 | 통과 | 3.12 전체 integration, 3.14 단위·API 106개와 진단 평가 10/10 |
| 대시보드 테스트 | 통과 | Node 22 CI, Node 24 로컬 검증, Vitest 4/4와 Vite production build |
| API·대시보드 이미지 | 통과 | 실제 Docker build, 최종 non-root USER 검사 |
| 대시보드 컨테이너 기동 | 통과 | CI에서 Nginx 기동 후 내부 8080 HTTP smoke test |
| 컨테이너 취약점 gate | 통과 | 실제 빌드 이미지의 fixable HIGH/CRITICAL OS·library 항목 0 |
| 컨테이너 SBOM | 통과 | CycloneDX 1.6: API 125개, 대시보드 71개 component artifact |
| GHCR release | 통과 | v0.1.0 이미지 2개와 digest별 provenance·SBOM attestation 검증 |
| Compose service image | 통과 | 4개 외부 image의 multi-platform digest 고정과 CI 정책 검사 |
| GitHub Release 불변성 | 미설정 | v0.1.0 Release API `immutable: false`; 설정은 미래 release부터 적용 |
| 정적 보안 분석 | 통과 | Python·JavaScript/TypeScript CodeQL, open alert 0 |
| 실제 GitHub App E2E | 미검증 | 공개 HTTPS·App credentials가 필요한 외부 검증 |
| production 배포 | 미완료 | 서명 image는 있으나 공개 HTTPS·TLS·backup과 실제 service 배포 없음 |
| `main` 보호 | 설정됨 | PR, strict CI 5개·CodeQL 2개, conversation·linear history, 관리자 적용 |

최근 검증 실행:

- [`Compose image 무결성 PR #20`](https://github.com/sangmu1126/PipeLens/pull/20)
- [Compose image 병합 후 CI run 33292468235](https://github.com/sangmu1126/PipeLens/actions/runs/33292468235)
- [Compose image 병합 후 CodeQL run 33292468225](https://github.com/sangmu1126/PipeLens/actions/runs/33292468225)
- [`main` 보호 검증 PR #18](https://github.com/sangmu1126/PipeLens/pull/18)
- [보호 PR merge 후 CI run 33288653155](https://github.com/sangmu1126/PipeLens/actions/runs/33288653155)
- [보호 PR merge 후 CodeQL run 33288653056](https://github.com/sangmu1126/PipeLens/actions/runs/33288653056)
- [CI run 33252323077](https://github.com/sangmu1126/PipeLens/actions/runs/33252323077)
- [CodeQL run 33252323079](https://github.com/sangmu1126/PipeLens/actions/runs/33252323079)
- [Nginx 1.31 PR CI run 33263438479](https://github.com/sangmu1126/PipeLens/actions/runs/33263438479)
- [Nginx 1.31 PR CodeQL run 33263438485](https://github.com/sangmu1126/PipeLens/actions/runs/33263438485)
- [Ruff 0.16 PR CI run 33264600380](https://github.com/sangmu1126/PipeLens/actions/runs/33264600380)
- [Ruff 0.16 PR CodeQL run 33264600379](https://github.com/sangmu1126/PipeLens/actions/runs/33264600379)
- [HTTPX 0.28 PR CI run 33265290645](https://github.com/sangmu1126/PipeLens/actions/runs/33265290645)
- [HTTPX 0.28 PR CodeQL run 33265290641](https://github.com/sangmu1126/PipeLens/actions/runs/33265290641)
- [Prometheus client 0.26 PR CI run 33265608928](https://github.com/sangmu1126/PipeLens/actions/runs/33265608928)
- [Prometheus client 0.26 PR CodeQL run 33265608942](https://github.com/sangmu1126/PipeLens/actions/runs/33265608942)
- [cryptography 50 PR CI run 33267108019](https://github.com/sangmu1126/PipeLens/actions/runs/33267108019)
- [cryptography 50 PR CodeQL run 33267108013](https://github.com/sangmu1126/PipeLens/actions/runs/33267108013)
- [SQLAlchemy 2.0.52 PR CI run 33267721665](https://github.com/sangmu1126/PipeLens/actions/runs/33267721665)
- [SQLAlchemy 2.0.52 PR CodeQL run 33267721517](https://github.com/sangmu1126/PipeLens/actions/runs/33267721517)
- [컨테이너 취약점 최초 검출 CI run 33268226647](https://github.com/sangmu1126/PipeLens/actions/runs/33268226647)
- [컨테이너 보안 수정 검증 CI run 33268380682](https://github.com/sangmu1126/PipeLens/actions/runs/33268380682)
- [컨테이너 보안 수정 CodeQL run 33268380597](https://github.com/sangmu1126/PipeLens/actions/runs/33268380597)
- [컨테이너 SBOM CI run 33270531568](https://github.com/sangmu1126/PipeLens/actions/runs/33270531568)
- [컨테이너 SBOM CodeQL run 33270531626](https://github.com/sangmu1126/PipeLens/actions/runs/33270531626)
- [릴리스 자동화 기준 CI run 33272932733](https://github.com/sangmu1126/PipeLens/actions/runs/33272932733)
- [릴리스 자동화 기준 CodeQL run 33272932727](https://github.com/sangmu1126/PipeLens/actions/runs/33272932727)
- [v0.1.0 release run 33273157722](https://github.com/sangmu1126/PipeLens/actions/runs/33273157722)
- [PipeLens v0.1.0](https://github.com/sangmu1126/PipeLens/releases/tag/v0.1.0)

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

별도 compatibility job은 Python 3.14에서 integration directory를 제외한 106개 테스트와
10개 진단 평가를 실행한다. 지원 범위는 `>=3.12,<3.15`이며 3.12는 하한 전체 통합 검증,
3.14는 상한 직전 호환성 검증을 담당한다. 로컬 3.14에서는 일부 dependency가 Python 3.16을
앞두고 제거될 asyncio API에 대한 deprecation warning을 출력하지만 테스트 결과에는 영향을
주지 않는다.

현재 FastAPI/Starlette 테스트 클라이언트는 HTTPX 0.28.1에서 정상 동작하지만 Starlette가
향후 `httpx2` package 전환을 요구하는 deprecation warning을 출력한다. production HTTPX
client와는 별개인 테스트 adapter 경로이며, FastAPI·Starlette 지원 정책에 맞춘 전환을 후속
호환성 작업으로 관리한다.

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
- 빌드 직후 실제 image에서 OS와 language package를 검사하며 수정 가능한 HIGH/CRITICAL
  취약점이 있으면 실패한다. 수정 버전이 아직 없는 항목은 gate 대상에서 제외한다.
- 같은 image의 모든 발견 package를 CycloneDX JSON으로 만들고 형식과 component 존재를
  검증한 뒤 API·대시보드별 artifact로 14일간 보관한다.
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

Dependabot이 pip, npm, GitHub Actions, API·대시보드 Dockerfile의 base image와 Compose
service image 업데이트를 매주 월요일 순차 실행한다. 대시보드의 Node·Nginx 변경은 한 PR로
묶어 동일한 image build와 smoke test를 함께 거치게 한다. Compose는 별도 `docker-compose`
생태계로 PostgreSQL, Redis, Prometheus와 Grafana의 tag·digest 변경을 제안한다. Docker 설정을
처음 반영한 2026-08-29 검사에서 Docker 2개와 Python dependency 5개, 총 7개의 후속 PR이
생성됐다.

의존성 PR은 자동 생성과 현재 CI가 성공했다는 이유만으로 바로 merge하지 않았다.

- [#10](https://github.com/sangmu1126/PipeLens/pull/10)은 API runtime을 Python 3.12에서
  3.14로 변경했다. Python 3.14 compatibility와 API image 기동 smoke test를 `main`에 먼저
  추가한 뒤 PR을 rebase했고, 모든 gate 통과 후 `95b9970`으로 squash merge했다.
- [#11](https://github.com/sangmu1126/PipeLens/pull/11)은 Node 24→26과 Nginx 1.29→1.31을
  함께 변경했지만 merge하지 않고 닫았다. 2026-08-30 기준 Node 26은 Current이며 공식
  일정상 2026-10-28에 LTS로 전환될 예정이므로 Node major 자동 업데이트를 제외했다.
- 새 설정이 만든 [#17](https://github.com/sangmu1126/PipeLens/pull/17)은 Nginx
  1.29→1.31만 포함했다. 최신 `main` 기반에서 전체 CI, image build·non-root·HTTP smoke와
  CodeQL을 모두 통과해 `afff1ec`으로 squash merge했다.
- [#12](https://github.com/sangmu1126/PipeLens/pull/12)는 개발 전용 lint 도구 Ruff의 최소
  버전을 0.8에서 0.16.4로 갱신했다. 최신 `main`으로 PR을 재생성하고 전체 CI·CodeQL을
  통과했으며, 로컬 Ruff 0.16.5 검사와 백엔드 105개 테스트, 진단 평가 10/10 확인 뒤
  `e6016f0`으로 squash merge했다.
- [#13](https://github.com/sangmu1126/PipeLens/pull/13)은 HTTPX 최소 버전을 0.27에서
  0.28.1로 갱신했다. 제거 API 미사용, 관련 GitHub·OpenAI·retry·API 테스트 38개와 최신
  `main` 전체 CI·CodeQL 통과를 확인해 `47d2c60`으로 squash merge했다.
- [#14](https://github.com/sangmu1126/PipeLens/pull/14)는 Prometheus client 최소 버전을
  0.21에서 0.26.0으로 갱신했다. 독립 registry와 실제 `/metrics` 노출, pipeline·worker
  metric 기록 테스트 18개 및 최신 `main` 전체 CI·CodeQL을 통과해 `a117d2b`으로 squash
  merge했다.
- [#15](https://github.com/sangmu1126/PipeLens/pull/15)는 cryptography 지원 범위를
  44–46에서 50.0.1–50로 갱신했다. 50.0.0의 PKCS#7 oracle 보안 수정도 포함하지만 PipeLens는
  해당 API를 사용하지 않는다. Fernet OAuth token round-trip과 새 RS256 JWT 서명 테스트,
  최신 `main` 전체 CI·CodeQL을 통과해 `448565c`으로 squash merge했다.
- [#16](https://github.com/sangmu1126/PipeLens/pull/16)은 SQLAlchemy 최소 버전을 2.0에서
  2.0.52로 갱신했다. 로컬 SQLite 포함 전체 106개 테스트와 실제 PostgreSQL 17에서 Alembic
  `upgrade/check`, analysis lifecycle 및 Redis integration을 통과하고 `b8c5cf2`로 squash
  merge했다.

초기 #10–#16은 모두 판정됐다. #11의 Node 26은 LTS 전환 전 자동 major update 금지 정책으로
제외하고 Nginx만 #17로 재생성했다. 최종적으로 #10, #12–#17은 검증 후 merge했다.

Compose에서만 참조하는 PostgreSQL, Redis, Prometheus와 Grafana는 amd64·arm64를 포함한
manifest-list digest로 고정했고, digest 누락을 CI에서 차단한다. 별도 Compose Dependabot이
주간 업데이트 경로를 담당한다. GHCR release image의 장기 SBOM과 provenance 자동화는
`v0.1.0`에서 실행·검증됐다. GitHub Release 자체의 immutability는 아직 꺼져 있다.

## 3. 보안 통제 현황

### 구현·검증됨

- GitHub webhook HMAC-SHA256 검증
- GitHub App installation token 사용과 최소 권한 문서화
- GitHub App RS256 JWT 서명·공개키 검증 회귀 테스트
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
- 실제 빌드 이미지의 fixable HIGH/CRITICAL 취약점 gate
- 실제 빌드 이미지의 CycloneDX SBOM 생성·검증·단기 artifact 보관
- v0.1.0 GHCR digest의 SLSA provenance·CycloneDX SBOM 이중 경로 검증
- Compose service image의 multi-platform digest 고정과 주간 Dependabot 업데이트
- CodeQL과 pip·npm·Actions·Dockerfile dependency 자동 업데이트

### 미구현 또는 외부 설정 필요

- 다음 release 전 GitHub release immutability 활성화
- API·대시보드 Dockerfile base image digest 정책
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
2. 실제 공개 HTTPS 환경의 OAuth·webhook 검증

### P1 — 릴리스와 공급망

1. 다음 release 전에 GitHub release immutability 활성화
2. GHCR package retention 정책 확정

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
5. FastAPI·Starlette의 `httpx2` 테스트 클라이언트 전환 시점 검토

## 6. 현재 GitHub 저장소 관리 상태

2026-08-30 조회 결과:

- visibility: public
- default branch: `main`
- open issues: 0
- open pull requests: 0
- version tags: 1 (`v0.1.0`)
- releases: 1 (`v0.1.0`, immutable false)
- GHCR images: 2 (`pipelens-api`, `pipelens-dashboard`), 빈 인증 설정 manifest 조회 통과
- GHCR retention: 미확정
- branch protection: PR과 7개 GitHub Actions check 필수, 관리자 적용
- repository rulesets: 0
- open CodeQL alerts: 0
- repository description과 homepage: 비어 있음

열린 이슈가 없다는 것은 남은 작업이 없다는 뜻이 아니다. 위 P0/P1 항목을 GitHub issue 또는
milestone으로 옮겨 추적하는 작업이 필요하다.

## 7. 운영 전 체크리스트

- [ ] GitHub App 실제 설치와 E2E 증적
- [ ] production HTTPS와 HSTS
- [x] `main` PR·필수 status check
- [ ] immutable GitHub Release와 digest-pinned production 배포
- [x] fixable HIGH/CRITICAL container vulnerability scan
- [x] CI build image CycloneDX SBOM
- [x] release image SBOM·provenance
- [ ] secret manager와 rotation
- [ ] PostgreSQL backup/restore drill
- [ ] Alertmanager 연결
- [ ] 외부 fork 공격 입력 검증
- [ ] 부하 상태에서 시작 60초·완료 120초 SLO 검증
