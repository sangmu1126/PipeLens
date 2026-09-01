# Alertmanager production 채널 증적 drill

## 목적과 완료 경계

이 절차는 staging 합성 alert로 실제 incident receiver를 검증하고 #64에 필요한 정규화된 JSON
증적을 만드는 방법을 정의한다. `ops/alertmanager/verify_channel_evidence.py`는 외부 서비스를
호출하지 않으며 Alertmanager나 receiver credential을 받지 않는다. 운영자가 Alertmanager,
incident provider와 secret manager의 audit log를 대조해 만든 관측 파일만 검증한다.

저장소에 포함된 example과 단위 테스트 통과는 입력 계약이 동작한다는 근거일 뿐 실제 receiver,
credential, notification, acknowledgement 또는 rotation 증적이 아니다. #64는 승인된 채널에서
이 문서의 모든 exercise를 수행하고 결과를 승인된 위치에 보관하기 전까지 열어 둔다.

## 사전 승인

실행 전에 다음 항목을 조직의 운영 시스템에서 승인한다.

1. receiver 종류와 production owner
2. warning·critical escalation policy와 업무시간 외 담당 경로
3. firing delivery, acknowledgement, resolved delivery와 retry latency 상한
4. staging 합성 alert의 label, 실행 시간과 영향받을 당직자
5. credential rotation과 receiver failure를 만들고 복구할 담당자
6. 원본 log와 redacted evidence의 보관 위치·보존 기간

owner, escalation policy와 실제 receiver endpoint는 이 공개 저장소에 기록하지 않는다. 정규화 입력은
각 값이 문서화됐음을 증명할 non-secret identifier만 사용하고, 출력은 owner와 policy의 실제 값을
제거해 boolean만 남긴다.

## 실행 순서

1. production과 같은 route·inhibition·group interval을 사용하는 staging Alertmanager를 준비한다.
2. routing key, token 또는 webhook URL을 production secret manager에서 read-only file이나 배포 시점
   config로 주입한다. 생성된 config와 secret은 저장소, image, shell history에 남기지 않는다.
3. 서로 같은 group에 들어갈 합성 alert 두 건을 firing하고 receiver notification 한 건과 외부
   incident ID를 확인한다.
4. 같은 firing alert를 반복 전송해 새 외부 incident가 생기지 않는지 확인한다.
5. 같은 `alertname`의 critical·warning을 함께 firing해 warning inhibition을 확인한다.
6. 제한된 matcher와 만료 시간이 있는 silence를 만들고 대상 alert가 전달되지 않는지 확인한 뒤
   silence를 제거한다.
7. 최초 incident를 담당자가 acknowledge하고 alert를 해소해 resolved notification을 확인한다.
8. 이전 credential로 canary를 전달하고 새 credential로 교체한다. 새 credential canary 성공 뒤
   이전 credential을 폐기하고 다시 전달을 확인한다.
9. staging receiver를 제한된 시간 실패시키거나 provider의 승인된 failure fixture를 사용한다.
   Alertmanager가 두 번 이상 시도하고 receiver 복구 뒤 같은 incident를 전달하는지 확인한다.
10. Alertmanager log, provider incident/audit log와 secret manager audit log의 UTC 시각을 대조해
    example 형식의 관측 파일을 만든다.

실제 production paging 정책에 영향이 생기거나 canary가 예상 group 밖으로 전달되면 즉시 새 alert를
중단한다. credential 교체 후 전달이 실패하면 이전 credential이 아직 유효할 때만 rollback하고,
이미 폐기했다면 새 credential을 재발급한다. 폐기한 credential을 다시 활성화하지 않는다. failure
exercise는 정해진 제한을 넘기기 전에 receiver를 복구하고 남은 synthetic incident를 resolve한다.

## 관측 입력 계약

[`channel-observation.example.json`](../ops/alertmanager/fixtures/channel-observation.example.json)을
작업 디렉터리 밖의 승인된 위치로 복사해 실제 값으로 바꾼다. 입력은 최대 1 MiB UTF-8 JSON이며
정의되지 않은 필드가 하나라도 있으면 실패한다. 특히 credential, URL, raw notification payload와
자유 형식 메모를 추가할 수 없다.

- `source_revision`: 검증한 배포 revision의 non-secret identifier
- `environment`: staging 환경 identifier
- `receiver_type`: `incidentio`, `pagerduty`, `slack`, `webhook`, `other` 중 하나
- `owner`, `escalation_policy_ref`: 비공개 운영 문서와 연결되는 non-secret identifier
- `alertmanager_group`, `external_incident_id`: 실제 exercise의 group과 incident identifier
- `probe`: firing 전송·도착·acknowledge와 resolved 전송·도착 UTC 시각
- `grouping`: 같은 group의 source alert 수와 실제 notification 수
- `deduplication`: 반복 firing 횟수와 새로 생긴 외부 incident 수
- `inhibition`, `silence`: 억제 대상 수와 실제 전달 수
- `credential_rotation`: 교체 전후 canary 시각, 교체 시각과 이전 credential 폐기 여부
- `receiver_failure`: 장애 시작, alert 전송, 복구, 최종 전달 시각과 시도 횟수

모든 identifier는 공백·query string 없이 200자 이하로 제한된다. timestamp는 timezone offset이 있는
ISO 8601이어야 하고 각 exercise 안에서 시간 순서가 역전되거나 미래이면 실패한다. grouping은 source
alert 2건 이상과 notification 1건, deduplication은 반복 1회 이상과 신규 incident 0건, inhibition과
silence는 후보 1건 이상과 전달 0건이어야 통과한다. retry는 2회 이상이어야 한다.

## 검증 명령과 결과

조직에서 승인한 상한을 명시해 실행한다. 아래 수치는 예시이며 production SLO를 대신하지 않는다.

```bash
python ops/alertmanager/verify_channel_evidence.py \
  --input /approved/private/channel-observation.json \
  --output /approved/private/channel-evidence.json \
  --max-delivery-seconds 120 \
  --max-acknowledgement-seconds 300 \
  --max-resolve-delivery-seconds 120 \
  --max-retry-seconds 300
```

결과는 schema version, 확인 시각, source revision, environment, receiver 종류, group, 외부 incident ID,
정규화된 timeline, 여섯 latency, exercise count, 개별 판정과 입력 SHA-256을 포함한다. owner와 policy의
실제 identifier, endpoint, token, routing key, notification payload는 포함하지 않는다.

계약이 올바르지만 acceptance가 실패하면 결과 JSON을 기록하고 exit code 1을 반환한다. 따라서 실패
증적도 버리지 않고 원본 audit log와 함께 원인을 기록한다. schema 오류나 미래 시각은 신뢰할 수 있는
측정이 아니므로 결과를 만들지 않는다. `--output`으로 입력 파일 자체를 덮어쓸 수 없다.

`passed: true`만으로 #64를 닫지 않는다. owner와 escalation 승인 문서, secret manager 주입·rotation
audit, Alertmanager/provider 원본 log, 실제 외부 incident URL을 비공개 증적 위치에서 함께 검토한 뒤
public issue에는 secret과 내부 URL이 없는 결과만 첨부한다.
