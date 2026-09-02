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

## Production soak 증적 계약

`verify_replica_recovery.py`의 JSON은 queue invariant와 latency의 한 입력이다. #66의 실제
production-representative 결과는 CPU·memory·PostgreSQL·Redis telemetry, provider audit와 fault
injection을 함께 정규화한 `ops/worker/soak-observation.example.json` 형식으로 기록한다. 체크인
예제는 schema 설명용이며 실제 soak 결과가 아니다.

사전에 다음 값을 승인된 test plan에 고정한다.

- 1시간 이상의 duration, job 수, arrival rate, burst, concurrency와 worker replica 수
- worker별 CPU·memory, PostgreSQL pool과 server max connection, Redis maxmemory
- GitHub·LLM latency profile과 주입할 429·일시적 5xx 수
- worker termination, expired lease와 Redis network interruption의 시점·복구 상한
- 60초/120초 SLO, 최소 attainment, 허용 resource utilization과 capacity headroom

실행 뒤 기존 runner output, 같은 UTC window의 container/DB/Redis telemetry와 provider/fault audit를
대조한다. 세 원본 bundle은 접근 제한된 위치에 두고 lowercase SHA-256만 observation에 입력한다.
Redis URL/password, database URL, provider endpoint/token, request·response body, repository와 job
payload는 JSON에 넣지 않는다.

```bash
cp ops/worker/soak-observation.example.json \
  /secure/work/worker-soak-observation.json

.venv/bin/python -m ops.worker.verify_soak_evidence \
  --input /secure/work/worker-soak-observation.json \
  --output /secure/work/worker-soak-evidence.json
```

기본 판정은 다음을 요구한다.

1. 실제·계획 duration 모두 3,600초 이상이고 arrival/burst/concurrency가 명시됨
2. replica별 PostgreSQL pool 합계가 server max connection 이하
3. GitHub와 LLM 각각 실제 latency 표본, 429와 transient failure 1회 이상, 모든 retry 회복
4. worker termination·expired lease·network interruption 각각 120초 이내 회복, lost job 0
5. 모든 job 완료, duplicate/lost 0, exactly-once와 final queue drain
6. p95 시작 60초·완료 120초 이하와 두 SLO attainment 99% 이상
7. CPU·memory·Redis peak 90% 이하, PostgreSQL pool/server connection budget 이하
8. 측정 max 이하이면서 tested arrival rate 이상, 20% 이상 headroom을 둔 reviewer 승인 capacity
   recommendation
9. runner·telemetry·provider audit artifact의 SHA-256과 secret scan match 0

승인된 운영 기준이 다르면 `--min-duration-seconds`, `--min-slo-attainment-percent`,
`--max-resource-utilization-percent`, `--max-fault-recovery-seconds`를 명시하고 change record에 이유를
남긴다. 기준을 느슨하게 바꾼 실행은 #66 reviewer가 acceptance와 별도로 비교해야 한다.

Strict JSON은 임의 필드와 URL 형태 resource identifier를 거부한다. 유효하지만 기준을 어긴 관측은
`passed: false`와 exit 1로 보존하고, schema·timestamp·count 관계가 신뢰 불가능하면 출력 없이
종료한다. 결과는 owner 원문을 `owner_documented`로 축약하고 secret이나 raw artifact를 포함하지
않는다.

Reviewer는 source revision·soak ID·UTC window와 artifact hash가 원본 runner, telemetry와 provider
audit에 일치하는지 확인한다. resource limit이 실제 container/deployment에 적용됐는지, network
interruption이 단순 synthetic sleep이 아닌지, PostgreSQL pool과 Redis maxmemory가 관측 대상과
같은지 검토한다. 이 원본 review와 실제 장시간 실행 전에는 #66을 닫지 않는다.

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
