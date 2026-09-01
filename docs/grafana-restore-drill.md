# Grafana 복원 증적 drill

`ops/grafana/verify_restore.py`는 중지된 Grafana data volume의 tar backup을 새 Docker volume에
복원하고, 고정 Grafana 13 image의 storage migration과 dashboard·folder·datasource·접근 정책을
검증해 redacted JSON으로 기록한다. production volume을 직접 변경하지 않으며
[production 복원 이슈 #63](https://github.com/sangmu1126/PipeLens/issues/63)의 실제 실행 도구다.

## 사전 결정과 대표 기준

운영 책임자는 실행 전에 다음을 승인된 변경 기록에 남긴다.

- volume byte 크기, `grafana.db` 크기, dashboard·folder·datasource 수와 필수 UID
- file provisioning 항목과 SQLite에만 존재하는 비-provisioned dashboard의 대표 UID
- RTO·RPO, backup schedule에서 계산한 observed RPO와 source release revision
- Grafana 쓰기 중단, backup 시작·완료 시각, 암호화 위치·보존 기간·검증 담당자
- production access policy, cutover 승인자, source volume과 rollback backup

Backup DB가 실제로 보존됐음을 확인하려면 drill 전에 production과 같은 접근 통제를 거쳐 전용
folder와 작은 비-provisioned dashboard를 생성하고 UID를 기록한다. 실행기는 예상 dashboard 중
최소 하나가 `provisioned: false`여야 성공한다. repository dashboard만 다시 provision해서 backup
복원이 성공한 것처럼 보이는 false positive를 허용하지 않는다.

## Backup과 안전 경계

Grafana를 중지한 뒤 정확한 Compose volume을 read-only로 mount해 archive를 만든다.

```bash
docker compose stop grafana
grafana_volume=<승인된-volume-name>
docker run --rm --user 0 --entrypoint tar \
  --mount "type=volume,source=$grafana_volume,target=/source,readonly" \
  --mount "type=bind,source=/approved/backup,target=/backup" \
  'grafana/grafana:13.2.0@sha256:<64-hex-digest>' \
  -czf /backup/grafana-data.tgz -C /source .
```

실행기는 다음 경계를 강제한다.

- `grafana/grafana:TAG@sha256:DIGEST` 형식의 고정 image만 허용한다.
- archive의 absolute·상위 경로, symlink·hardlink·device·FIFO를 거부하고 root의 non-empty
  `grafana.db`를 요구한다. plugin symlink가 필요한 배포는 plugin을 별도 공급망에서 재설치한다.
- source나 Compose volume을 mount하지 않고 `pipelens-grafana-restore-<run-id>` 새 volume만 쓴다.
  같은 container·volume 이름이 존재하면 덮어쓰지 않는다.
- file provisioning은 명시된 두 directory만 read-only로 target에 mount한다. 실제 경로는 JSON에
  기록하지 않는다.
- 복원된 DB의 기존 server admin credential을 secret file에서 읽어 API 검증에만 사용한다. 새
  `GF_SECURITY_ADMIN_PASSWORD`는 기존 SQLite admin password를 바꾸지 않으므로 사용하지 않는다.
- 성공·실패 뒤 disposable target을 제거한다. 조사 목적의 성공 실행에서 명시적으로
  `--preserve-target`을 지정한 경우만 보존한다.

Admin password file과 archive는 repository에 두지 않고 운영 secret manager와 승인된 backup
storage에서 제공한다. JSON에는 password, backup·provisioning 경로, dashboard title, datasource
URL의 실제 값을 저장하지 않고 UID와 match boolean만 기록한다.

## 실행

Production에서는 일반적으로 anonymous access를 끈다. 아래 예시는 current repository
provisioning과 별도 persistent probe를 함께 확인한다.

```bash
.venv/bin/python ops/grafana/verify_restore.py \
  --image 'grafana/grafana:13.2.0@sha256:<64-hex-digest>' \
  --expected-version 13.2.0 \
  --backup /approved/backup/grafana-data.tgz \
  --admin-user '<server-admin-user>' \
  --admin-password-file /run/secrets/grafana-admin-password \
  --provisioning-dir ops/grafana/provisioning \
  --dashboards-dir ops/grafana/dashboards \
  --source-revision release-2026-09-02 \
  --write-freeze-at 2026-09-02T01:00:00Z \
  --backup-created-at 2026-09-02T01:01:00Z \
  --backup-duration-seconds 60 \
  --rto-seconds 300 \
  --rpo-seconds 300 \
  --observed-rpo-seconds 240 \
  --expect-dashboard 'pipelens-operations=PipeLens Operations' \
  --expect-dashboard 'restore-probe=Restore Probe' \
  --expect-folder 'restore-probe-folder=Restore Probe' \
  --expect-datasource 'prometheus=prometheus,http://prometheus:9090' \
  --anonymous-role disabled \
  --run-id prod-20260902 \
  --output /approved/evidence/grafana-restore-20260902.json
```

`--anonymous-role`은 `disabled`, `Viewer`, `Editor` 중 하나다. Disabled에서는 anonymous dashboard와
admin API를 모두 거부해야 한다. Viewer·Editor에서는 dashboard 조회만 허용하고 admin settings는
항상 401·403이어야 한다. 복원된 server admin만 health와 content를 검증한다.

결과에는 archive 압축·비압축 byte, member 수, source·migrated `grafana.db` 크기, SHA-256,
backup·archive restore·전체 recovery duration, Grafana version, RTO/RPO 판정과 항목별 match가
포함된다. 운영자가 제공한 시간과 observed RPO는 원본 backup log와 대조해 승인된 evidence
location에 함께 보관한다.

## 추가 확인과 rollback

JSON 성공 뒤에도 실제 browser rendering, panel query, alert·annotation, SSO와 network policy를
확인한다. datasource URL은 일치 여부만으로 부족하므로 target Prometheus 연결과 대표 query도
별도 검증한다.

이 도구는 격리 target을 production에 연결하지 않아 자체 point of no return이 없다. 실제 Grafana
13 cutover 뒤 migration 또는 첫 dashboard·annotation 쓰기가 발생하면 이전 Grafana image만 같은
volume에 연결하지 않는다. target을 중지·보존하고 검증된 pre-cutover archive를 새 rollback volume에
복원해 이전 revision을 기동한다. 13 이후 변경분을 export·병합할 계획이 없다면 해당 변경은 rollback
때 손실된다. rollback 검증 전에는 source volume, target volume과 backup을 삭제하지 않는다.

## 현재 검증 범위

2026-09-02 Docker Desktop 29.6.2 arm64에서 합성 43,036,207-byte archive와 고정 Grafana 13.2.0
image를 사용했다. archive restore 1.461초, 전체 recovery 5.443초, `grafana.db` 1,642,496 bytes,
provisioned `pipelens-operations`, 비-provisioned probe dashboard·folder, Prometheus datasource,
anonymous Viewer dashboard 허용과 admin API 차단, target cleanup을 확인했다. 이는 실행기 통합
검증이며 production volume RTO/RPO나 실제 access policy 증적이 아니다.
