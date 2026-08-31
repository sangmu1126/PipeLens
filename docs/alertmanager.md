# Alertmanager routing과 운영 채널 연결

## 현재 구성

Compose는 Alertmanager 0.33.1 multi-platform manifest를 digest로 고정해 실행한다.

```text
prom/alertmanager:v0.33.1@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d
```

조회한 manifest는 linux/amd64, linux/arm64, linux/arm/v7, linux/ppc64le와 linux/s390x를
포함한다. 신규 설치이므로 Alertmanager는 `utf8-strict-mode`로 시작한다. 개발 Compose는
단일 replica이므로 `--cluster.listen-address=`로 HA gossip을 끈다. Compose Dependabot은 0.33.x
patch와 digest만 자동 제안하고, 0.x minor 전환은 release note와 config 호환성을 수동 검토한다.

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
5. Prometheus readiness와 API의 firing 상태를 확인한다.
6. Alertmanager API에서 같은 alert가 active가 될 때까지 확인한다.
7. Alertmanager가 group화한 webhook JSON을 로컬 일회성 receiver에 POST하면 version, receiver,
   firing status, alert name, severity, environment와 summary를 검증한다.

receiver는 실제 socket bind 뒤 준비 파일을 만들고 최대 1 MiB JSON 하나만 받는다. 전체 수신
상한은 180초이며 Prometheus readiness, firing, Alertmanager active와 webhook 전달에는 각각 더
짧은 제한을 둔다. 따라서 실패 시 어느 단계에서 멈췄는지 API의 마지막 응답과 container log로
구분할 수 있다. 모든 container, network와 임시 payload는 성공·실패와 관계없이 정리한다.
webhook URL과 테스트 alert는 CI fixture에만 있으며 기본 Compose config에는 포함되지 않는다.

PR #45의 첫 CI run `33325807628`은 합성 Prometheus config가 실제 mount 경로와 다른 rule
glob을 참조해 rule 0개로 기동했고 webhook 대기 시간이 초과됐다. fixture가 mount한
`/etc/prometheus/probe.yml`을 직접 참조하도록 고친 뒤 run `33325903043`에서 config 1개와
rule 1개, Alertmanager 기본·CI config, firing webhook payload와 Prometheus·Alertmanager API
상태를 모두 통과했다. 같은 revision의 CodeQL run
`33325903025`도 성공했다.

Compose healthcheck 명령 검증을 추가한 최종 PR CI run `33326106111`에서도 같은 전체 경로가
성공했고 CodeQL run `33326106102`를 포함한 필수 gate 7개가 모두 통과했다.

병합 직후 기본 HA gossip이 남은 상태의 `main` CI run `33326887437`은 webhook 30초 제한으로
실패했다. 단일-node HA를 끄고 제한을 60초로 보강한 PR #48 CI run `33327036671`과 병합 후
`main` CI run `33327158576`은 라우팅을 각각 통과했다. 최종 `main` CodeQL run
`33327158575`도 성공했다.

GitHub Actions 참조를 SHA로 고정한 PR #51의 첫 CI run `33361428377`은 Prometheus와
Alertmanager가 정상 기동했지만 60초 안에 webhook payload를 받지 못했다. 당시 드릴은 payload
파일만 기다려 Prometheus 평가, Alertmanager 수신과 webhook 연결 중 어느 구간이 원인인지
판별할 수 없었다. receiver bind 완료를 명시적으로 기다리고 두 API 상태를 순서대로 관측한 뒤
webhook을 확인하도록 보강했다. 로컬 Docker daemon이 없어 이 container 경로의 최종 판정은
PR #51의 GitHub runner 결과로 남긴다. 보강 후 CI run `33361752707`은 Prometheus firing,
Alertmanager active와 최종 webhook payload를 순서대로 확인해 전체 경로를 통과했다. rebase merge
후 `main` CI run `33362037504`에서도 같은 단계가 다시 성공했다.

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

2026-08-31에는 Docker Desktop 29.6.2 arm64에서 Compose의 Alertmanager 0.33.1과 Prometheus
3.13.2 digest로 config·rule, firing·active 상태와 최종 webhook payload를 로컬에서도 통과했다.
상세 환경과 정리 상태는 [Docker Desktop 로컬 통합 검증](local-docker-validation.md)에 남겼다.

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
7. replica를 둘 이상 운영한다면 각 Alertmanager를 load balancer 뒤에 숨기지 않고 Prometheus가
   모든 replica로 보내도록 구성한 뒤 TCP·UDP gossip과 deduplication을 검증한다.

실제 채널 증적 전에는 “Alertmanager routing 구현·로컬 webhook 검증”만 완료 상태다. 외부
호출 채널 연결은 production secret manager와 함께 남은 작업으로 유지한다.
