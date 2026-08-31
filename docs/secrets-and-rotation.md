# 비밀값 관리, 키 교체와 침해 대응

## 범위와 완료 기준

이 문서는 PipeLens가 사용하는 비밀값의 보관 경계, 정기 교체 순서와 노출 사고 대응 절차를
정의한다. 저장소에는 실제 production 값, 암호화된 값, secret manager resource ID를 넣지 않는다.
배포 환경은 승인된 secret manager 또는 동등한 workload identity 기반 주입 수단으로 값을
process environment나 읽기 전용 file에 제공해야 한다.

현재 자동 검증은 OAuth access token용 Fernet key ring과 기존 token의 lazy 재암호화까지
포함한다. 특정 secret manager 연결, GitHub App production credential 교체와 실제 incident
훈련은 외부 환경 증적이 생기기 전까지 완료로 간주하지 않는다.

## 비밀값 목록

| 설정 | 용도 | 교체 영향과 경계 |
| --- | --- | --- |
| `PIPELENS_WEBHOOK_SECRET` | GitHub webhook HMAC 검증 | GitHub App 설정과 수신 service를 함께 변경해야 한다. 단일 값만 지원한다. |
| `PIPELENS_GITHUB_PRIVATE_KEY` | App JWT 서명 | GitHub가 여러 private key를 허용하므로 새 key 검증 뒤 이전 key를 폐기한다. |
| `PIPELENS_GITHUB_CLIENT_SECRET` | 사용자 OAuth code 교환 | 새 secret으로 login canary를 통과한 뒤 이전 secret을 폐기한다. |
| `PIPELENS_SESSION_SECRET` | OAuth state HMAC | 진행 중인 OAuth state는 무효화될 수 있지만, production의 기존 session token 암호화와 session hash에는 사용하지 않는다. |
| `PIPELENS_TOKEN_ENCRYPTION_KEY` | 새 GitHub user access token 암호화 | key ring의 첫 key이며 모든 새 암호화와 lazy 재암호화에 사용한다. |
| `PIPELENS_TOKEN_ENCRYPTION_FALLBACK_KEYS` | 기존 access token 복호화 | 쉼표로 구분한 Fernet key 목록이다. primary로 해독되지 않는 token에만 사용한다. |
| `PIPELENS_OPENAI_API_KEY` | 선택적 OpenAI 호출 | 새 key canary 뒤 이전 key를 provider에서 폐기한다. log와 진단 결과에 값을 남기지 않는다. |
| `PIPELENS_DATABASE_URL` | PostgreSQL 인증 | provider의 dual credential 또는 사용자 교체 기능을 우선 사용하고 migration·readiness를 확인한다. |
| `PIPELENS_REDIS_URL` | Redis queue 인증 | API와 모든 worker가 같은 전환 window를 사용하고 enqueue/dequeue·lease recovery를 확인한다. |
| Alertmanager receiver secret | 외부 incident 채널 호출 | repository 기본 config에는 넣지 않으며 환경별 Alertmanager config에 secret manager로 주입한다. |

비밀값 inventory에는 실제 값 대신 secret version, 소유자, 생성·교체·폐기 시각, 다음 교체 예정일,
적용 workload와 마지막 검증 run만 기록한다. 접근 권한은 배포 service와 교체 담당자에게만 주고,
조회·변경 audit log를 보존한다.

## Fernet token encryption key 무중단 교체

Fernet key는 다음 명령으로 각각 새로 만든다.

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

`PIPELENS_TOKEN_ENCRYPTION_KEY`가 primary이고 fallback은 쉼표 순서대로 복호화에만 사용된다.
primary로 복호화하지 못했지만 fallback으로 성공한 로그인은 같은 access token을 primary로 즉시
재암호화해 DB에 저장한다. key 값 자체와 token 평문은 log에 기록하지 않는다.

무중단 rolling deployment는 다음 세 단계로 수행한다.

1. 새 key를 생성해 secret manager에 새 version으로 저장한다. 기존 key는 폐기하지 않는다.
2. 모든 instance를 **기존 primary + 새 fallback**으로 배포한다. 이 단계에서 구·신 instance가
   모두 두 key로 생성된 token을 읽을 준비를 한다.
3. 모든 instance를 **새 primary + 기존 fallback**으로 배포한다. 새 로그인은 새 key를 사용하고,
   기존 token은 사용될 때 lazy 재암호화된다.
4. 최소 `PIPELENS_SESSION_TTL_DAYS`와 rollback 관찰 기간이 모두 지난 뒤 이전 key를 fallback에서
   제거한다. 그 전에 모든 이전 deployment가 종료됐는지 확인한다.
