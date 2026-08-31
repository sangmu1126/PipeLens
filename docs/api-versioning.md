# API versioning과 deprecation 정책

## 현재 계약

PipeLens가 대시보드와 외부 API consumer에 제공하는 JSON resource API의 현재 major version은
`v1`이며 base path는 `/api/v1`이다.

| v1 endpoint | 용도 | 이전 alias |
| --- | --- | --- |
| `GET /api/v1/me` | 로그인 사용자와 installation | `GET /api/me` |
| `GET /api/v1/analyses` | 분석 목록·filter·cursor pagination | `GET /api/analyses` |
| `GET /api/v1/analyses/{run_id}` | 분석 상세 | `GET /api/analyses/{run_id}` |
| `PUT /api/v1/analyses/{run_id}/feedback` | 분석 feedback upsert | `PUT /api/analyses/{run_id}/feedback` |

health, readiness와 metrics는 workload 운영 endpoint이므로 `/healthz`, `/readyz`, `/metrics`를
유지한다. GitHub OAuth·App 설치 callback과 webhook은 브라우저 또는 GitHub에 등록하는 protocol
endpoint이므로 resource API major path에 포함하지 않는다. 해당 payload version은 GitHub 계약과
별도로 검토한다.

생성된 전체 계약은 [OpenAPI JSON](openapi.json)에 있다. FastAPI runtime schema와 이 파일이
다르면 CI가 실패한다.

## 호환성 규칙

`v1` 안에서 허용하는 변경은 기존 consumer가 같은 요청을 보내고 기존 response field를 읽을 수
있는 additive 변경으로 제한한다.

- optional response field·optional query parameter와 새 endpoint 추가는 허용한다.
- 기존 field 제거·이름 변경·type 변경, required request field 추가, status code 의미 변경은
  breaking change다.
- enum 값 추가도 exhaustive consumer를 깨뜨릴 수 있으므로 명시적 migration 없이 조용히
  추가하지 않는다.
- pagination ordering, cursor 의미, 인증·installation 접근 범위와 멱등성 변경은 schema 모양이
  같아도 behavioral breaking change로 취급한다.
- breaking change는 `/api/v2`처럼 새 major path에 병렬 제공하고 consumer migration 뒤 이전
  major를 폐기한다.

application version과 API major는 별개다. patch/minor application release가 `v1`의 additive
변경을 포함할 수 있지만 기존 `v1` 의미를 깨뜨릴 수는 없다.

## Legacy alias deprecation

무버전 `/api/*` alias는 2026-08-31부터 deprecated다. 동작과 response body는 현재 `v1`과 같게
유지하지만 다음 두 신호를 제공한다.

- OpenAPI operation의 `deprecated: true`
- RFC 9745 형식의 `Deprecation: @1788134400`과 이 문서를 가리키는
  `Link: <...>; rel="deprecation"` response header

아직 제거 날짜를 승인하지 않았으므로 `Sunset` header는 보내지 않는다. 제거하려면 replacement가
production에서 검증되고, 사용량 또는 access log로 legacy consumer가 식별되며, public 공지 뒤
최소 180일이 지나야 한다. 제거 날짜가 정해지면 HTTP-date 형식의 `Sunset` header, release note와
migration 결과를 함께 추가한다.

현재 migration은 path의 `/api`를 `/api/v1`으로 바꾸는 것뿐이며 method, query, request와 response
schema는 같다. PipeLens 대시보드는 이미 `v1`만 사용한다.

## 계약 변경 절차

1. route, request·response model 또는 status/header 동작을 변경한다.
2. 호환성 규칙에 따라 additive인지 새 major가 필요한지 판단하고 decision record를 남긴다.
3. schema를 다시 생성한다.

   ```bash
   .venv/bin/python ops/ci/export_openapi.py --write
   ```

4. `docs/openapi.json` diff에서 path, required field, enum, response와 security 변화를 검토한다.
5. 다음 검사를 실행한다.

   ```bash
   .venv/bin/python ops/ci/export_openapi.py --check
   .venv/bin/pytest -q tests/test_api_contract.py
   cd frontend && npm test -- --run && npm run build
   ```

6. breaking change라면 구·신 major 병렬 운영, dashboard 전환, deprecation signal과 제거 조건을
   같은 PR 또는 연결된 migration PR에 기록한다.

생성 파일만 갱신해 CI를 통과시키는 것은 호환성 승인으로 간주하지 않는다. OpenAPI가 표현하지
못하는 ordering, authorization과 멱등성도 테스트와 문서 diff에서 함께 검토한다.

## 자동 검증 증적

- 로컬: backend 126 passed, 2 skipped, dashboard 4 passed와 production build
- [PR #55 CI run `33364795817`](https://github.com/sangmu1126/PipeLens/actions/runs/33364795817):
  committed OpenAPI와 runtime schema 일치, Python 3.12·3.14, dashboard, container와 service
  integration 통과
- [PR #55 CodeQL run `33364795825`](https://github.com/sangmu1126/PipeLens/actions/runs/33364795825):
  Python·JavaScript/TypeScript 분석 통과
- [병합 후 `main` CI run `33365087414`](https://github.com/sangmu1126/PipeLens/actions/runs/33365087414)와
  [CodeQL run `33365087411`](https://github.com/sangmu1126/PipeLens/actions/runs/33365087411):
  rebase된 최종 v1 계약에서 OpenAPI gate, 전체 5개 CI job과 두 언어 분석 통과
