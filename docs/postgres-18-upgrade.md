# PostgreSQL 18 업그레이드

이 문서는 PipeLens의 Compose PostgreSQL을 17에서 18로 전환할 때 데이터 볼륨을 안전하게
이관하는 절차다. 현재 고정 이미지는 PostgreSQL 18.6이며 PostgreSQL 18부터 공식 image의
기본 `PGDATA`와 권장 volume target이 `/var/lib/postgresql/18/docker`와
`/var/lib/postgresql`로 바뀌었다.

## 안전 경계

- PostgreSQL major의 데이터 디렉터리는 직접 호환되지 않는다. 17 데이터 디렉터리로 18을
  기동하지 않는다.
- 기존 Compose volume `postgres-data`는 삭제하지 않는다. 18은 별도 `postgres18-data`를
  사용하므로 전환 뒤에도 17 rollback 원본이 남는다.
- `docker compose down -v`는 두 volume을 삭제할 수 있으므로 이 절차에서 사용하지 않는다.
- 전환 중 API와 worker의 쓰기를 중지한다. dump 뒤 18에 기록된 데이터는 17 volume으로
  자동 역복제되지 않는다.
- production에서는 이 절차 전에 별도 저장소의 암호화 backup, 복원 시간과 보존 정책을
  확인한다. 저장소 CI의 합성 데이터 drill은 production backup 증적을 대신하지 않는다.

## 사전 확인과 백업

아래 명령은 PostgreSQL 17을 사용하는 배포 revision에서 실행한다. backup 경로와 파일명은
운영 환경의 암호화·접근 통제 정책에 맞춰 정한다.

```bash
docker compose exec -T postgres \
  psql --username pipelens --dbname pipelens --command 'SHOW server_version;'
docker compose stop api worker
docker compose exec -T postgres \
  pg_dump --username pipelens --dbname pipelens --format custom \
  > pipelens-postgres17.dump
docker compose exec -T postgres \
  pg_dumpall --username pipelens --globals-only \
  > pipelens-postgres17-globals.sql
pg_restore --list pipelens-postgres17.dump >/dev/null
```

backup의 크기, checksum, 생성 시각과 원본 revision을 배포 기록에 남긴다. `pg_dumpall`의
전역 객체 파일에는 role 정보가 포함될 수 있으므로 database dump보다 엄격하게 보호한다.
PipeLens Compose의 `pipelens` role은 18 image 초기화 과정에서 다시 생성되므로 아래 기본
복원에서는 globals 파일을 적용하지 않는다.

## 18로 복원

1. 17 stack을 내리되 volume은 보존한다.
2. PostgreSQL 18 전환 revision으로 이동한다.
3. 새 18 volume에는 PostgreSQL만 먼저 기동하고 backup을 복원한다.
4. Alembic 상태를 확인한 뒤 나머지 서비스를 기동한다.

```bash
docker compose down
docker compose up -d postgres
docker compose exec -T postgres \
  psql --username pipelens --dbname pipelens --command 'SHOW server_version;'
docker compose exec -T postgres \
  pg_restore --username pipelens --dbname pipelens --no-owner --exit-on-error \
  < pipelens-postgres17.dump
docker compose run --rm migrate alembic check
docker compose up -d --build
docker compose ps
```

복원 뒤에는 분석·사용자·installation·feedback의 대표 개수와 최근 레코드를 원본 기록과
대조하고 API `/readyz`, worker heartbeat와 새 분석 1건을 확인한다. 검증이 끝날 때까지 17
volume과 외부 backup을 유지한다.

## Rollback

18 cutover 뒤 치명적 문제가 발견되면 API와 worker를 먼저 중지하고 stack을 내린다. 이전에
검증한 PostgreSQL 17 revision의 Compose 설정으로 돌아가면 보존된 `postgres-data` volume을
다시 사용한다.

```bash
docker compose stop api worker
docker compose down
# 이전에 검증한 revision으로 전환한 뒤
docker compose up -d --build
```

dump 이후 18에서 발생한 쓰기는 17에 존재하지 않는다. 쓰기가 발생한 뒤 rollback할 때는
서비스를 다시 열기 전에 18의 증분 데이터를 별도로 추출·조정하거나 18 backup을 새 18
cluster에 복원하는 복구 계획을 선택한다. rollback 완료를 확인하기 전에는 어느 volume도
삭제하지 않는다.

## 자동 검증 범위

`ops/postgres/verify-major-upgrade.sh`는 CI에서 다음 경로를 매 PR과 `main` push마다 검증한다.

1. 고정된 PostgreSQL 17 image와 Compose의 현재 18 image를 별도 volume으로 기동한다.
2. 17에서 모든 Alembic migration을 적용하고 표본 데이터를 기록한다.
3. 18의 `pg_dump`/`pg_restore`로 database를 옮긴다.
4. 표본 데이터와 `alembic check`를 18에서 확인한다.

이 검증은 image 호환성, mount 경계와 현재 schema의 논리 backup/restore 가능성을 다룬다.
실제 데이터 크기의 복원 시간, 외부 backup 내구성, role·extension 차이와 cutover 중 쓰기
차단은 production restore drill에서 별도로 검증해야 한다.

2026-08-31 Docker Desktop 29.6.2 arm64에서도 같은 17·18 digest, migration 9개, 표본
dump/restore와 `alembic check`를 통과했다. 상세 결과는
[Docker Desktop 로컬 통합 검증](local-docker-validation.md)에 기록했다.

## 근거

- [PostgreSQL 18 release notes](https://www.postgresql.org/docs/18/release-18.html)
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/)
- [PostgreSQL `pg_upgrade`](https://www.postgresql.org/docs/current/pgupgrade.html)
- [Docker Official Image: postgres](https://hub.docker.com/_/postgres)
