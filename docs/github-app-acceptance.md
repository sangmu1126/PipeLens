# 실제 GitHub App E2E 증적 절차

이 문서는 테스트 저장소에 설치한 실제 GitHub App으로 #61의 PR 실패, branch 실패,
webhook 재전달과 외부 fork 신뢰 경계를 검증하고 redacted JSON 증적을 만드는 절차다.
`ops/acceptance/github-app-observation.example.json`은 schema 예제일 뿐 실제 실행 증적이 아니다.

## 완료 경계

다음 항목을 모두 실제 외부 환경에서 확인해야 #61 완료 후보가 된다.

- App이 지정한 테스트 저장소에 설치되고 Actions(read), Checks(read/write), Contents(read),
  Pull requests(read/write), Metadata(read)만 가진다.
- 의도적으로 실패한 PR workflow가 webhook 저장 후 60초 안에 분석을 시작하고 120초 안에
  완료된다.
- PR 코멘트에 근거, 관련 파일과 GitHub Actions run link가 있고 재전달 뒤 같은 URL의 한 개
  코멘트가 갱신된다.
- PR이 없는 branch 실패는 Commit Check 한 개를 만들고 재전달 뒤 같은 Check URL을 갱신한다.
- seeded secret의 SHA-256과 게시물·persistence·provider request scan count 0을 기록한다.
- 외부 fork PR은 경고 코멘트를 게시하지만 LLM 호출과 Commit Check 게시가 각각 0이다.
- 실제 run ID, run URL, 게시 URL, UTC timeline과 측정 latency를 보존한다.

검증기와 체크인 예제의 통과, local mock, 일반 PipeLens CI는 위 외부 사실을 증명하지 않는다.
#62의 public TLS, OAuth callback, signed webhook delivery 검증도 이 절차와 별도로 완료해야 한다.

## 사전 조건

1. production과 분리된 PipeLens staging, GitHub App과 테스트 저장소를 준비한다.
2. App 설정과 installation repository selection을 운영자 두 명이 확인한다. 테스트 저장소 외
   repository가 선택되어 있으면 시작하지 않는다.
3. `PIPELENS_PUBLISH_CHECKS=true`와 60초/120초 SLO를 설정하고 API, worker, PostgreSQL,
   Redis readiness를 확인한다.
4. 실패 workflow에는 실제 credential과 무관한 고유 seeded secret을 넣는다. 값은 evidence
   JSON, issue, PR, CI artifact나 shell history에 복사하지 않는다.
5. GitHub audit와 App 설정, PipeLens DB query, provider request audit의 원본을 접근 제한된
   저장소에 보관한다. 공개 증적에는 원본 대신 아래 정규화 결과만 넣는다.

## 실행 순서

1. source revision과 시작 UTC 시각, repository URL, installation ID와 실제 permission을 기록한다.
2. 테스트 PR에서 marker가 있는 workflow를 의도적으로 실패시킨다. GitHub run ID/URL과
   `workflow_run.completed` webhook DB 저장 시각, 분석 시작·완료·게시 시각을 수집한다.
3. PR 코멘트 URL을 열어 근거, 관련 파일, run link가 실제로 렌더링되는지 각각 확인한다.
4. PR과 연결되지 않은 테스트 branch에서 별도 workflow를 실패시키고 같은 timeline과 Commit
   Check URL을 수집한다. PR과 branch는 서로 다른 run ID여야 한다.
5. GitHub에서 두 `workflow_run.completed` delivery를 한 번씩 재전달한다. 재전달 전후 게시
   URL과 해당 run의 PipeLens 게시물 개수를 기록한다. 전후 URL과 count 1이 같아야 한다.
6. 외부 fork PR의 실패 workflow를 전달한다. 경고 PR 코멘트 URL을 기록하고 worker/provider
   audit에서 LLM invocation 0, fork SHA Commit Check publication 0을 확인한다.
7. 모든 exercise 뒤 seeded secret을 PR 코멘트·Commit Check, persistence 대상과 provider request
   audit에서 exact match로 검색한다. 값은 폐기하고 lowercase SHA-256과 영역별 match count만
   관측 JSON에 적는다.
