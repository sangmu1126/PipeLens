# Grafana 13 업그레이드

이 문서는 PipeLens Compose의 Grafana를 12.1에서 13.2로 전환할 때 `grafana-data`를
백업·검증하고 필요하면 복원하는 절차다. PipeLens dashboard와 datasource 정의는 저장소의
file provisioning이 원본이지만 Grafana SQLite에는 사용자 설정, annotation과 dashboard
storage migration 상태가 남는다.

## 호환성과 안전 경계

- Grafana 13은 기존 folder와 dashboard를 legacy SQL table에서 unified storage로 자동
  마이그레이션한다.
- 13으로 migration한 같은 database에 Grafana 12 이미지만 다시 기동하면 12는 stale legacy
  table을 읽는다. rollback은 업그레이드 전에 만든 database 또는 전체 volume backup을
  복원해야 한다.
- Grafana 13.0.0의 Git Sync migration 결함은 13.0.1에서 수정됐다. PipeLens는 Git Sync
  feature flag를 사용하지 않고 13.2.0으로 직접 전환하지만, backup 없이 major 전환하지 않는다.
- PipeLens는 외부 plugin, Image Renderer와 숫자 ID 기반 datasource API를 사용하지 않는다.
  Prometheus datasource는 고정 UID `prometheus`로 provision한다.
- Compose의 익명 Viewer는 로컬 관측 편의를 위한 설정이다. 외부에 공개하는 production
  Grafana에는 인증과 접근 통제를 별도로 구성한다.

## 업그레이드 전 backup

Grafana를 멈춘 상태에서 전체 data volume을 보관한다. 아래 조회가 여러 volume을 출력하면
자동 선택하지 말고 현재 Compose project의 정확한 volume을 확인한다.

```bash
docker compose stop grafana
docker volume ls --filter label=com.docker.compose.volume=grafana-data \
  --format '{{.Name}}'
```

확인한 volume 이름을 사용해 backup을 만든다. backup 디렉터리는 운영 환경의 암호화·접근
통제 대상이어야 한다.

```bash
grafana_volume=<확인한-volume-이름>
mkdir -p backups
docker run --rm --user 0 --entrypoint tar \
  --mount "type=volume,source=$grafana_volume,target=/source,readonly" \
  --mount "type=bind,source=$PWD/backups,target=/backup" \
  grafana/grafana:12.1.0@sha256:6ac590e7cabc2fbe8d7b8fc1ce9c9f0582177b334e0df9c927ebd9670469440f \
  -czf /backup/grafana-data-v12.1.0.tgz -C /source .
shasum -a 256 backups/grafana-data-v12.1.0.tgz
```

checksum, 크기, 생성 시각, 원본 revision과 실제 복원 위치를 배포 기록에 남긴다. backup을
만든 뒤에도 원본 volume은 검증이 끝날 때까지 삭제하지 않는다.

## 13 전환과 확인

Grafana 13 revision에서 Grafana를 다시 만들고 migration log와 API를 확인한다.

```bash
docker compose pull grafana
docker compose up -d --force-recreate grafana
docker compose logs grafana
curl --fail http://localhost:3001/api/health
curl --fail http://localhost:3001/api/dashboards/uid/pipelens-operations
curl --fail http://localhost:3001/api/datasources/uid/prometheus
```

health 응답의 version이 13.2.0이고 database가 `ok`인지, dashboard title과 8개 panel,
Prometheus datasource UID·URL이 유지되는지 확인한다. 익명 브라우저에서 dashboard가 로그인
redirect 없이 열리는지와 실제 panel query도 확인한다. migration 오류가 있으면 서비스를
열지 않고 backup에서 복구한다.

## Rollback

Grafana 13 기동 뒤에는 이전 이미지만 지정하는 downgrade를 하지 않는다. Grafana를 멈추고
현재 13 volume을 별도로 보존한 다음, 검증한 12.1 backup을 정확한 rollback volume에 복원해
이전 Compose revision으로 기동한다. 복원 대상을 잘못 선택하면 데이터를 덮어쓰므로 volume
이름과 backup checksum을 다시 확인한 뒤 운영 승인 절차에 따라 수행한다.

13에서 새로 만든 dashboard, annotation과 설정은 12.1 backup에 존재하지 않는다. rollback
전에 필요한 변경을 export하고 복원 뒤 합치는 방법을 결정해야 한다. 12 복구를 확인하기
전에는 13 volume과 backup을 삭제하지 않는다.

## 자동 검증 범위

`ops/grafana/verify-major-upgrade.sh`는 임시 volume에서 다음 경로를 검증한다.

1. 고정 Grafana 12.1 image와 현재 provisioning을 기동한다.
2. 기존 PipeLens dashboard를 조회하고 비관리 probe dashboard를 database에 생성한다.
3. 같은 volume을 고정 Grafana 13.2 image로 기동해 storage migration을 수행한다.
4. probe dashboard 보존, file-provisioned dashboard 8개 panel, Prometheus datasource UID와
   익명 Viewer API 접근을 확인한다.

이는 현재 schema와 작은 SQLite volume의 migration 호환성을 검증한다. production volume의
backup 내구성, 복원 시간, 실제 browser rendering과 13 이후 변경분 병합은 별도 운영 drill이
필요하다.

## 근거

- [Grafana 13.0 upgrade guide](https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v13.0/)
- [Grafana 13.2 upgrade guide](https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v13.2/)
- [Grafana upgrade strategy](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/)
- [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Grafana anonymous authentication](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/anonymous-auth/)
