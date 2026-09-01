# 공개 HTTPS acceptance preflight

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

HSTS의 `includeSubDomains`와 `preload`는 상위 domain의 다른 service에 영향을 줄 수 있어 강제하지
않고 JSON에 현재 상태를 기록한다. operator가 전체 domain 소유권을 확인한 뒤 별도로 결정한다.
