# PipeLens 개발 문서

이 디렉터리는 `README.md`의 사용자용 설명을 보완하는 개발·운영 기록이다. 문서의 기준
시점은 **2026-08-31**, 기준 브랜치는 `main`이다.

## 문서 구성

- [개발 연혁](development-history.md): 저장소가 만들어진 뒤 현재 상태까지의 구현 순서와
  관련 커밋
- [아키텍처](architecture.md): 런타임 구성, 분석 파이프라인, 데이터·신뢰 경계, 장애 처리
- [의사결정 기록](decisions.md): 중요한 설계 선택, 선택 이유, 포기한 대안과 결과
- [검증 및 운영 준비 현황](readiness.md): 테스트·CI·보안 현황, 검증되지 않은 부분과 남은 작업
- [컨테이너 릴리스](release.md): version tag, GHCR image, SBOM·provenance 게시와 검증 절차
  - [v0.1.0 릴리스 증적](releases/v0.1.0.md)
- [GHCR 보존 정책](ghcr-retention.md): 정식 image·attestation 영구 보존과 월별 감사
- [Worker replica drill](worker-replica-drill.md): Redis 부하, lease 장애 복구와 SLO 검증
- [Alertmanager](alertmanager.md): Prometheus alert routing, webhook 통합 검증과 운영 채널 경계
- [비밀값과 키 교체](secrets-and-rotation.md): secret inventory, Fernet rolling rotation과 침해 대응
- [API versioning](api-versioning.md): v1 계약, 호환성, deprecation과 OpenAPI drift gate
- [브라우저 E2E](browser-e2e.md): Chromium OAuth·session·dashboard 인수 흐름과 외부 검증 경계
- [로컬 Docker 검증](local-docker-validation.md): arm64 major-upgrade·routing·worker·image 증적
- [PostgreSQL 18 업그레이드](postgres-18-upgrade.md): 17 backup, 18 복원, 검증과 rollback 경계
- [PostgreSQL 복원 증적 drill](postgres-restore-drill.md): 격리 복원, RTO/RPO·무결성 JSON 증적
- [Grafana 13 업그레이드](grafana-13-upgrade.md): volume backup, unified storage migration과 rollback
- [저장소 보호와 변경 절차](repository-governance.md): `main` PR·필수 check와 운영 규칙

## 기록 원칙

1. 완료 여부는 코드, 테스트, Git 이력 또는 GitHub Actions 실행으로 확인된 것만 표시한다.
2. 개발 당시의 명시적 기록이 없는 동기는 현재 코드에서 확인되는 설계 근거와 구분한다.
3. 실제 GitHub App 설치나 운영 배포처럼 외부 환경이 필요한 항목은 코드가 존재하더라도
   `미검증`으로 표시한다.
4. 설계나 운영 경계가 바뀌면 해당 변경 커밋에서 관련 문서를 함께 갱신한다.

## 현재 한 줄 상태

MVP 요구 기능, 자동화된 로컬·CI 검증, `main` 보호와 서명 image release·보존 정책은 구현됐다.
실제 GitHub App 설치를 통한 종단 간 인수 테스트와 production HTTPS 배포는 아직 남아 있다.
