# 브라우저 OAuth·대시보드 E2E

## 목적과 완료 경계

Playwright의 실제 Chromium으로 로그인 전 화면부터 OAuth redirect, callback, session cookie,
인증된 대시보드와 logout까지 검증한다. DOM 단위 테스트가 대신할 수 없는 브라우저 navigation,
Vite reverse proxy와 cookie jar의 결합을 확인하는 회귀 테스트다.

GitHub 운영 계정과 자격증명은 사용하지 않는다. `ops/browser_e2e.py`가 같은 FastAPI process에
제어된 OAuth 승인 화면을 추가하고 GitHub token·user·installation API 응답을
`httpx.MockTransport`로 제공한다. 따라서 외부 network, rate limit과 계정 상태 없이도 다음
애플리케이션 경계를 반복 검증한다.

1. 로그인 전 `/api/v1/me`의 `401` 처리와 로그인 링크
2. OAuth client ID, callback URL과 매번 새로 생성되는 서명 state
3. state cookie를 거친 authorization-code callback
4. HttpOnly·SameSite=Lax session cookie와 OAuth state cookie 삭제
5. installation이 있는 사용자 대시보드와 분석 목록 영역
6. logout 뒤 session cookie 삭제와 로그인 화면 복귀

실제 `github.com`, production HTTPS, Secure cookie와 실제 GitHub App 설치는 검증하지 않는다.
이 항목은 [공개 HTTPS acceptance](https-acceptance.md)의 실제 E2E 증적과 공개 환경 P0 인수
테스트로 계속 관리한다.

## 로컬 실행

Python 프로젝트 가상환경과 frontend package를 준비한 뒤 Chromium을 한 번 설치한다.

```bash
.venv/bin/pip install -e '.[dev]'
npm --prefix frontend ci
npx --prefix frontend playwright install chromium
npm --prefix frontend run test:e2e
```

Playwright가 `.venv/bin/python`으로 FastAPI test server를 `127.0.0.1:8000`에, Vite를
`127.0.0.1:5173`에 기동하고 종료한다. 다른 Python 실행 파일이 필요하면 `PYTHON` 환경변수로
지정한다.

## CI

dashboard job은 Python 3.12와 Node 22를 함께 준비하고 다음 순서로 실행한다.

1. backend runtime과 frontend lockfile dependency 설치
2. Vitest 4개 단위·접근성 테스트
3. `playwright install --with-deps chromium`
4. Chromium OAuth·dashboard E2E
5. TypeScript와 Vite production build

Playwright trace는 실패한 실행에서만 유지된다. `test-results/`와 `playwright-report/`는 생성
산출물이므로 Git에서 제외한다.

## 검증 증적

- [PR #57](https://github.com/sangmu1126/PipeLens/pull/57)
- [CI run 33385076481](https://github.com/sangmu1126/PipeLens/actions/runs/33385076481):
  dashboard job에서 Python 3.12·Node 22, Chromium OAuth E2E 1개, Vitest 4개와 production
  build 통과; backend·Python 3.14·두 container job도 통과
- [CodeQL run 33385076451](https://github.com/sangmu1126/PipeLens/actions/runs/33385076451):
  Python과 JavaScript/TypeScript 분석 통과

## 유지보수 규칙

- production OAuth route와 session 동작을 사용하고, 브라우저에서 API 응답을 직접 stub하지
  않는다.
- 외부 GitHub 요청을 추가하지 않는다. 필요한 provider 동작은 test server에 최소 응답으로
  추가한다.
- Vitest와 Playwright 수집 경로를 분리한다. 브라우저 spec은 `frontend/e2e/`에만 둔다.
- callback host·cookie 정책·Vite proxy가 바뀌면 이 테스트와 production Nginx 경계를 함께
  검토한다.

참고: [Playwright 설치](https://playwright.dev/docs/intro),
[web server 설정](https://playwright.dev/docs/test-webserver),
[브라우저 격리](https://playwright.dev/docs/browser-contexts).