8. 종료 시각을 기록하고 원본 audit의 reviewer, 보관 위치와 retention을 비공개 change record에
   연결한다. 발견된 문제는 증적을 성공으로 고치지 말고 failed JSON과 별도 issue로 남긴다.

## 관측 JSON 계약

예제를 복사해 실제 값으로 바꾸되 임의 필드를 추가하지 않는다.

```bash
cp ops/acceptance/github-app-observation.example.json \
  /secure/work/github-app-observation.json

python ops/acceptance/verify_github_app_evidence.py \
  --input /secure/work/github-app-observation.json \
  --output /secure/work/github-app-evidence.json
```

기본 threshold는 분석 시작 60초, 완료 120초다. 두 값 모두 webhook이 DB에 저장된
`webhook_recorded_at`을 기준으로 계산한다. 승인된 다른 SLO를 평가할 때만
`--max-start-seconds`와 `--max-completion-seconds`를 명시한다.

입력은 1 MiB 이하의 strict JSON이며 다음 원칙을 따른다.

- 모든 timestamp는 UTC offset이 있는 ISO 8601이고 acceptance window 안에서 시간순이어야 한다.
- repository, Actions run, PR comment와 Commit Check는 credential·query가 없는
  `https://github.com/...` URL이어야 하고 모두 같은 repository에 속해야 한다.
- URL의 run ID와 PR 번호는 별도 숫자 필드와 일치해야 한다.
- permission은 정확한 다섯 항목만 받는다. GitHub의 read/write 설정은 정규화 JSON에서
  `checks: write`, `pull_requests: write`로 기록한다. `write`는 해당 resource read를 포함한다.
- seeded secret 값, App private key, webhook/OAuth secret, delivery body, log, diff, provider
  payload, database row와 access token은 입력하지 않는다. unknown field는 거부된다.
- 실패한 acceptance도 도구가 읽을 수 있는 유효 관측이면 `passed: false` 증적을 쓰고 exit 1을
  반환한다. schema·URL·시간 관계가 잘못된 입력은 출력 없이 종료한다.

출력은 두 run의 ID/URL과 게시 URL, redelivery URL/count, 전체 timeline, 계산된 latency,
secret fingerprint/count, fork side-effect count, threshold, 개별 check와 입력 SHA-256을 보존한다.
출력 파일에 원본 secret이 없음을 별도로 검사한 뒤 승인된 evidence 위치에 첨부한다.

## 판정과 리뷰

자동 판정은 다음 check를 모두 요구한다.

- 최소 권한 일치와 PR/branch workflow conclusion `failure`
- PR/branch 분석 시작·완료 SLO
- PR 코멘트 필수 내용
- PR 코멘트와 branch Check의 URL 동일성 및 전후 count 1
- 세 영역의 seeded-secret match 0
- 외부 fork LLM invocation과 Commit Check publication 0

Reviewer는 JSON 통과 외에도 GitHub App installation/permission 화면, 각 run과 게시 URL,
webhook delivery, DB timeline, provider audit와 scan 원본이 같은 acceptance ID와 source revision을
가리키는지 확인한다. 원본 접근 권한이나 retention이 불명확하면 통과시키지 않는다.

## 보관과 정리

- 공개 가능: verifier output, run ID/URL, PR comment/Check URL, latency와 check 결과.
- 제한 보관: App 설정 screenshot/export, delivery ID와 body, DB/provider audit, reviewer 서명.
- 금지: credential 원문, seeded secret 원문, installation token, 사용자 OAuth token, unredacted
  logs/diff/workflow/provider request.
- 테스트 뒤 seeded credential을 폐기하고 App의 repository selection이 테스트 저장소로만 남았는지
  재확인한다. 실제 운영 credential과 production traffic은 이 drill 범위 밖이다.

결과가 통과해도 #61 본문의 모든 acceptance와 security criterion을 reviewer가 대조하기 전에는
issue를 닫지 않는다. 실제 URL이 private repository를 노출하면 공개 문서 대신 접근 제한된
evidence location만 issue에 연결한다.
