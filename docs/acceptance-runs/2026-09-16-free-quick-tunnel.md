# 2026-09-16 무료 Quick Tunnel 실제 GitHub 경계 재검증

## 목적과 범위

OpenAI를 활성화하지 않고 Docker Desktop의 전체 PipeLens 스택을 account 없는
Cloudflare Quick Tunnel로 공개해 GitHub OAuth, signed `workflow_run` webhook, Redis worker,
규칙 진단과 Commit Check 게시 경계를 다시 검증했다. 실행 source는 PipeLens
`f5c470e`, acceptance repository `acafd71`이다.

이 실행은 비용 없는 실제 기능 검증이며 production ingress 승인은 아니다. Quick Tunnel은
고정 hostname과 SLA가 없고 HTTP origin의 exact HTTPS 301·308 redirect와 HSTS를 보장하지
않으므로 #62는 닫지 않는다.

## 환경

- public origin: `https://discretion-remedy-chairman-winner.trycloudflare.com`
- ingress: account-less Cloudflare Quick Tunnel, `cloudflared` 2026.8.3, HTTP/2
- application: Docker Compose API, worker, dashboard, PostgreSQL 18, Redis 8.2
- GitHub App: `pipelens-staging-acceptance`, acceptance repository 한 개만 선택
- LLM provider: `none`
- App private key: repository 밖 PEM, mode `0600`, API·worker에 read-only mount
- 민감값: `.env`와 로컬 PEM에만 보관하고 문서·Git·출력에 기록하지 않음

## 실행 결과

1. 공개 `/readyz`는 HTTP 200과 database·queue `ok`를 반환했다.
2. OAuth start는 GitHub authorize endpoint, exact public callback, non-empty state를 반환했고
   state cookie는 Secure·HttpOnly·SameSite=Lax였다.
3. 실제 GitHub callback 후 2026-09-16T08:37:02Z에 새 암호화 session이 생성됐고
   GitHub user 1명과 App installation 1개가 연결됐다.
4. [intentional failure run 35074952820](https://github.com/sangmu1126/PipeLens-acceptance/actions/runs/35074952820)은
   2026-09-16T08:39:12Z에 `workflow_dispatch`로 시작해 통제된 `pip==0.0.0` resolver
   실패로 종료했다.
5. GitHub App delivery는 requested·in-progress에 HTTP 204, completed에 HTTP 202를 받았다.
   completed delivery는 2026-09-16T08:39:22.967Z에 0.5초로 완료됐고 redelivery가
   아니었다.
6. 분석은 queue wait 0.012055초, processing 5.459710초, 전체 5.471765초에
   `completed`가 됐다. 분류는 `dependency_installation_failure`, confidence 0.9,
   matched rule은 `dependency.install`이었다.
7. `model_name`은 비어 있어 OpenAI 호출 없이 규칙 기반 fallback만 사용했다.
8. [PipeLens diagnosis Check 104725115425](https://github.com/sangmu1126/PipeLens-acceptance/runs/104725115425)가
   `completed/neutral`로 게시됐다. Check summary·text와 DB의 classification·diagnosis에
   `synthetic-token=`과 `ghp_` prefix가 없어 fixture secret이 노출되지 않았다.

## 한계와 후속

- 최초 Quick Tunnel은 약 2시간 후 `Tunnel not found`로 폐기되어 새 hostname을
  발급했다. 이는 account-less 무료 endpoint의 예상된 제약이다.
- HTTPS preflight는 앱에 도달하기 전 HTTP→HTTPS exact permanent redirect 조건에서
  실패했다. 나머지 public readiness, OAuth redirect, secure state cookie는 개별로 통과했다.
- #62를 완료하려면 출시 시점의 고정 hostname ingress에서 permanent redirect, HSTS,
  browser logout, forwarding audit과 제한 보관 증적을 다시 수집해야 한다.
- OpenAI 실제 품질·token·비용 검증은 요청대로 최후 단계로 유보한다.
