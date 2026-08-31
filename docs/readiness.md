# 검증 및 운영 준비 현황

## 1. 상태 요약

기준 시점: **2026-08-31**, 검증 기준 commit `ec691bc`, v0.1.0 source `320f6ae`.

| 영역 | 상태 | 근거 |
| --- | --- | --- |
| MVP 기능 코드 | 완료 | root `README.md` 기능 목록과 자동 테스트 |
| 고정 진단 평가 | 통과 | 10/10, 100%; CI 최소 기준은 80% |
| 백엔드 테스트 | 통과 | 로컬 121 passed, integration 2 skipped; CI에서 service integration 별도 통과 |
| Python 호환성 | 통과 | 3.12 전체 integration, 3.14 단위·API 113개와 진단 평가 10/10 |
| 대시보드 테스트 | 통과 | Node 22 CI, Node 24 로컬 검증, Vitest 4/4와 Vite production build |
| API·대시보드 이미지 | 통과 | 실제 Docker build, 최종 non-root USER 검사 |
| 대시보드 컨테이너 기동 | 통과 | CI에서 Nginx 기동 후 내부 8080 HTTP smoke test |
| 컨테이너 취약점 gate | 통과 | 실제 빌드 이미지의 fixable HIGH/CRITICAL OS·library 항목 0 |
| 컨테이너 SBOM | 통과 | CycloneDX 1.6: API 125개, 대시보드 71개 component artifact |
| GHCR release | 통과 | v0.1.0 이미지 2개와 digest별 provenance·SBOM attestation 검증 |
| GHCR 보존 정책 | 통과 | 정식 release·attestation 영구 보존, 월별 tag/digest 읽기 전용 감사 |
| Compose service image | 통과 | 5개 외부 image의 multi-platform digest 고정과 CI 정책 검사 |
| Prometheus runtime | 통과 | 3.13.2 LTS 설정·규칙 5개 검증과 실제 readiness smoke |
| Alertmanager routing | 통과 | 0.33.1 strict mode, Prometheus→Alertmanager→webhook CI drill |
| Uvicorn runtime | 통과 | 0.52.4, Python 3.12·3.14와 실제 API `/readyz` 기동 검증 |
| Redis runtime | 통과 | redis-py 8.1.0 RESP3와 Redis 8.2.9 Extended queue 통합 검증 |
| Worker replica drill | 통과 | 4 replica·200 job, orphan 1개 2.060초 복구, 최대 완료 2.071초 |
| PostgreSQL runtime | 통과 | 18.6 전용 volume, 17→18 dump/restore·Alembic·integration 검증 |
| Grafana runtime | 통과 | 13.2, 12→13 persistent-volume·provisioning·anonymous Viewer 검증 |
| GitHub Release 불변성 | 설정됨 | repository API `enabled: true`; 미래 release부터 적용, v0.1.0은 `immutable: false` 유지 |
| GitHub Actions Python runtime | 통과 | setup-python 7.0.0, Python 3.12·3.14 CI와 GHCR 감사 검증 |
| GitHub Actions 공급망 | 통과 | 모든 외부 action full commit SHA 고정과 mutable reference CI gate 통과 |
| OAuth token key rotation | 통과 | primary/fallback Fernet key ring, lazy 재암호화와 session 폐기 회귀 테스트 |
| 정적 보안 분석 | 통과 | Python·JavaScript/TypeScript CodeQL, open alert 0 |
| 실제 GitHub App E2E | 미검증 | 공개 HTTPS·App credentials가 필요한 외부 검증 |
| production 배포 | 미완료 | 서명 image는 있으나 공개 HTTPS·TLS·backup과 실제 service 배포 없음 |
| `main` 보호 | 설정됨 | PR, strict CI 5개·CodeQL 2개, conversation·linear history, 관리자 적용 |

최근 검증 실행:

