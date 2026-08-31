# Docker Desktop 로컬 통합 검증

## 실행 기준

2026-08-31 `main` commit `7e1c5b1`을 macOS Docker Desktop에서 다시 검증했다.

| 항목 | 값 |
| --- | --- |
| Docker client/server | 29.6.2 / 29.6.2 |
| Docker Compose | 5.3.1 |
| engine architecture | `aarch64` |
| 할당 자원 | 8 CPU, 약 8GB memory |

이 기록은 GitHub-hosted amd64 runner 증적을 대체하지 않는다. 같은 multi-platform digest의
arm64 variant와 개발자 로컬 실행 경로를 추가로 검증한 결과다.

## 결과

### PostgreSQL 17→18

- source: PostgreSQL 17 고정 digest
  `sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73`
- target: PostgreSQL 18.6 고정 digest
  `sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2`
- migration 9개 적용, 표본 데이터 custom-format dump/restore와 `alembic check` 통과

### Grafana 12→13

- source: Grafana 12.1.0 고정 digest
  `sha256:6ac590e7cabc2fbe8d7b8fc1ce9c9f0582177b334e0df9c927ebd9670469440f`
- target: Grafana 13.2.0 고정 digest
  `sha256:3fd54ae1214669f8355f065ec9f6445d5279a3d77095ab048ca045685272429b`
- 같은 volume의 storage migration, 비관리 probe 보존, provisioned dashboard 8개 panel,
  Prometheus datasource와 익명 Viewer API 통과

### Alertmanager routing

- Alertmanager 0.33.1과 Prometheus 3.13.2의 Compose 고정 digest 사용
- 두 config와 Prometheus rule을 공식 검사기로 통과
- Prometheus firing → Alertmanager active → local webhook payload 전달 통과
- notifier discovery와 최초 rule 평가의 경쟁을 제거한 bootstrap/reload 경로를 연속 5회 통과

### PostgreSQL·Redis와 worker

- Docker가 임의 배정한 loopback port와 실행별 고유 컨테이너·volume을 사용
- PostgreSQL 18 migration·analysis lifecycle과 Redis 8.2 lease recovery 통합 테스트 2개 통과
- worker 4 replica가 200 job을 `49 / 50 / 50 / 51`로 처리
- orphan 1개 복구, 최대 시작·복구 2.117초, 최대 완료 2.128초
- 60초 시작·120초 완료 SLO와 정확히 한 번 처리, 최종 queue drain 통과

### 애플리케이션 이미지

| image | local manifest ID | 크기 | runtime user | smoke |
| --- | --- | ---: | --- | --- |
| `pipelens-api:local-7e1c5b1` | `sha256:d5985610…` | 84,835,055 bytes | `pipelens` | `/readyz` 성공 |
| `pipelens-dashboard:local-7e1c5b1` | `sha256:46393c3d…` | 26,459,688 bytes | `nginx` | 내부 `8080` 성공 |

두 image는 재검증을 위해 로컬 Docker image store에 남겼다. 실행 중 container나 drill용 volume은
남기지 않았다.

## 실행 중 발견한 로컬 경계

PostgreSQL과 Grafana script의 첫 실행은 스크립트 내부 `python` 또는 `alembic` 명령이 macOS
system PATH에 없어 실패했다. image pull과 임시 resource cleanup은 정상 동작했다. repository
가상환경을 PATH 앞에 둔 뒤 같은 명령이 통과했다.

```bash
PATH="$PWD/.venv/bin:$PATH" ops/postgres/verify-major-upgrade.sh
PATH="$PWD/.venv/bin:$PATH" ops/grafana/verify-major-upgrade.sh
```

실제 실행에는 각 문서와 CI처럼 current/previous image 환경변수를 함께 전달해야 한다. CI는
setup-python 설치 경로가 이미 PATH에 있으므로 이 차이의 영향을 받지 않는다.

PostgreSQL·Redis 통합 검증은 고정 host port나 고정 resource 이름을 사용하지 않았다. `mktemp`
기반 이름과 `127.0.0.1::<container-port>`의 Docker 임의 port를 사용해 기존 로컬 database와
충돌하지 않게 했고, trap은 이번 실행이 만든 container·volume만 정리했다.

## 남은 운영 경계

이 로컬 검증은 합성 데이터와 작은 volume을 사용한다. 다음은 완료로 바꾸지 않는다.

- production 규모 PostgreSQL backup 보관·복원 시간
- production Grafana volume backup 내구성과 복원 시간
- 실제 Alertmanager 호출 채널과 secret manager
- production resource limit·provider latency를 포함한 장시간 worker soak/load
- 공개 HTTPS, 실제 GitHub App과 OAuth/webhook 인수 테스트
