# 2026-09-09 production-representative worker soak

## 결론

launch 전 실제 사용자 트래픽이 없는 상태에서 승인한 합성 arrival와 provider profile을 Docker
Desktop의 제한된 PostgreSQL·Redis·worker 환경에 적용했다. 세 번째 실행
`worker-soak-20260909-r3`이 3,601.127초 동안 3,605건을 처리했고 strict verifier의 9개 check가
모두 `true`, 최종 `passed: true`였다.

이는 현재 launch capacity 모델에 대한 #66 acceptance다. 실제 production cluster나 실제
GitHub/OpenAI endpoint의 최대 용량을 뜻하지 않는다. 운영 30일 또는 peak가 아래 1 job/s를 넘으면
실제 payload·provider 분포와 replica별 container limit으로 다시 실행한다.

## 승인한 계획과 환경

| 항목 | 값 |
| --- | ---: |
| source revision | `c19646280e478ff6933e68e2c18afb3ca9b0b557` |
| Docker Engine / platform | 29.6.2 / Linux arm64 |
| 계획 duration | 3,600초 |
| job / arrival / burst | 3,605 / 1 job/s / 4 |
| logical worker replica | 4 |
| worker 제한 | 합계 1 CPU, 512 MiB |
| replica별 budget share | 0.25 CPU, 128 MiB |
| PostgreSQL pool / server max | 20 / 50 connections |
| Redis maxmemory | 128 MiB, `noeviction` |
| 시작 / 완료 SLO | 60초 / 120초 |

네 `AnalysisWorker`는 한 process 안에서 서로 다른 Redis connection, processing list, worker ID와 lease를
사용했다. CPU·memory cgroup은 worker별 container 네 개가 아니라 이 process container 하나에
1 CPU/512 MiB로 적용했고 observation의 `each` 값은 그 합계를 네 replica에 균등 배분한 budget
share다. PostgreSQL도 replica별 실제 application pool 네 개 대신 격리 pool emulator 하나가
`application_name=pipelens-soak-pool`로 20개 실연결을 유지했다. 따라서 scheduler·pod별 편차는 이번
결과에 포함되지 않는다.

Python 3.14 slim 이미지는 source revision에서 새로 만들었고 local image ID는
`sha256:904c9722d7b2ca93bdd2821c24970d02672e0d9ac8922baea7191d5717731dc3`였다. 기존 staging
Compose와 분리된 `pipelens-soak` network, PostgreSQL·Redis와 고유 queue keyspace를 사용했다.

## 실행 결과

| 측정 | 결과 |
| --- | ---: |
| container 관측 duration | 3,601.127초 |
| arrival 실측 / 계획 | 3,600.011초 / 3,600초 |
| 처리 job | 3,605 / 3,605 |
| replica별 처리 | 901 / 901 / 902 / 901 |
| throughput | 1.001 job/s |
| 시작 p50 / p95 / p99 | 0.001 / 0.003 / 0.004초 |
| 완료 p50 / p95 / p99 | 0.255 / 0.262 / 0.264초 |
| orphan 복구 | 30.080초 |
| 시작·완료 SLO 달성률 | 100% / 100% |
| duplicate / lost | 0 / 0 |
| 최종 queue | drained |

실행 중 Docker stats, PostgreSQL `pg_stat_activity`, Redis `INFO memory`를 235회 수집했다. 첫 표본은
container 시작 18.785초 뒤, 마지막 표본은 종료 4.943초 전이다. script의 목표 간격은 10초지만 세
container의 순차 `docker stats --no-stream` 비용 때문에 실제 간격은 약 15초였다.

| resource peak | 결과 | 제한 대비 |
| --- | ---: | ---: |
| worker CPU | 2.25% | 1 CPU cgroup 기준 |
| worker memory | 12.20% | 512 MiB cgroup 기준 |
| PostgreSQL pool | 20 | 20 budget |
| PostgreSQL total | 29 | 50 max |
| Redis memory | 1.264536% | 128 MiB maxmemory 기준 |

## Provider와 장애 주입

실제 loopback TCP HTTP server를 사용해 credential이나 외부 호출 없이 GitHub형 150ms, LLM형
1.2초 latency를 재현했다. provider마다 논리 요청 20회, 실제 HTTP 22회였고 첫 429와 다음 503을
각각 한 번 주입했다. GitHub형 p50/p95는 0.159/0.313초, LLM형은 1.210/2.422초였으며 네 fault를
모두 retry로 회복했다. 이 audit은 실제 GitHub/OpenAI의 품질·token·비용 측정이 아니다.

