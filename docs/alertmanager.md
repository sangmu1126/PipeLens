# Alertmanager routing과 운영 채널 연결

## 현재 구성

Compose는 Alertmanager 0.33.1 multi-platform manifest를 digest로 고정해 실행한다.

```text
prom/alertmanager:v0.33.1@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d
```

조회한 manifest는 linux/amd64, linux/arm64, linux/arm/v7, linux/ppc64le와 linux/s390x를
포함한다. 신규 설치이므로 Alertmanager는 `utf8-strict-mode`로 시작한다. Compose Dependabot은
0.33.x patch와 digest만 자동 제안하고, 0.x minor 전환은 release note와 config 호환성을 수동
검토한다.

Prometheus는 `alertmanager:9093`으로 다섯 alert rule을 전달한다. 기본 route는 `alertname`과
`severity`로 group화하며 최초 30초, 같은 group은 5분 간격, 반복 알림은 4시간 간격으로 둔다.
같은 `alertname`에서 critical이 firing이면 warning을 inhibit한다.

기본 `local-observer` receiver에는 외부 notification integration이 없다. 개발 Compose를
실행했을 뿐인데 실제 당직 채널로 호출되는 일을 막기 위한 경계다. Alertmanager UI·API에서
alert, group과 silence를 확인할 수 있지만 운영 호출을 완료한 것으로 간주하지 않는다.

## 자동 통합 검증

`ops/alertmanager/verify-routing.sh`는 별도 Docker network에서 다음 전체 경로를 확인한다.

1. `amtool`로 기본·CI Alertmanager config를 검증한다.
2. `promtool`로 합성 Prometheus config와 rule을 검증한다.
3. Alertmanager를 UTF-8 strict mode로 기동한다.
4. Prometheus의 `vector(1)` rule로 `PipeLensAlertRoutingProbe` critical alert를 firing한다.
5. Prometheus가 Alertmanager에 alert를 전달하고 Alertmanager가 group화한 webhook JSON을 로컬
   일회성 receiver에 POST한다.
6. webhook의 version, receiver, firing status, alert name, severity, environment와 summary를
   검증한다.
7. Prometheus API의 firing 상태와 Alertmanager API의 active 상태를 각각 확인한다.

receiver는 최대 1 MiB JSON 하나만 받고 30초 뒤 종료한다. 모든 container, network와 임시
payload는 성공·실패와 관계없이 정리한다. webhook URL과 테스트 alert는 CI fixture에만 있으며
기본 Compose config에는 포함되지 않는다.

PR #45의 첫 CI run `33325807628`은 합성 Prometheus config가 실제 mount 경로와 다른 rule
glob을 참조해 rule 0개로 기동했고 webhook 대기 시간이 초과됐다. fixture가 mount한
`/etc/prometheus/probe.yml`을 직접 참조하도록 고친 뒤 run `33325903043`에서 config 1개와
rule 1개, Alertmanager 기본·CI config, firing webhook payload와 Prometheus·Alertmanager API
상태를 모두 통과했다. 같은 revision의 CodeQL run
`33325903025`도 성공했다.

Compose healthcheck 명령 검증을 추가한 최종 PR CI run `33326106111`에서도 같은 전체 경로가
성공했고 CodeQL run `33326106102`를 포함한 필수 gate 7개가 모두 통과했다.

## 로컬 검증

Docker daemon이 실행 중일 때 Compose에서 정확한 image 참조를 읽어 실행한다.

```bash
ALERTMANAGER_IMAGE="$(docker compose config --format json | python -c '
import json, sys
print(json.load(sys.stdin)["services"]["alertmanager"]["image"])
')" \
PROMETHEUS_IMAGE="$(docker compose config --format json | python -c '
import json, sys
print(json.load(sys.stdin)["services"]["prometheus"]["image"])
')" \
  ops/alertmanager/verify-routing.sh
```

Compose 실행 뒤에는 `http://localhost:9093/-/ready`와 Alertmanager UI를 확인한다.

## Production 채널 연결

운영 배포는 `ops/alertmanager/alertmanager.yml`을 그대로 사용하지 않고 환경별 config를 안전하게
주입한다.

1. 조직의 호출 정책에 따라 PagerDuty, incident.io, Slack 또는 인증된 webhook receiver를
   선택한다.
2. routing key, webhook URL과 token은 repository나 image에 넣지 않고 secret manager에서 file
   또는 배포 시점 config로 주입한다.
3. warning과 critical의 receiver, group/repeat interval, resolve notification과 inhibition을
   승인한다.
4. staging의 합성 alert로 firing·resolved 두 알림, grouping, deduplication과 silence를 확인한다.
5. 수신 시각, Alertmanager group, 외부 incident ID와 담당자 acknowledgment 시간을 증적으로
   남긴다.
6. 자격 증명 교체와 receiver 장애 때의 retry·fallback 경로를 훈련한다.

실제 채널 증적 전에는 “Alertmanager routing 구현·로컬 webhook 검증”만 완료 상태다. 외부
호출 채널 연결은 production secret manager와 함께 남은 작업으로 유지한다.