- [`OAuth token key rotation PR #53`](https://github.com/sangmu1126/PipeLens/pull/53)
- [OAuth token key rotation PR CI run 33363411829](https://github.com/sangmu1126/PipeLens/actions/runs/33363411829)
- [OAuth token key rotation PR CodeQL run 33363411722](https://github.com/sangmu1126/PipeLens/actions/runs/33363411722)
- [`GitHub Actions SHA 고정 PR #51`](https://github.com/sangmu1126/PipeLens/pull/51)
- [GitHub Actions SHA 고정 PR CI run 33361752707](https://github.com/sangmu1126/PipeLens/actions/runs/33361752707)
- [GitHub Actions SHA 고정 PR CodeQL run 33361752698](https://github.com/sangmu1126/PipeLens/actions/runs/33361752698)
- [GitHub Actions SHA 고정 병합 후 CI run 33362037504](https://github.com/sangmu1126/PipeLens/actions/runs/33362037504)
- [GitHub Actions SHA 고정 병합 후 CodeQL run 33362037525](https://github.com/sangmu1126/PipeLens/actions/runs/33362037525)
- [`setup-python 7 PR #47`](https://github.com/sangmu1126/PipeLens/pull/47)
- [setup-python 7 PR CI run 33328357773](https://github.com/sangmu1126/PipeLens/actions/runs/33328357773)
- [setup-python 7 PR CodeQL run 33328357775](https://github.com/sangmu1126/PipeLens/actions/runs/33328357775)
- [setup-python 7 PR branch GHCR 감사 run 33328451609](https://github.com/sangmu1126/PipeLens/actions/runs/33328451609)
- [setup-python 7 병합 후 CI run 33328478789](https://github.com/sangmu1126/PipeLens/actions/runs/33328478789)
- [setup-python 7 병합 후 CodeQL run 33328478782](https://github.com/sangmu1126/PipeLens/actions/runs/33328478782)
- [setup-python 7 병합 후 GHCR 감사 run 33328498258](https://github.com/sangmu1126/PipeLens/actions/runs/33328498258)
- [`Ruff 0.16.5 PR #46`](https://github.com/sangmu1126/PipeLens/pull/46)
- [Ruff 0.16.5 PR CI run 33327919399](https://github.com/sangmu1126/PipeLens/actions/runs/33327919399)
- [Ruff 0.16.5 PR CodeQL run 33327919385](https://github.com/sangmu1126/PipeLens/actions/runs/33327919385)
- [Ruff 0.16.5 병합 후 CI run 33328022359](https://github.com/sangmu1126/PipeLens/actions/runs/33328022359)
- [Ruff 0.16.5 병합 후 CodeQL run 33328022350](https://github.com/sangmu1126/PipeLens/actions/runs/33328022350)
- [`Alertmanager routing 안정화 PR #48`](https://github.com/sangmu1126/PipeLens/pull/48)
- [Alertmanager routing 안정화 PR CI run 33327036671](https://github.com/sangmu1126/PipeLens/actions/runs/33327036671)
- [Alertmanager routing 안정화 PR CodeQL run 33327036669](https://github.com/sangmu1126/PipeLens/actions/runs/33327036669)
- [Alertmanager routing 병합 후 CI run 33327158576](https://github.com/sangmu1126/PipeLens/actions/runs/33327158576)
- [Alertmanager routing 병합 후 CodeQL run 33327158575](https://github.com/sangmu1126/PipeLens/actions/runs/33327158575)
- [`Alertmanager routing PR #45`](https://github.com/sangmu1126/PipeLens/pull/45)
- [Alertmanager routing PR CI run 33326106111](https://github.com/sangmu1126/PipeLens/actions/runs/33326106111)
- [Alertmanager routing PR CodeQL run 33326106102](https://github.com/sangmu1126/PipeLens/actions/runs/33326106102)
- [`Worker replica drill PR #43`](https://github.com/sangmu1126/PipeLens/pull/43)
- [Worker replica drill PR CI run 33323312380](https://github.com/sangmu1126/PipeLens/actions/runs/33323312380)
- [Worker replica drill PR CodeQL run 33323312384](https://github.com/sangmu1126/PipeLens/actions/runs/33323312384)
- [Worker replica drill 병합 후 CI run 33323532906](https://github.com/sangmu1126/PipeLens/actions/runs/33323532906)
- [Worker replica drill 병합 후 CodeQL run 33323532969](https://github.com/sangmu1126/PipeLens/actions/runs/33323532969)
- [`GHCR 보존 정책 PR #41`](https://github.com/sangmu1126/PipeLens/pull/41)
- [GHCR 보존 정책 PR CI run 33322207726](https://github.com/sangmu1126/PipeLens/actions/runs/33322207726)
- [GHCR 보존 정책 PR CodeQL run 33322207722](https://github.com/sangmu1126/PipeLens/actions/runs/33322207722)
- [병합 후 수동 GHCR 감사 run 33322294819](https://github.com/sangmu1126/PipeLens/actions/runs/33322294819)
- [`Grafana 13 PR #38`](https://github.com/sangmu1126/PipeLens/pull/38)
- [Grafana 13 PR CI run 33303557311](https://github.com/sangmu1126/PipeLens/actions/runs/33303557311)
- [Grafana 13 PR CodeQL run 33303557289](https://github.com/sangmu1126/PipeLens/actions/runs/33303557289)
- [Grafana 13 병합 후 CI run 33303638041](https://github.com/sangmu1126/PipeLens/actions/runs/33303638041)
- [Grafana 13 병합 후 CodeQL run 33303637927](https://github.com/sangmu1126/PipeLens/actions/runs/33303637927)
- [`PostgreSQL 18 PR #36`](https://github.com/sangmu1126/PipeLens/pull/36)
- [PostgreSQL 18 PR CI run 33302816133](https://github.com/sangmu1126/PipeLens/actions/runs/33302816133)
- [PostgreSQL 18 PR CodeQL run 33302816136](https://github.com/sangmu1126/PipeLens/actions/runs/33302816136)
- [PostgreSQL 18 병합 후 CI run 33302884926](https://github.com/sangmu1126/PipeLens/actions/runs/33302884926)
- [PostgreSQL 18 병합 후 CodeQL run 33302884947](https://github.com/sangmu1126/PipeLens/actions/runs/33302884947)
- [`Redis 8.2 Extended PR #34`](https://github.com/sangmu1126/PipeLens/pull/34)
- [Redis 8.2 PR CI run 33300129032](https://github.com/sangmu1126/PipeLens/actions/runs/33300129032)
- [Redis 8.2 PR CodeQL run 33300129030](https://github.com/sangmu1126/PipeLens/actions/runs/33300129030)
- [Redis 8.2 병합 후 CI run 33300182440](https://github.com/sangmu1126/PipeLens/actions/runs/33300182440)
- [Redis 8.2 병합 후 CodeQL run 33300182403](https://github.com/sangmu1126/PipeLens/actions/runs/33300182403)
- [`redis-py 8.1.0 PR #27`](https://github.com/sangmu1126/PipeLens/pull/27)
- [redis-py 8.1.0 PR CI run 33299569088](https://github.com/sangmu1126/PipeLens/actions/runs/33299569088)
- [redis-py 8.1.0 PR CodeQL run 33299569060](https://github.com/sangmu1126/PipeLens/actions/runs/33299569060)
- [redis-py 병합 후 CI run 33299653576](https://github.com/sangmu1126/PipeLens/actions/runs/33299653576)
- [redis-py 병합 후 CodeQL run 33299653632](https://github.com/sangmu1126/PipeLens/actions/runs/33299653632)
- [`Uvicorn 0.52.4 PR #25`](https://github.com/sangmu1126/PipeLens/pull/25)
- [Uvicorn 0.52.4 PR CI run 33295968358](https://github.com/sangmu1126/PipeLens/actions/runs/33295968358)
- [Uvicorn 0.52.4 PR CodeQL run 33295968363](https://github.com/sangmu1126/PipeLens/actions/runs/33295968363)
- [Uvicorn 병합 후 CI run 33296035915](https://github.com/sangmu1126/PipeLens/actions/runs/33296035915)
- [Uvicorn 병합 후 CodeQL run 33296035880](https://github.com/sangmu1126/PipeLens/actions/runs/33296035880)
- [`psycopg 3.3.4 PR #26`](https://github.com/sangmu1126/PipeLens/pull/26)
- [psycopg 3.3.4 PR CI run 33294950950](https://github.com/sangmu1126/PipeLens/actions/runs/33294950950)
- [psycopg 병합 후 CI run 33295005385](https://github.com/sangmu1126/PipeLens/actions/runs/33295005385)
- [psycopg 병합 후 CodeQL run 33295005394](https://github.com/sangmu1126/PipeLens/actions/runs/33295005394)
- [`Prometheus 3.13 LTS PR #29`](https://github.com/sangmu1126/PipeLens/pull/29)
- [Prometheus 3.13 LTS CI run 33293111339](https://github.com/sangmu1126/PipeLens/actions/runs/33293111339)
- [Prometheus 3.13 LTS CodeQL run 33293111348](https://github.com/sangmu1126/PipeLens/actions/runs/33293111348)
- [Prometheus LTS 병합 후 CI run 33293260308](https://github.com/sangmu1126/PipeLens/actions/runs/33293260308)
- [Prometheus LTS 병합 후 CodeQL run 33293260317](https://github.com/sangmu1126/PipeLens/actions/runs/33293260317)
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
5. Compose에 고정한 Prometheus image의 공식 `promtool`로 설정과 규칙 5개를 검사하고 실제
   server readiness 검증
6. `docker compose config --quiet`와 Grafana dashboard JSON 검증
7. Grafana 12.1에서 만든 비관리 dashboard와 같은 volume을 Compose Grafana 13.2로 승격해
   데이터 보존, file provisioning, Prometheus UID datasource와 익명 Viewer API 검증
8. PostgreSQL 17 source에 migration·표본 데이터를 만든 뒤 Compose PostgreSQL 18 target으로
   dump/restore하고 데이터와 `alembic check` 검증
9. Compose에 digest로 고정한 PostgreSQL 18과 Redis 8.2를 각각 pull·기동해 integration test 실행
10. `pipelens-evaluate --minimum-accuracy 0.8`

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
- [#46](https://github.com/sangmu1126/PipeLens/pull/46)은 Ruff 최소 버전을 0.16.5로 올렸다.
  preview 기능을 활성화하지 않은 현재 설정에서 lint, 전체 테스트와 최신 `main` CI·CodeQL을
  통과해 `d80ecff`로 squash merge했다.
- [#47](https://github.com/sangmu1126/PipeLens/pull/47)은 `actions/setup-python`을 Node 24 기반
  v7.0.0으로 갱신했다. 제거된 `pip-install` 입력은 사용하지 않으며 Python 3.12·3.14 CI와
  SHA 고정 action을 쓰는 GHCR 감사를 PR branch와 병합 후 `main`에서 각각 통과해 `9735a11`로
  squash merge했다.
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
- [#26](https://github.com/sangmu1126/PipeLens/pull/26)은 PostgreSQL driver의 최소 버전을
  psycopg 3.2에서 3.3.4로 갱신했다. Python 3.12·3.14 binary wheel, API image build·기동,
  PostgreSQL 17 migration·analysis lifecycle과 Redis integration을 최신 `main`에서 통과해
  `73e4641`로 squash merge했다.
- [#25](https://github.com/sangmu1126/PipeLens/pull/25)는 ASGI server Uvicorn의 최소 버전을
  0.30에서 0.52.4로 갱신했다. 공식 변경 기록에서 Python 3.14 지원과 제거·기본값 변경을
  검토하고 PipeLens가 제거 API, reload·worker·TLS option, WebSocket route나 experimental
  `zttp`를 사용하지 않음을 확인했다. Uvicorn 0.52.4, httptools 0.8.0, websockets 17.1로
  Python 3.12·3.14, 전체 테스트, CodeQL과 실제 API `/readyz` 기동을 통과해 `3b0b203`으로
  squash merge했다.
- [#27](https://github.com/sangmu1126/PipeLens/pull/27)은 비동기 queue client의 최소 버전을
  redis-py 5.2에서 8.1.0으로 갱신했다. 6·7 major의 cluster·Sentinel·TLS 변경은 현재 경로와
  무관함을 확인하고, 8.0의 RESP3·timeout·pool·retry 기본값은 실제 queue command 기준으로
  검토했다. Redis 7.4.11에서 enqueue·blocking dequeue·heartbeat·orphan recovery·acknowledge를
  수행하는 통합 테스트, Python 3.12·3.14 전체 테스트, API image·CodeQL을 통과해 `7258f5c`로
  squash merge했다. pool·retry의 고동시성 지연은 production 부하 검증 항목으로 유지한다.
- [#34](https://github.com/sangmu1126/PipeLens/pull/34)는 floating Redis 8.10 제안 #23 대신
  2030-09-01까지 지원되는 Redis 8.2 Extended를 선택했다. Compose의 8.2.9 digest를 CI가 직접
  pull·기동해 redis-py 8.1 RESP3 queue 통합 테스트를 수행하도록 만들고, patch·digest만 자동
  추적하게 했다. 역할별 `fd286c2`, `9bc43ee`, `9cfdfda`를 rebase merge했으며 새 경계 적용 후
  #23은 자동으로 닫혔다.
- [#36](https://github.com/sangmu1126/PipeLens/pull/36)은 PostgreSQL 18 한 줄 변경 제안 #24를
  직접 병합하지 않고 새 volume·복원 경계를 먼저 추가했다. PostgreSQL 17 migration과 표본
  데이터를 18.6으로 dump/restore하고 Alembic 일치와 실제 lifecycle integration을 검증했다.
  역할별 `3a13cff`, `791cabb`, `2a5ff15`를 rebase merge했으며 새 major 제외 정책 적용 후
  #24는 자동으로 닫혔다.
- [#38](https://github.com/sangmu1126/PipeLens/pull/38)은 Grafana image 한 줄 변경 제안 #21을
  직접 병합하지 않고 12.1→13.2 같은-volume migration을 먼저 검증했다. 비관리 dashboard와
  file provisioning, Prometheus UID datasource 및 익명 Viewer 접근을 실제 두 image에서
  확인했다. 역할별 `70e788d`, `0ee59e2`, `7a39980`을 rebase merge했고 #21은 자동으로 닫혔다.

초기 #10–#16은 모두 판정됐다. #11의 Node 26은 LTS 전환 전 자동 major update 금지 정책으로
제외하고 Nginx만 #17로 재생성했다. 최종적으로 #10, #12–#17은 검증 후 merge했다.

Compose에서만 참조하는 PostgreSQL, Redis, Prometheus, Alertmanager와 Grafana는 amd64·arm64를 포함한
manifest-list digest로 고정했고, digest 누락을 CI에서 차단한다. 별도 Compose Dependabot이
주간 업데이트 경로를 담당한다. Prometheus는 2027-07-31까지 지원되는 3.13 LTS, Redis는
2030-09-01까지 지원되는 8.2 Extended의 patch만 자동 추적한다. PostgreSQL은 18.6으로
전환하면서 17→18 논리 복원 drill과 전용 volume 경계를 추가했고 다음 major는 자동 제안하지
않는다. GHCR release image의 장기
SBOM과 provenance 자동화는 `v0.1.0`에서 실행·검증됐다. GitHub Release 불변성은
2026-08-30 repository 설정에서 활성화했으며, 소급 적용되지 않는 `v0.1.0`은 계속
`immutable: false`다.

## 3. 보안 통제 현황

### 구현·검증됨

- GitHub webhook HMAC-SHA256 검증
- GitHub App installation token 사용과 최소 권한 문서화
- GitHub App RS256 JWT 서명·공개키 검증 회귀 테스트
- OAuth state 검증, HttpOnly/SameSite session cookie
- 사용자 token Fernet 암호화 저장
- primary/fallback Fernet key ring과 로그인 시 lazy 재암호화
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
- 미래 GitHub Release의 tag·asset 변경을 막는 repository 불변성 설정
- Compose service image의 multi-platform digest 고정과 주간 Dependabot 업데이트
- CodeQL과 pip·npm·Actions·Dockerfile dependency 자동 업데이트

### 미구현 또는 외부 설정 필요

- API·대시보드 Dockerfile base image digest 정책
- production secret manager 연결과 실제 credential 주입
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

완료. 정식 SemVer image와 attestation은 영구 보존하며 실패한 부분 게시만 30일 격리와 참조
검사 뒤 수동 정리한다.

### P1 — 운영 신뢰성

1. production 규모의 PostgreSQL backup 보관·복원 시간과 Grafana 12→13 volume restore drill
2. Alertmanager의 실제 호출 채널과 production secret 연결
3. production secret manager 연결과 credential rotation drill
4. production resource limit·provider latency를 포함한 worker soak/load와 SLO 검증

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
- releases: 1 (`v0.1.0`, immutable false); repository 불변성은 미래 release 대상으로 활성화
- GHCR images: 2 (`pipelens-api`, `pipelens-dashboard`), 빈 인증 설정 manifest 조회 통과
- GHCR retention: 정식 release·attestation 영구 보존, 월별 자동 감사
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
- [x] 미래 GitHub Release의 repository 불변성 설정
- [ ] `immutable: true`인 차기 GitHub Release와 digest-pinned production 배포
- [x] fixable HIGH/CRITICAL container vulnerability scan
- [x] CI build image CycloneDX SBOM
- [x] release image SBOM·provenance
- [x] GHCR release·attestation 보존 정책과 자동 감사
- [x] 외부 GitHub Action full commit SHA 고정과 CI 정책 검사
- [x] Fernet rolling key rotation 구현과 secret·incident response runbook
- [ ] production secret manager 연결과 실제 credential rotation drill
- [x] PostgreSQL 17→18 합성 데이터 backup/restore CI drill
- [ ] production 규모 PostgreSQL backup/restore drill
- [x] Grafana 12→13 합성 persistent-volume migration CI drill
- [ ] production Grafana volume backup/restore drill
- [ ] production 조건의 worker replica soak/load test
- [x] Alertmanager routing과 로컬 webhook 통합 검증
- [ ] Alertmanager 실제 호출 채널 연결
- [ ] 외부 fork 공격 입력 검증
- [ ] 부하 상태에서 시작 60초·완료 120초 SLO 검증