- 별도 0.25 CPU/128 MiB worker가 job을 claim한 뒤 container를 SIGKILL했다. 준비 timestamp부터
  운영 명령과 lease 만료 대기를 포함해 51.507초 뒤 교체 worker가 만료 lease 한 건을 회수했다.
- Redis container를 Docker network에서 분리하고 5초 뒤 다시 연결했다. probe의 실제 failure 감지부터
  DNS·connection 회복까지 21.196초였고 pending job은 손실 없이 한 번 처리됐다.
- 같은 전역 Redis 단절을 주 runner도 직접 겪었다. worker와 producer가 연결 오류를 기록하고
  재시도했으며 process는 종료되지 않았다. 종료 시 processing list 고립, duplicate, lost job은 0이었다.

## Capacity 판단

같은 1 CPU/512 MiB worker 제한에서 601건, 5 jobs/s, burst 20을 별도 고유 queue로 실행했다.
117.303초 동안 5.123 jobs/s를 처리했고 시작 p95 1.032초, 완료 p95 1.286초, SLO 달성률 100%,
duplicate/lost 0과 queue drain을 확인했다.

검증한 상한은 5 jobs/s로 제한한다. 포화점을 찾지 않았으므로 5.123을 실제 최대 용량으로 외삽하지
않는다. 권장 launch admission은 4 jobs/s, logical replica 4개로 두어 검증 상한 대비 20%를 남긴다.
현재 예상 1 job/s에는 그보다 더 큰 여유가 있다. 상한 위 limiting resource는 측정하지 않았으므로
`tested-rate-ceiling`으로 기록했다.

## 실패 실행과 수정 판단

성공 결과를 만들기 전에 두 실행을 거부했다.

1. 첫 실행은 3,601 jobs, 1 job/s, burst 4였다. 3,596.013초 동안 enqueue하고 전체
   3,596.273초를 관측해 처리·SLO는 통과했지만 3,600초 기준보다 3.727초 짧았다. Mac 절전으로
   늘어난 wall clock을 duration에 더하지 않았다. orphan probe와 마지막 burst 뒤 대기 없음까지
   계산하는 `planned_arrival_seconds`와 `--minimum-arrival-seconds`를 추가해 짧은 계획을 Redis 연결
   전에 거부했다(`05ddd00`).
2. 두 번째 실행은 3,605 jobs로 계획을 바로잡았지만 Redis network 분리 때 producer의 EVAL timeout이
   전파돼 runner가 exit 1했다. cleanup도 Redis DNS가 아직 복구되지 않아 ConnectionError를 냈다.
   worker 시작·dequeue 경로는 Redis 오류 뒤 heartbeat 간격으로 재시도하고, producer는 60초 안에서
   같은 idempotency key로 enqueue를 재시도하도록 수정했다. timeout 전에 EVAL이 반영된 불확실한
   요청은 재접속 뒤 dedupe 응답으로 성공을 판별한다(`c196462`). 전체 412 tests, 2 skipped가 통과한
   source로 세 번째 실행을 새로 시작했다.

Pool emulator 준비 과정에서도 임의로 가정한 비밀번호가 실제 격리 DB와 달라 첫 container가
인증 실패했고, 같은 shell command의 임시 변수 확장 순서 때문에 빈 비밀번호를 전달한 두 번째
container도 실패했다. 세 번째에는 PostgreSQL container 설정에서 값을 출력하지 않고 같은 shell
scope로 전달해 20개 connection을 확인한 뒤 주 실행을 시작했다. 이 준비 실패는 성공 시간창에
포함하거나 resource 결과로 사용하지 않았다.

## 증적과 redaction

- [`runner-bundle.json`](runner-bundle.json): 계획, source/image, 제한, 주·capacity 결과와 fault audit
- [`telemetry.json`](telemetry.json): timestamp별 container·PostgreSQL·Redis 관측
- [`provider-audit.json`](provider-audit.json): provider별 latency·status·retry 집계
- [`observation.json`](observation.json): strict verifier 입력
- [`evidence.json`](evidence.json): 공개 가능한 정규화 판정, `passed: true`

세 원본 SHA-256은 observation에 고정했다. 파일에는 endpoint URL, credential, request/response body,
repository payload가 없고 로컬 redaction audit match는 0이다. PR의 `Repository secret scan`이 같은
파일을 다시 검사해야 최종 병합한다.
