# 2026-09-08 PostgreSQL·Grafana scale recovery drill

이 묶음은 issue #63의 격리 스테이징 실행에서 나온 공개 가능한 증적이다. 실제 사용자가 아직 없는
launch 단계이므로 대표 기준은 예상 하루 처리량으로 고정했다. PostgreSQL은 분석 100,000건,
feedback 10,000건, 사용자·installation 각 1,000건과 비압축 난수성 진단 payload를 사용했고,
custom-format backup 최소 256 MiB를 요구했다. Grafana는 provisioned dashboard·datasource와 SQLite에만
있는 folder/dashboard를 함께 만들고 128 MiB의 비압축 난수성 persistent payload를 추가해 archive
최소 128 MiB를 요구했다.

## 결과

| 항목 | PostgreSQL 18 | Grafana 13 |
| --- | ---: | ---: |
| backup bytes | 470,664,637 | 155,808,250 |
| backup duration | 5.766초 | 5.511초 |
| restore duration | 7.610초 | 2.699초 |
| 전체 recovery | 12.886초 / RTO 900초 | 6.627초 / RTO 300초 |
| observed RPO | 0초 / 목표 300초 | 0초 / 목표 300초 |

PostgreSQL 18의 Alembic head `20260829_0009`와 모든 대표 count가 일치했다. Grafana 13.2.1은
provisioned `pipelens-operations`, persistent `scale-dashboard`·`scale-folder`, Prometheus datasource,
anonymous disabled와 비인증 admin API 차단을 통과했다. 복원 target에서 read-only client smoke를
수행하고 첫 post-cutover write 전 되돌렸으며, 보존 source를 재기동해 database count, Grafana
content와 access policy를 다시 확인했다. rollback은 5.933초 / RTO 300초였다.

## 실행 중 발견과 교정

1. 최초 실행은 `docker exec`에 stdin 유지 옵션이 없어 적재 SQL이 전달되지 않았다. 복원기가
   `analyses: 0 < 100000`을 감지해 실패했고 대상과 source를 자동 정리했다. `docker exec -i`로
   교정했다.
2. 다음 실행은 두 격리 복원을 통과했으나 source Grafana 재시작 뒤 Docker의 동적 port가 바뀌어
   rollback client가 이전 port를 조회했다. 재시작 직후 `docker port`를 다시 읽도록 교정했다.
3. 최종 실행은 여섯 통합 check 모두 `true`였다. 실패 실행은 성공 증적에 합치지 않았고, 기존
   Compose stack이나 그 volume은 어느 실행에서도 mount·중지·변경하지 않았다.

## 파일

- `postgres.json`, `grafana.json`: 개별 restore verifier의 redacted 원문
- `observation.json`: 통합 verifier 입력
- `evidence.json`: strict 통합 판정(`passed: true`)
- `cutover-audit.txt`, `rollback-audit.txt`: synthetic environment의 비민감 audit 원문. SHA-256은
  observation/evidence와 일치한다.

실제 credential, backup, database record와 volume 경로는 저장하지 않았다. 이 모델은 현재 launch
capacity의 storage·RTO 경계를 증명하지만 실제 사용자 payload 분포를 증명하지 않는다. 실제 운영
30일 또는 예상 peak가 이 기준을 넘으면 대표 최소값과 RTO를 다시 산정해 drill을 반복한다.
