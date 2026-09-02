# PostgreSQL 복원 증적 drill

`ops/postgres/verify_restore.py`는 승인된 PostgreSQL custom-format backup을 고정된 PostgreSQL 18
image와 새 Docker volume에 복원하고, 복구 목표와 무결성 결과를 redacted JSON으로 기록한다.
production database나 Compose volume을 직접 변경하지 않으며 [production 복원 이슈
#63](https://github.com/sangmu1126/PipeLens/issues/63)의 실제 실행을 위한 도구다.

## 사전 결정과 기록

실행 전에 운영 책임자가 다음을 승인된 변경·사고 기록에 남긴다.

- production representative 기준: database byte 크기, 분석·사용자·installation·feedback의 최소
  레코드 수와 보존 기간
- RTO와 RPO 목표, backup schedule로부터 계산한 실제 observed RPO
- API와 worker 쓰기를 중단할 시점, backup 시작·완료 시각과 source release revision
- 암호화 backup 위치, 접근 권한, 보존 기간과 검증 담당자
- 복원 target, cutover 승인자, rollback source volume과 point of no return

backup duration은 쓰기 중단 뒤 `pg_dump --format custom`이 성공할 때까지 monotonic clock으로
측정한다. `--write-freeze-at`과 `--backup-created-at`은 UTC offset이 포함된 ISO 8601 값이어야
한다. `--observed-rpo-seconds`는 장애 또는 drill 기준 시각과 마지막 durable recovery point 사이의
차이다. 실행기는 운영자가 제공한 시간 값을 다시 만들어낼 수 없으므로 원본 backup log와 함께
보관해야 한다.

## 안전 경계

- `postgres:TAG@sha256:DIGEST` 형식의 고정 image만 허용한다.
- backup과 password file은 container에 read-only로 mount한다. JSON에는 두 경로와 password를
  기록하지 않는다.
- `pipelens-postgres-restore-<run-id>` container 또는 대응 volume이 이미 있으면 덮어쓰지 않고
  중단한다.
- 새 target에는 `/var/lib/postgresql` 전용 volume을 사용하며 source·Compose volume을 mount하지
  않는다.
- 성공·실패 뒤 target container와 volume을 제거한다. 조사 때문에 `--preserve-target`을 지정한
  성공 실행만 target을 남긴다.
- 최소 한 개의 `--expect-min-count`가 필요하다. relation 이름은 단순 schema/table identifier만
  허용하므로 임의 SQL을 실행할 수 없다.

비밀번호 파일은 운영 secret manager가 제공하는 임시 read-only mount를 사용하고 repository나
evidence 위치에 복사하지 않는다. globals dump는 role·credential을 포함할 수 있어 이 실행기가
적용하지 않는다. target role은 빈 PostgreSQL 18 container 초기화 때 password file로 생성된다.

## 실행

먼저 현재 Compose PostgreSQL image의 tag와 digest를 확인한다.

```bash
docker compose config --format json | python -c '
import json
import sys
print(json.load(sys.stdin)["services"]["postgres"]["image"])
'
```

승인된 운영 host에서 virtual environment와 Docker 접근을 준비한 뒤 실행한다.

```bash
.venv/bin/python ops/postgres/verify_restore.py \
  --image 'postgres:18-alpine@sha256:<64-hex-digest>' \
  --backup /approved/backup/pipelens.dump \
  --password-file /run/secrets/postgres-restore-password \
  --source-revision release-2026-09-01 \
  --write-freeze-at 2026-09-01T14:00:00Z \
  --backup-created-at 2026-09-01T14:02:30Z \
  --backup-duration-seconds 150 \
  --rto-seconds 900 \
  --rpo-seconds 300 \
  --observed-rpo-seconds 240 \
  --expect-min-count analyses=100000 \
  --expect-min-count github_users=1000 \
  --expect-min-count user_installations=1000 \
  --run-id prod-20260901 \
  --output /approved/evidence/postgres-restore-20260901.json
```

실행기는 image pull과 빈 PostgreSQL 초기화를 포함한 전체 recovery duration, `pg_restore` 단독
duration, backup·database bytes, backup SHA-256, PostgreSQL major, Alembic heads, 대표 레코드 수와
RTO/RPO 달성 여부를 기록한다. output은 production secret이 없는지 검토한 뒤 승인된 운영 증적
위치에 보관한다. repository에는 실제 record, database URL, password, dump를 커밋하지 않는다.

## 결과 판정과 추가 확인

JSON 성공만으로 service 복구가 끝난 것은 아니다. 다음을 같은 실행 기록에 추가한다.

1. API `/readyz`의 database·queue 상태와 worker heartbeat를 확인한다.
2. 가장 최근 분석, 사용자, installation과 feedback 표본을 source manifest와 대조한다.
3. 새 합성 webhook 한 건이 저장·처리되고 허용된 사용자만 dashboard에서 조회하는지 확인한다.
4. backup checksum과 object storage의 retention·encryption·restore audit를 대조한다.
5. Grafana persistent storage는 별도 Grafana 복원 drill로 검증한다.

## Rollback과 point of no return

두 service를 실제 cutover·rollback하는 상위 실행은
[Production 통합 recovery drill](production-recovery-drill.md)에 따라 같은 drill ID로 기록한다.

이 실행기는 격리 target을 production에 연결하지 않으므로 자체 point of no return은 없다. 실제
cutover에서는 restored PostgreSQL 18에 API나 worker가 첫 쓰기를 수행하는 순간 source volume만으로
무손실 rollback할 수 없게 된다. 그 전에 target을 폐기하면 source stack을 그대로 다시 열 수 있다.
첫 쓰기 뒤에는 target을 다시 freeze하고 증분 데이터를 추출·조정하거나 검증된 새 PostgreSQL 18
backup으로 복구해야 한다. source volume과 외부 backup은 rollback 승인과 대표 데이터 대조가
끝나기 전까지 삭제하지 않는다.

## 현재 검증 범위

2026-09-01 Docker Desktop 29.6.2 arm64에서 합성 17,585-byte backup과 고정 PostgreSQL 18.6
image를 사용했다. `pg_restore` 0.099초, image pull·초기화·검증을 포함한 recovery 4.928초,
database 8,255,167 bytes, Alembic `20260829_0009`, 대표 analysis 1건과 target 자동 cleanup을
확인했다. 이 수치는 실행기 통합 검증일 뿐 production 규모 RTO/RPO 증적이 아니다.
