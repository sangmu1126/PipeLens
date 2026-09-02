# Production PostgreSQL·Grafana 통합 recovery와 rollback 증적

이 문서는 #63의 production-representative PostgreSQL·Grafana 복원 결과를 같은 recovery window로
묶고, 보존 source를 이용한 cutover·rollback까지 검증하는 상위 절차다. 개별 복원 명령과 안전
경계는 [PostgreSQL 복원 drill](postgres-restore-drill.md)과
[Grafana 복원 drill](grafana-restore-drill.md)을 따른다.

`ops/recovery/drill-observation.example.json`은 schema 예제이며 production backup이나 실제 rollback
증적이 아니다.

## 사전 승인

실행 전에 다음 항목을 change record에 고정한다.

- source revision, drill ID, UTC window와 production과 분리된 target
- PostgreSQL·Grafana 각각의 대표 최소 backup byte 크기, backup 방식과 write-freeze
- PostgreSQL/Grafana RTO, 공통 RPO와 rollback RTO
- cutover 승인자, 보존할 source volume/archive와 접근 권한
- PostgreSQL은 target에 첫 post-cutover write, Grafana는 target의 첫 mutable 변경 등 명확한
  point-of-no-return 조건
- point of no return 이후 rollback 시 변경분 export·replay/reconciliation 책임자와 승인 절차

Source volume, backup과 target 이름을 명시적으로 대조한다. 기존 production source에 restore하거나
덮어쓰는 명령은 이 drill에서 사용하지 않는다. 두 개별 verifier의 output, backup, audit와 secret은
승인된 제한 저장소에 보관한다.

## 실행 순서

1. 두 service write를 freeze하고 backup 시각·duration·byte 크기·SHA-256을 기록한다.
2. 각 backup을 source와 분리된 disposable PostgreSQL 18/Grafana 13 target에 복원한다.
3. PostgreSQL은 Alembic head·대표 relation count를, Grafana는 persistent/provisioned dashboard,
   folder, datasource와 access policy를 확인한다.
4. 두 verifier output의 SHA-256을 계산하고 RTO/RPO·integrity 결과를 원본 audit와 대조한다.
5. Source volume/archive를 삭제하지 않은 상태에서 승인된 cutover를 수행하고 client smoke를 확인한다.
6. 명시한 point of no return을 넘기기 전 보존 source로 rollback한다. 실제 운영 정책상 조건을 넘어야
   하는 exercise이면 reconciliation plan을 먼저 review하고 변경분 손실·재생 결과를 제한 audit에
   남긴다.
7. Rollback 뒤 PostgreSQL representative record, Grafana content/datasource/access policy와 client
   smoke를 다시 확인한다.
8. cutover·rollback audit bundle을 redaction하고 SHA-256을 계산한 뒤 전체 artifact에서 secret exact
   match가 0인지 검사한다.

## 통합 관측 검증

예제를 제한 작업 디렉터리로 복사해 실제 관측값으로 바꾼다.

```bash
cp ops/recovery/drill-observation.example.json \
  /secure/work/recovery-drill-observation.json

.venv/bin/python -m ops.recovery.verify_drill_evidence \
  --input /secure/work/recovery-drill-observation.json \
  --output /secure/work/recovery-drill-evidence.json
```

Verifier는 provider, database나 Docker에 접속하지 않고 1 MiB 이하 strict JSON만 읽는다. 자동 판정은
다음을 모두 요구한다.

1. PostgreSQL·Grafana backup이 각각 사전 정의한 representative minimum 이상
2. 두 service의 recovery time이 개별 RTO 이하, observed RPO가 공통 RPO 이하
3. 개별 restore integrity 통과와 rollback 종료까지 source 보존
4. 시간순 승인→cutover→rollback과 문서화된 approver
5. 보존 PostgreSQL/Grafana source를 실제 사용하고 DB integrity, Grafana content/access policy,
   client smoke를 rollback 뒤 모두 재검증
6. rollback duration이 rollback RTO 이하
7. point of no return 미통과 또는 통과 시 reconciliation plan review
8. cutover·rollback artifact review와 secret scan match 0

유효하지만 기준을 어긴 관측은 `passed: false` JSON과 exit 1로 보존한다. unknown field, 역전·미래
timestamp, 잘못된 hash·count와 URL 형태 identifier는 증적 자체 오류로 보고 출력하지 않는다.

## 합성 live regression gate

`ops/recovery/verify-live-restore.sh`는 CI에서 현재 Compose의 digest-pinned PostgreSQL 18과 Grafana
13 image를 사용해 두 개별 restore 실행기의 Docker 경로를 검증한다.

1. 임시 PostgreSQL source에 Alembic head를 적용하고 probe relation을 넣어 custom-format backup을
   만든 뒤 새 volume에 복원한다.
2. 임시 Grafana source에 provisioning content와 별도 persistent folder/dashboard를 만든 뒤 중지된
   volume archive를 새 volume에 복원한다.
3. PostgreSQL major·Alembic head·probe count와 Grafana version·dashboard·folder·datasource·anonymous
   access policy를 실제 API와 database에서 확인한다.
4. 성공과 실패 모두 source·target container, volume, backup과 합성 password를 정리한다.

스크립트는 두 image가 `tag@sha256` 형식인지 Docker 호출 전에 검사하고, 기존 고정 이름 resource를
발견하면 덮어쓰지 않는다. 로컬에서 같은 gate를 실행할 때는 다음과 같이 Compose image를 전달한다.

```bash
POSTGRES_IMAGE="$(docker compose config --format json | python -c '
import json, sys
print(json.load(sys.stdin)["services"]["postgres"]["image"])
')" \
GRAFANA_IMAGE="$(docker compose config --format json | python -c '
import json, sys
print(json.load(sys.stdin)["services"]["grafana"]["image"])
')" \
GRAFANA_VERSION=13.2.0 \
  ops/recovery/verify-live-restore.sh
```

이 gate는 restore 실행기의 real Docker integration 회귀만 증명한다. 작은 합성 backup, 고정된 120초
RTO와 60초 RPO를 사용하며 실제 production 규모, write freeze, 승인, source 보존 cutover·rollback,
point of no return 또는 운영 artifact review를 증명하지 않는다.

## 증적과 보안 경계

- 공개 가능: verifier output, byte·duration, RTO/RPO 결과, UTC timeline, boolean과 artifact SHA-256.
- 제한 보관: PostgreSQL/Grafana verifier 원본, backup metadata, cutover/rollback 명령 audit, reviewer
  승인과 reconciliation 결과.
- 금지: database/admin password, connection URL, record 원문, dashboard 내부 URL·contact, backup
  경로, raw log와 secret-bearing environment.

출력은 cutover approver 원문을 `approver_documented`로 축약한다. 실제 owner, source/target resource
이름과 경로도 schema에 입력하지 않는다. Reviewer는 drill ID, source revision, UTC window와 네
artifact SHA-256이 제한 원본에 일치하는지 확인한다.

## 완료 경계

체크인 예제와 verifier 통과는 production 규모 backup, cutover 또는 rollback 실행이 아니다. 실제
backup size/duration, 개별 restore output, 보존 source rollback과 private audit review가 모두 있어야
#63 완료 후보가 된다. Source를 보존하지 않았거나 point of no return 이후 reconciliation 결과를
확인할 수 없으면 성공 처리하지 않는다.
