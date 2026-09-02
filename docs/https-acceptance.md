# 공개 HTTPS acceptance

## 목적과 완료 경계

공개 ingress를 연결한 직후 TLS와 PipeLens의 비인증 경계를 같은 계약으로 반복 검증한다. probe는
read-only GET만 보내며 인증서 검증을 비활성화하는 option을 제공하지 않는다.

검증 범위:

1. HTTP origin의 exact HTTPS origin 301·308 영구 redirect
2. 신뢰 체인·hostname·유효 기간을 포함한 기본 TLS certificate 검증
3. `max-age=31536000` 이상 HSTS
4. dashboard의 CSP, Permissions Policy, Referrer Policy, nosniff와 frame 차단 header
5. `/readyz`의 HTTP 200, database·queue `ok`
6. GitHub OAuth authorize endpoint와 exact callback URL
7. non-empty OAuth state와 Secure·HttpOnly·SameSite=Lax state cookie

이 검사는 실제 GitHub 사용자 로그인, App 설치, callback code 교환, logout, signed webhook delivery와
reverse proxy forwarding 증적을 만들지 않는다. 따라서 성공해도 issue #62를 완료 처리하지 않는다.

## 실행

project dependency를 설치한 환경에서 공개 origin을 지정한다.

```bash
.venv/bin/python -m ops.acceptance.verify_https \
  https://pipelens.example.com \
  --output https-preflight.json
```

HTTPS가 표준 443이 아니거나 HTTP entrypoint가 별도 port이면 명시한다.

```bash
.venv/bin/python -m ops.acceptance.verify_https \
  https://pipelens.example.com:8443 \
  --http-origin http://pipelens.example.com:8080 \
  --output https-preflight.json
```

실패하면 exit code 1과 민감값을 포함하지 않는 요약을 stderr에 출력한다. 성공 JSON은 timestamp,
origin, status code, header 검증 결과, readiness와 OAuth flag만 포함한다. OAuth state, cookie 값,
client ID와 response body는 기록하지 않는다.

## 실제 인수 절차

preflight 성공 뒤 #62의 나머지 절차를 수행한다.

1. GitHub App의 callback, setup과 webhook URL이 같은 public origin인지 확인한다.
2. 실제 브라우저에서 login→installation 선택→dashboard→logout을 완료한다.
3. Secure·HttpOnly·SameSite cookie와 forwarding scheme·host를 browser/network evidence로 확인한다.
4. GitHub가 보낸 signed `workflow_run` webhook이 ingress를 지나 처리되는지 확인한다.
5. preflight JSON, redacted screenshot/request, timestamp와 delivery ID를 승인된 위치에 보존한다.

## 실제 E2E 관측 준비

`ops/acceptance/https-e2e-observation.example.json`은 실제 실행 결과가 아닌 schema 예제다.
production과 분리된 staging public hostname에서 다음 원본을 수집한다.

- GitHub App 설정의 callback, setup, webhook URL과 변경 audit
- 실제 브라우저의 login, GitHub authorization, installation 선택, dashboard, logout timeline
- OAuth state와 session cookie의 Secure·HttpOnly·SameSite 속성 및 logout 뒤 session 401
- ingress/app request audit에서 확인한 forwarded scheme·host, application origin과 redirect URI
- GitHub의 `workflow_run.completed` delivery, HMAC-SHA256 검증·저장·응답 timeline
- credential을 가린 screenshot bundle과 request evidence bundle

브라우저 개발자 도구나 trace를 저장하기 전에 OAuth code, state, cookie value, access token과
사용자 정보를 제거한다. Webhook 원본의 signature, delivery body, repository 식별자와 IP도 공개
artifact에 넣지 않는다. 원본은 접근 제한된 evidence storage에서 reviewer만 확인한다.

각 redacted bundle은 승인된 도구로 SHA-256을 계산한다. GitHub delivery ID도 원문 대신
lowercase SHA-256만 관측 JSON에 넣는다. 같은 acceptance ID와 source revision이 모든 원본에
표시되어야 하지만 credential이나 raw payload를 JSON에 복사해서는 안 된다.

## 실제 E2E 증적 검증

예제를 제한된 작업 디렉터리로 복사해 실제 관측값으로 바꾸고 검증한다.

```bash
cp ops/acceptance/https-e2e-observation.example.json \
  /secure/work/https-e2e-observation.json

.venv/bin/python -m ops.acceptance.verify_https_e2e_evidence \
  --input /secure/work/https-e2e-observation.json \
  --output /secure/work/https-e2e-evidence.json
```

검증기는 provider나 ingress에 접속하지 않으며 1 MiB 이하 strict JSON만 읽는다. 모든 URL은
credential·query·fragment가 없는 같은 public HTTPS origin이어야 한다. `localhost`, IP literal,
single-label host와 `.local`은 실제 public hostname 증적으로 받지 않는다.

자동 판정은 다음을 모두 요구한다.

1. 같은 origin의 통과한 preflight JSON SHA-256과 실행 시각
2. exact `/auth/github/callback`, `/github/setup`, `/webhooks/github` 설정
3. 시간순 login→authorization→installation→dashboard→logout과 installation 1개 이상
4. OAuth state·session cookie의 Secure·HttpOnly·SameSite=Lax와 logout 뒤 session 무효화
5. 브라우저 navigation 중 관측한 forwarded `https`, exact host·application origin·redirect URI
6. HMAC 검증된 `workflow_run.completed`, HTTP 202와 기본 10초 이내 ingress 응답
7. browser screenshot, forwarding request, webhook request와 delivery ID의 SHA-256

승인된 ingress가 다른 webhook 응답 상한을 사용하면
`--max-webhook-response-seconds`를 명시하고 change record에 근거를 남긴다. False 상태는 유효한
관측이면 `passed: false` JSON과 exit 1로 보존한다. unknown field, unsafe URL, 역전·미래 timestamp,
잘못된 hash처럼 증적 자체가 신뢰 불가능하면 출력 없이 종료한다.

## Reviewer 판정과 보관

Reviewer는 verifier output만 보지 않고 제한 보관 원본의 timestamp, origin, source revision과
artifact hash를 대조한다. GitHub 설정 URL, 인증된 사용자에게 허용된 installation, logout 뒤 401,
ingress forwarding audit, webhook signature 검증 결과가 같은 실행인지 확인한다.

- 공개 가능: verifier output, public origin, UTC timeline, status·count·boolean, artifact SHA-256.
- 제한 보관: redacted screenshot/request bundle, GitHub 설정 audit, delivery ID 원문과 delivery audit.
- 금지: OAuth code/state, cookie value, client/webhook secret, access/installation token, signature,
  raw delivery body, unredacted browser trace와 request log.

이 검증은 workflow 진단 내용, PR 코멘트·Commit Check와 외부 fork 처리를 판정하지 않는다. 해당
항목은 [실제 GitHub App E2E 증적](github-app-acceptance.md)과 #61에서 검토한다. 반대로 #61의
실제 run 성공만으로 TLS, browser session과 public ingress webhook을 완료 처리할 수 없다.

검증기와 체크인 예제의 통과는 실제 public deployment가 아니다. reviewer가 원본을 확인하고 #62의
모든 acceptance criterion을 대조하기 전까지 issue와 readiness 체크박스를 닫지 않는다.

HSTS의 `includeSubDomains`와 `preload`는 상위 domain의 다른 service에 영향을 줄 수 있어 강제하지
않고 JSON에 현재 상태를 기록한다. operator가 전체 domain 소유권을 확인한 뒤 별도로 결정한다.
