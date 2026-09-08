# 2026-09-08 실제 GitHub App staging 실행

## 판정

실제 GitHub App, installation token, OAuth와 signed webhook을 사용한 branch·PR 실패 진단은
통과했고 별도 공개 fixture의 실제 외부 fork 격리도 통과했다. 다만 임시 Quick Tunnel의 HTTPS
preflight와 하나의 repository에 묶인 strict acceptance JSON·제한 원본 review는 통과하지 않았으므로
[#61](https://github.com/sangmu1126/PipeLens/issues/61)과
[#62](https://github.com/sangmu1126/PipeLens/issues/62)는 완료 처리하지 않는다.

## 환경과 권한

- PipeLens source revision: trusted run `b171dfe`, 최종 외부-fork run `bdee0bc`
- App: `pipelens-staging-acceptance`, App ID `4867714`
- installation ID: `159934172`
- repository selection: `selected`
- 설치 대상: `sangmu1126/PipeLens-acceptance`,
  `sangmu1126/PipeLens-external-fork-acceptance`
- 권한: Actions(read), Checks(write), Contents(read), Metadata(read), Pull requests(write)
- event: `workflow_run`
- staging: Docker Desktop의 API·worker·PostgreSQL 18·Redis 8.2·dashboard
- public origin: 실행 시간에만 유지되는 `trycloudflare.com` Quick Tunnel
- secret 주입: repository 밖 `0600` file을 API·worker에 read-only mount
- LLM provider: trusted run `none`; 외부-fork 최종 run은 `openai`와 무효 canary key를 활성화

App private key JWT와 installation token으로 GitHub API에 인증한 뒤 설치 대상과 권한을 다시
조회했다. 실제 secret, private key, OAuth token, webhook body와 delivery ID 원문은 문서나
repository에 보관하지 않았다.

## OAuth와 public webhook

PipeLens의 `/auth/github/login`에서 시작한 실제 GitHub OAuth는 state cookie 검증, callback code
교환과 dashboard redirect를 완료했다. 인증 직후 `/api/v1/me`와 `/api/v1/analyses`가 HTTP 200을
반환했다. App 설치·repository selection 변경 webhook과 실패 run의 signed
`workflow_run.completed` webhook도 public ingress를 지나 API에서 204 또는 202로 처리됐다.

초기 설치에서는 manifest의 `request_oauth_on_install`이 state cookie 없이 callback을 시작해
`invalid OAuth state`로 거부됐다. 이는 state 검증의 정상적인 fail-closed 결과였고, 명시적인
PipeLens login endpoint에서 다시 시작한 흐름은 성공했다.

## Branch failure와 Commit Check

- [실패 run 34184222277](https://github.com/sangmu1126/PipeLens-acceptance/actions/runs/34184222277)
- [PipeLens diagnosis Check](https://github.com/sangmu1126/PipeLens-acceptance/runs/101929245574)
- queue wait: `0.010s`
- analysis duration: `3.120s`
- total latency: `3.130s`
- 최초 Check 개수: `1`
- webhook 재전달 뒤 Check 개수와 URL: `1`, 동일 URL
- webhook delivery ID SHA-256: `e77b2dc56e883ea4a06cd04185cb12d180ee5b812df0f23f41331d40266a4317`

worker는 installation token을 만들고 실제 Actions log·run·job·workflow·commit을 읽은 뒤 Commit
Check를 생성했다. 재전달 뒤 PostgreSQL의 해당 run 분석 행과 delivery는 각각 1개였고 worker는
완료된 분석을 다시 실행하지 않았다.

### 실제 dependency resolver 분류 재검증

최초 fixture는 dependency failure 문구를 수동 출력해 게시 경로는 검증했지만 분류기가 runner의
exit line을 핵심 오류로 선택해 category가 `unknown`이었다. acceptance repository의 fixture를
존재하지 않는 `pip==0.0.0` version을 실제로 요청하도록 바꿨다. 외부 package code는 설치되지 않는다.

- fixture revision: `acafd7179ca8767c04ee42d9572df1d6cbc96ff7`
- [실패 run 34185336066](https://github.com/sangmu1126/PipeLens-acceptance/actions/runs/34185336066)
- [PipeLens diagnosis Check](https://github.com/sangmu1126/PipeLens-acceptance/runs/101932484081)
- category: `dependency_installation_failure`
- confidence: `0.9`
- queue wait: `0.006s`
- analysis duration: `3.135s`
- total latency: `3.141s`
- webhook 재전달 뒤 Check 개수와 URL: `1`, 동일 URL
- webhook delivery ID SHA-256: `386e325643397ef7abd254d45c6ea49dc7851619ceb30a16cd7c6e80dba4a281`

## PR failure와 comment

- [실패 run 34184453918](https://github.com/sangmu1126/PipeLens-acceptance/actions/runs/34184453918)
- [acceptance PR #1](https://github.com/sangmu1126/PipeLens-acceptance/pull/1)
- [PipeLens diagnosis comment](https://github.com/sangmu1126/PipeLens-acceptance/pull/1#issuecomment-5578799736)
- queue wait: `0.004s`
- analysis duration: `3.089s`
- total latency: `3.093s`
- 대상 run marker를 가진 comment 개수: `1`
- webhook 재전달 뒤 대상 comment 개수와 URL: `1`, 동일 URL
- webhook delivery ID SHA-256: `650d352b0f1c5e3c30973680d89022aef6ccc6e793db1c4a01c041eabeaf7395`

comment에는 검증된 log 근거, 관련 변경 파일, PipeLens 상세 링크와 workflow run ID가 포함됐다.
같은 PR에 branch push run용 comment도 하나 존재하지만 서로 다른 run marker를 사용한다. 대상 PR
run의 comment upsert 판정은 해당 marker 기준으로 1개다.

## 실제 외부 fork 격리와 발견한 결함

공개 가능한 최소 base repository
[`sangmu1126/PipeLens-external-fork-acceptance`](https://github.com/sangmu1126/PipeLens-external-fork-acceptance)와
조직 소유 fork `NewJeanSe/PipeLens-external-fork-acceptance`를 만들었다. 실제
[cross-repository PR #1](https://github.com/sangmu1126/PipeLens-external-fork-acceptance/pull/1)의
head repository owner는 `NewJeanSe`이고 base owner는 `sangmu1126`이다. Fork는 존재하지 않는
`pip==0.0.0`만 선택하므로 package code를 설치하거나 실행하지 않고 resolver가 실패한다.

최초 두 run에서 GitHub run API는 `event: pull_request`와 외부 `head_repository`를 반환했지만
`pull_requests`는 빈 배열이었다. PipeLens는 이를 `untrusted_fork`로 분류해 LLM과 Commit Check를
차단했지만 PR 번호를 알 수 없어 계약상 필요한 경고 comment도 게시하지 못했다. commit-to-PR API도
빈 결과였고, `head=<owner>:<branch>` PR 목록은 PR #1을 반환했다.

`bdee0bc`에서는 workflow run이 외부 fork이고 PR 배열이 비었을 때만 head owner·branch로 PR을 찾고,
head SHA·head repository·base repository가 모두 일치하는 결과가 정확히 하나일 때만 컨텍스트를
채택하도록 수정했다. 불일치·0개·복수 결과는 기존처럼 게시하지 않는 fail-closed 동작을 유지한다.

- [최종 실패 run 34187478447](https://github.com/sangmu1126/PipeLens-external-fork-acceptance/actions/runs/34187478447)
- [외부-fork 경고 comment](https://github.com/sangmu1126/PipeLens-external-fork-acceptance/pull/1#issuecomment-5579290723)
- trust level: `untrusted_fork`
- queue wait: `0.005s`
- analysis duration: `3.392s`
- total latency: `3.398s`
- provider 활성 상태의 `model_name`·`prompt_version`: 둘 다 `null`
- worker 재기동 이후 OpenAI endpoint request log match: `0`
- fork SHA의 Check: GitHub Actions 자체 Check `1`, PipeLens Check `0`
- 경고와 run marker를 가진 PipeLens comment: `1`
- webhook 재전달 뒤 분석 행·comment 개수와 URL: `1`, `1`, 동일 URL
- webhook delivery ID SHA-256: `882dea4d7f080d3b26756ee38c9916b0d5a000808720d51422006600cd99b31e`

무효 canary key는 repository 밖 `0600` secret file로만 주입했다. 외부-fork 격리가 실패했다면 실제
OpenAI endpoint 요청 시도와 LLM fallback metadata가 남도록 provider를 활성화했으나 둘 다 없었다.
따라서 provider가 꺼져 있어서 우연히 0건인 검사가 아니라 trust boundary가 호출을 건너뛴 결과다.

## Synthetic secret scan

세 trusted run은 실제 credential이 아닌 run ID 기반 token 모양의 seeded value를 log에 출력했다.
원문 대신 SHA-256만 기록한다.

| Run | Seed SHA-256 | Persistence | PR comment | Commit Check | Provider request |
| --- | --- | ---: | ---: | ---: | ---: |
| `34184222277` | `b999230b9bfed07f2a429130c0f25706c5e5b16281b2bd6094cfea7c47e84df3` | 0 | 0 | 0 | 0 |
| `34184453918` | `7db9ba0df1fee5bb1e7353127d50961c1a182b693e2710a2bffe0fd39e479d04` | 0 | 0 | 0 | 0 |
| `34185336066` | `64752c4a6f3e45b519caac754bff48d80df1e62f0969c7a34610daec914910a7` | 0 | 0 | 0 | 0 |

Provider match는 `PIPELENS_LLM_PROVIDER=none`인 staging에서 외부 provider request 자체가 0임을
뜻한다. 실제 LLM provider redaction과 latency 증적은 이 실행 범위에 없다.

## 실행 중 발견하고 수정한 결함

1. dashboard nginx가 `/webhooks/github`를 SPA로 보내던 누락을 수정했다.
   [PR #100](https://github.com/sangmu1126/PipeLens/pull/100)에서 API reverse proxy와 회귀 test를
   추가했다.
2. 실제 OAuth callback query의 code와 state가 nginx·Uvicorn access log에 남는 문제를 발견했다.
   [PR #101](https://github.com/sangmu1126/PipeLens/pull/101)에서 nginx를 query 없는 path log로
   바꾸고 API access log를 비활성화했다. 새 public probe의 query marker가 container log에 없음을
   확인했다.
3. 최초 App 설치에서 본 저장소를 잘못 선택했으나 실행 전에 installation 설정을 고쳐
   `PipeLens-acceptance` 하나만 접근함을 installation token으로 확인했다. 외부-fork 검증 시에는
   공개 base fixture만 추가하고 installation token으로 두 저장소 목록을 다시 확인했다.
4. 실제 fork run에서 GitHub가 `pull_requests: []`를 반환해 경고 comment가 누락되는 결함을 발견했다.
   `bdee0bc`에서 owner·branch 검색 뒤 SHA와 양쪽 repository를 검증하는 fail-closed 복구를 추가했고,
   새 실제 run과 재전달에서 경고 comment 한 개가 같은 URL로 유지됨을 확인했다.

## 남은 완료 조건

- Quick Tunnel은 account·SLA·고정 hostname이 없는 개발용 endpoint다. HTTPS verifier는 HTTP
  origin이 exact HTTPS origin으로 영구 redirect되지 않아 실패했다.
- trusted branch·PR과 외부-fork run이 서로 다른 base repository여서 현재 strict acceptance JSON의
  단일 repository 계약으로 묶지 않았다.
- 실제 성공하는 LLM provider의 품질·token·비용과 provider 429·5xx fault는 검증하지 않았다.
- raw GitHub·ingress·database audit를 승인된 장기 evidence storage에 보관한 production review가
  아니다.

따라서 이 문서는 #61의 모든 개별 실행 조건에 대한 실제 staging 증적이지만, 하나의 repository에
묶인 strict acceptance JSON이나 승인된 원본 review 및 production HTTPS 완료 증적을 대신하지 않는다.