5. 새 로그인, 기존 session, installation 동기화와 분석 목록 접근을 확인하고 secret version과
   검증 시각만 증적으로 남긴다.

2단계를 생략하면 rollout 중 이전 instance가 새 key로 생성된 token을 해독하지 못할 수 있다.
문제가 생기면 두 key를 유지한 채 기존 key를 다시 primary로 두어 rollback한다. key가 실제로
노출된 경우에는 관찰 기간을 기다리지 않고 모든 OAuth session을 폐기하고 이전 key를 즉시
제거하며 사용자가 다시 로그인하도록 한다.

## 다른 credential의 교체

### GitHub App private key

1. GitHub App 설정에서 새 private key를 생성하고 fingerprint를 별도 채널로 확인한다.
2. secret manager에 새 version을 추가하고 API·worker를 새 key로 배포한다.
3. App JWT 발급, installation token 발급과 읽기 전용 GitHub API 요청을 canary로 확인한다.
4. 모든 instance가 새 key를 사용한 뒤 GitHub App 설정에서 이전 key를 삭제한다.

GitHub는 App당 여러 private key를 허용하므로 새 key를 먼저 배포해 downtime 없이 교체한다.

### Webhook secret

PipeLens와 GitHub App 설정은 각각 단일 webhook secret을 사용한다. maintenance window에서 새
고엔트로피 값을 준비하고, 수신 service와 GitHub App webhook 설정을 연속해서 변경한다. 전환
중 HMAC 실패한 delivery ID를 기록하고 새 secret 적용 뒤 재전달한다. GitHub는 실패한 webhook을
자동 재전달하지 않으므로 최근 delivery와 응답 상태를 직접 확인해야 한다.

### OAuth client·session secret

새 OAuth client secret을 배포한 뒤 로그인→callback→installation 조회를 canary로 확인하고 이전
secret을 폐기한다. session secret 교체 시 이미 발급된 로그인 session은 유지되지만 전환 전에
시작한 OAuth state는 실패할 수 있으므로 로그인 오류율을 확인한다. 침해 상황에서는 OAuth
session을 모두 폐기하고 재로그인을 요구한다.

### Provider·database·queue credential

OpenAI, PostgreSQL, Redis와 incident receiver는 provider가 dual credential을 지원하면 추가→
배포→검증→폐기 순서를 사용한다. 지원하지 않으면 maintenance window와 rollback credential을
확보한다. 교체 뒤 OpenAI 최소 요청, DB migration/readiness, Redis enqueue/dequeue와 Alertmanager
firing/resolved canary 중 해당 경로를 검증한다.

## 침해 대응

1. 노출된 credential, 영향 workload, 최초·최종 노출 가능 시각과 audit event를 식별한다.
2. 배포와 로그 접근을 제한하고 credential을 새 version으로 교체한다. 공개 저장소나 log에 값이
   있었다면 history 삭제만으로 해결된 것으로 보지 않고 즉시 폐기한다.
3. GitHub private/client secret, provider key와 webhook secret은 외부 서비스에서도 폐기한다.
   token encryption key 노출이면 모든 OAuth session을 폐기한다.
4. GitHub App permission 변경, 비정상 installation token 발급, webhook HMAC 실패, LLM 사용량,
   DB·Redis 접속과 incident receiver 호출을 노출 window 전체에서 조사한다.
5. 실패 webhook은 새 secret 배포 뒤 delivery ID로 재전달하고 PipeLens의 workflow run 멱등성이
   중복 분석·게시를 막는지 확인한다.
6. incident ID, timeline, 영향 범위, 폐기한 secret version, 검증 run과 재발 방지 조치를 남긴다.
   실제 secret과 access token은 incident 문서에도 기록하지 않는다.

## 교체 증적 체크리스트

- [ ] 승인된 secret manager와 workload identity가 연결됨
- [ ] secret inventory의 owner·version·rotation deadline이 최신임
- [ ] Fernet 3단계 rolling rotation과 기존 session 접근을 staging에서 검증함
- [ ] GitHub App private key·OAuth client secret canary와 이전 credential 폐기를 확인함
- [ ] webhook secret 전환 중 실패 delivery를 재전달함
- [ ] OpenAI·PostgreSQL·Redis·incident receiver 중 사용 중인 credential을 검증함
- [ ] 로그, DB dump, artifact와 incident 기록에 secret 평문이 없음을 확인함
- [ ] rollback 또는 강제 session 폐기 결과를 기록함

이 체크리스트의 실제 날짜, 환경, secret version과 run ID가 없으면 production rotation 완료로
표시하지 않는다.
