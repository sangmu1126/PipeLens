# Worker replica 부하·장애 복구 drill

## 목적

Redis queue의 단일 job 복구만 확인하던 기존 통합 테스트를 넘어, 여러 worker replica가 동시에
backlog를 처리하는 동안 한 worker가 lease를 남기고 종료돼도 job 손실·중복 없이 사용자 관점
60초 시작/120초 완료 SLO 안에 회수되는지 검증한다.

이 drill은 queue·worker orchestration을 대상으로 한 합성 검증이다. GitHub API, LLM, 실제
PostgreSQL 쓰기와 게시 latency는 포함하지 않으므로 production 용량 판정으로 사용하지 않는다.

## CI 시나리오

`ops/worker/verify_replica_recovery.py`는 Compose와 같은 Redis image를 사용하는 backend CI에서
다음 순서로 실행된다.

1. 고유 queue에 첫 합성 분석 요청을 enqueue한다.
2. `abandoned` worker가 그 job을 processing list로 옮기고 ack 없이 중단된 상태를
   만든다.
3. lease 2초, heartbeat 0.5초인 worker replica 4개를 시작한다.
4. 나머지 199개 요청을 burst로 enqueue한다.
5. 살아 있는 replica의 lease는 유지하고, 만료된 `abandoned` processing list만 pending으로
   원자 복구한다.
6. 모든 job이 ack돼 pending, processing과 dedupe 상태가 비워질 때까지 기다린다.

검증기는 다음 조건 중 하나라도 어기면 실패한다.

- 200개 각각의 시작·완료 횟수가 정확히 1회가 아님
- 어떤 replica도 job을 하나도 처리하지 못함
- orphan recovery metric이 정확히 1이 아님
- 복구 job의 시작이 lease 2초와 CI scheduling grace 5초를 넘김
- 최대 queue wait가 60초 또는 최대 완료 latency가 120초를 넘김
- 완료 뒤 pending queue나 dedupe set이 남음

## 실행

Redis를 실행한 뒤 repository root에서 다음 명령을 사용한다.

```bash
python -m ops.worker.verify_replica_recovery \
  --redis-url redis://localhost:6379/0 \
  --jobs 200 \
  --replicas 4 \
  --output worker-drill.json
```

성공 출력은 replica별 처리량, 복구 job 수, 최대 시작·완료 latency와 orphan recovery latency를
JSON으로 남긴다. `--output`은 timestamp와 schema version, p50·p95·p99 latency, SLO 달성률,
throughput, exactly-once와 queue drain 결과도 파일로 보존한다. 매 실행은 UUID가 포함된 별도
Redis keyspace를 사용하고 성공·실패 여부와 관계없이 worker task, connection과 모든 drill key를
정리한다.

기본값은 기존 CI와 같은 단일 200-job burst다. production-representative arrival profile을 준비할
때는 초당 enqueue rate와 burst 크기, 합성 provider 처리 시간을 명시한다.

```bash
python -m ops.worker.verify_replica_recovery \
  --redis-url "$REDIS_URL" \
  --jobs 10000 \
  --replicas 8 \
  --enqueue-rate-per-second 25 \
  --burst-size 50 \
  --processing-seconds 0.25 \
  --lease-seconds 60 \
  --heartbeat-seconds 15 \
  --output /approved-evidence/worker-soak.json
```

rate를 지정하고 burst를 생략하면 job을 하나씩 일정하게 주입한다. burst를 지정하면 해당 크기를
즉시 넣고 누적 평균 rate에 맞춰 다음 batch를 기다린다. orphan 한 건을 먼저 claim하고 replica를
시작한 뒤 나머지 arrival stream을 주입하므로 앞쪽 job에 인위적인 enqueue 대기 시간이 더해지지
않는다.

## 해석과 운영 경계

- 60초/120초는 제품 기본 SLO와 같은 절대 상한이다. 합성 pipeline은 각 job에 10ms만 사용하므로
  이 결과만으로 실제 GitHub·LLM latency를 예측하지 않는다.
- 4개 in-process `AnalysisWorker`가 각자 독립 Redis connection, processing list와 lease를
  사용한다. container scheduler, CPU·memory limit과 network partition은 포함하지 않는다.
- production 전에는 실제 replica container, production과 같은 resource limit·provider 지연,
  장시간 arrival rate와 PostgreSQL connection pool을 포함한 별도 soak/load test가 필요하다.
- `--processing-seconds`는 일정한 합성 latency일 뿐 GitHub/OpenAI rate limit·5xx·jitter를 재현하지
  않는다. CPU·memory와 database pool saturation도 외부 telemetry에서 같은 timestamp로 결합한다.
- stale worker가 복구 뒤 뒤늦게 재개하는 fencing은 DB attempt token 회귀 테스트가 별도로
  검증한다. 이 drill의 abandoned worker는 재개하지 않는다.

## 병합 후 기준선

[main CI run 33323532906](https://github.com/sangmu1126/PipeLens/actions/runs/33323532906)의
GitHub-hosted runner에서 다음 결과로 통과했다.

| 항목 | 결과 |
| --- | ---: |
| 합성 job | 200 |
| replica별 처리 | 49 / 50 / 50 / 51 |
| 복구 job | 1 |
| 최대 시작 latency | 2.060초 |
| orphan recovery latency | 2.060초 |
| 최대 완료 latency | 2.071초 |

60초 시작·120초 완료 SLO와 lease 2초+grace 5초 상한을 모두 만족했고 정확한 1회 처리와 최종
queue drain도 통과했다.

## Rate-shaped evidence 기준선

2026-09-01 Docker Desktop arm64에서 고정 Redis 8.2 digest에 40 jobs, 20 jobs/s, burst 4,
합성 처리 30ms와 replica 4개를 적용했다. 각 replica가 10건씩 처리했고 orphan 1건을 1.074초에
복구했다. p95 시작 0.008초, p95 완료 0.039초, 관측 throughput 21.698 jobs/s, 두 SLO 달성률
100%와 exactly-once·queue drain을 확인했다. 이 짧은 결과는 도구 검증 기준선이며 #66의 production
capacity evidence가 아니다.

## 로컬 arm64 재검증

2026-08-31 Docker Desktop 29.6.2에서 Compose의 Redis 8.2 digest를 실행하고 임의 loopback
port로 같은 200-job/4-replica 시나리오를 통과했다.

| 항목 | 결과 |
| --- | ---: |
| replica별 처리 | 49 / 50 / 50 / 51 |
| 복구 job | 1 |
| 최대 시작 latency | 2.117초 |
| orphan recovery latency | 2.117초 |
| 최대 완료 latency | 2.128초 |

실행별 Redis keyspace와 고유 container를 사용했고 종료 뒤 container와 volume이 남지 않음을
확인했다. 상세 환경은 [Docker Desktop 로컬 통합 검증](local-docker-validation.md)에 기록했다.
