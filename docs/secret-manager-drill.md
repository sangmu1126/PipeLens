# Production secret manager와 credential rotation 증적 drill

## 목적과 완료 경계

이 절차는 승인된 production secret manager, workload identity, file 주입과 credential rotation을
staging에서 검증하고 #65의 redacted JSON 증적을 만드는 방법을 정의한다.
`ops/secrets/verify_rotation_evidence.py`는 secret manager나 외부 provider에 접속하지 않고 실제
secret 값, resource URL, access key 또는 manifest를 받지 않는다. 운영자가 manager audit,
deployment, canary와 incident 기록을 대조해 만든 정규화 관측만 판정한다.

체크인된 example과 단위 테스트는 schema와 redaction 계약만 검증한다. 실제 manager 선택,
workload identity 연결, production credential 주입·폐기와 incident response가 완료됐다는 뜻이
아니므로 외부 증적을 검토하기 전까지 #65는 열린 상태다.

## 실행 전 승인

다음 항목을 조직의 비공개 운영 시스템에서 먼저 승인한다.

1. secret manager와 workload identity 방식, owner와 교체 담당자
2. workload별 읽을 secret의 정확한 목록과 read 외 모든 권한 거부
3. credential version, 생성 시각, 다음 rotation deadline과 적용 workload inventory
4. Fernet rollback 관찰 기간과 기존 session 검증 방법
5. 외부 credential canary, 이전 version 폐기와 허용할 unplanned outage 상한
6. unavailable/revoked secret exercise의 detection·recovery 상한과 incident 담당자
7. 원본 audit log와 redacted evidence의 보관 위치·보존 기간

장기 cloud access key를 workload에 배포하지 않는다. workload identity에는 inventory에 있는
secret version의 read만 허용하고 list, write와 delete를 허용하지 않는다. 교체 담당자의 관리 권한은
runtime identity와 분리한다.

## Inventory와 주입 검증

최소 inventory는 다음 9개 credential을 포함한다.

- webhook secret
- GitHub App private key
- GitHub OAuth client secret
- session secret
- token encryption primary와 fallback
- PostgreSQL URL
- Redis URL
- Alertmanager receiver secret

OpenAI provider를 실제로 사용하면 `openai_api_key`도 추가한다. 각 항목에는 실제 값이나 manager
resource ID 대신 name, workload, owner identifier, version identifier, 생성·다음 교체 시각과 file
주입·read-only 여부만 기록한다. API·worker·migration·Alertmanager가 사용하지 않는 secret을 읽을 수
없어야 한다.

배포 뒤 다음을 확인한다.

1. secret이 process argument나 direct 환경값이 아니라 대응 `*_FILE` 또는 동등한 read-only
   regular file로 주입된다.
2. image layer와 repository state에 값이나 manager resource가 없다.
3. rendered manifest, deployment event와 application log에 secret 평문이 없다.
4. version이 누락되거나 file이 unavailable이면 production startup 또는 해당 경로가 fail-closed하고
   SQLite·memory queue·개발 credential로 fallback하지 않는다.

Alertmanager처럼 application `*_FILE` 설정 밖에 있는 secret도 환경별 config 생성 단계에서
read-only file을 사용하며 repository 기본 config를 수정하지 않는다.

## Rotation과 장애 exercise

Fernet rotation은 [기존 key runbook](secrets-and-rotation.md)의 순서를 그대로 따른다.

1. 새 version을 만들고 기존 primary를 유지한다.
2. 기존 primary + 새 fallback을 모든 instance에 배포해 dual read를 검증한다.
3. 새 primary + 기존 fallback으로 배포하고 기존 session의 lazy rewrap을 검증한다.
4. session TTL과 rollback 관찰 기간 뒤 이전 deployment 종료를 확인하고 old fallback을 제거한다.
5. 새 login, 기존 session, installation sync와 분석 목록 canary를 실행한다.

외부 credential 하나 이상은 추가→배포→pre-revoke canary→이전 version 폐기→post-revoke canary
순서로 교체한다. dual credential이 없으면 승인된 maintenance window와 rollback credential을 먼저
준비한다. 예기치 않은 outage는 조직이 승인한 상한 이하여야 한다.

별도의 controlled staging exercise에서 inventory credential 하나를 unavailable 또는 revoked 상태로
만든다. detection, incident 선언, replacement 배포와 recovery 시각을 기록하고 fail-closed 및 secret
비노출을 확인한다. 실제 노출 사고에서는 drill을 계속하지 않고 모든 session·credential 폐기와
침해 대응 절차를 우선한다.

## 입력 계약과 검증

[`rotation-observation.example.json`](../ops/secrets/rotation-observation.example.json)을 승인된 비공개
작업 위치로 복사해 실제 audit 결과로 바꾼다. 입력은 최대 1 MiB UTF-8 JSON이며 unknown field,
중복 credential, resource URL, timezone 없는 시각, 역전·미래 시각을 거부한다. 모든 drill event는
`started_at`과 `completed_at` 사이여야 한다.

`manager_type`은 실제 운영자가 선택한 `aws-secrets-manager`, `azure-key-vault`,
`gcp-secret-manager`, `kubernetes-external-secrets`, `vault`, `other` 중 하나를 기록한다. example의
`other`는 특정 vendor 선택을 의미하지 않는다.

승인된 상한을 명시해 실행한다. 아래 값은 형식 예시이며 production SLO를 대신하지 않는다.

```bash
python ops/secrets/verify_rotation_evidence.py \
  --input /approved/private/rotation-observation.json \
  --output /approved/private/rotation-evidence.json \
  --max-detection-seconds 60 \
  --max-recovery-seconds 300 \
  --max-unplanned-outage-seconds 0
```

결과는 inventory name·workload·시각, version fingerprint, workload identity 권한 boolean, Fernet와
외부 credential timeline, unavailable-secret incident ID·detection·recovery, artifact scan과 개별
판정을 포함한다. identity, owner와 원본 version identifier는 제거되며 실제 secret, resource ID,
endpoint, manifest와 log 내용은 입력 계약에 없다. 입력 파일 전체의 SHA-256으로 비공개 원본과
redacted 결과를 연결한다.

계약은 맞지만 acceptance가 실패하면 결과 JSON을 남기고 exit code 1을 반환한다. schema가 잘못된
입력은 신뢰할 수 있는 측정이 아니므로 결과를 만들지 않으며 입력 자체를 output으로 덮어쓸 수 없다.
`passed: true`도 private IAM policy, manager/deployment audit, 실제 canary와 폐기 기록을 검토하기
전에는 #65 완료 증적이 아니다.
