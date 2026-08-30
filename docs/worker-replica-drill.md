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

1. 고유 queue에 합성 분석 요청 200개를 원자적으로 enqueue한다.
2. `abandoned` worker가 가장 오래된 job 하나를 processing list로 옮기고 ack 없이 중단된 상태를
   만든다.
3. lease 2초, heartbeat 0.5초인 worker replica 4개를 시작한다.
4. 살아 있는 replica의 lease는 유지하고, 만료된 `abandoned` processing list만 pending으로
   원자 복구한다.
5. 모든 job이 ack돼 pending, processing과 dedupe 상태가 비워질 때까지 기다린다.

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
  --replicas 4
```

성공 출력은 replica별 처리량, 복구 job 수, 최대 시작·완료 latency와 orphan recovery latency를
JSON으로 남긴다. 매 실행은 UUID가 포함된 별도 Redis keyspace를 사용하고 성공·실패 여부와
관계없이 worker task, connection과 모든 drill key를 정리한다.

## 해석과 운영 경계

- 60초/120초는 제품 기본 SLO와 같은 절대 상한이다. 합성 pipeline은 각 job에 10ms만 사용하므로
  이 결과만으로 실제 GitHub·LLM latency를 예측하지 않는다.
- 4개 in-process `AnalysisWorker`가 각자 독립 Redis connection, processing list와 lease를
  사용한다. container scheduler, CPU·memory limit과 network partition은 포함하지 않는다.
- production 전에는 실제 replica container, production과 같은 resource limit·provider 지연,
  장시간 arrival rate와 PostgreSQL connection pool을 포함한 별도 soak/load test가 필요하다.
- stale worker가 복구 뒤 뒤늦게 재개하는 fencing은 DB attempt token 회귀 테스트가 별도로
  검증한다. 이 drill의 abandoned worker는 재개하지 않는다.
