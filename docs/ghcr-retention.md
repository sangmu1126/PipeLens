# GHCR 보존 정책과 감사 절차

## 정책

`pipelens-api`와 `pipelens-dashboard`의 정식 `vMAJOR.MINOR.PATCH` image, manifest digest와
그 digest에 연결된 SLSA provenance·CycloneDX SBOM OCI attestation은 기간 제한 없이 보존한다.
이 artifact는 배포 재현, rollback과 공급망 조사 증적이므로 새 release가 나와도 이전 version을
자동 삭제하지 않는다.

- mutable `latest`, branch, commit SHA tag는 게시하지 않는다.
- 두 package는 같은 SemVer release tag 집합을 유지한다.
- 각 SemVer tag가 가리키는 `sha256:<64 hex>`마다 GHCR의 `sha256-<64 hex>` attestation tag를
  함께 보존한다.
- published GitHub Release, 배포 digest 또는 release 증적 문서가 참조하는 package version은
  삭제하지 않는다.
- workflow는 package나 version을 자동 삭제하지 않으며 `packages: write` 권한을 갖지 않는다.

저장 용량을 이유로 정식 release를 회전 삭제하지 않는다. 비용이나 GitHub 제한 때문에 이 정책을
바꿔야 하면 배포·rollback 보존 기간과 외부 archive를 먼저 결정하고 별도 설계 결정으로 남긴다.

## 자동 감사

`.github/workflows/ghcr-retention.yml`은 매월 1일 03:17 UTC와 수동 요청 때 공개 GHCR을 읽기
전용으로 감사한다. `ops/ghcr/audit_retention.py`는 다음을 실패 조건으로 판정한다.

1. 두 package 중 하나에 SemVer release가 없음
2. API와 dashboard의 SemVer tag 집합이 다름
3. `vMAJOR.MINOR.PATCH` 또는 `sha256-<64 hex>`가 아닌 tag 존재
4. release tag가 가리키는 manifest digest의 attestation tag 누락
5. 어떤 release digest도 가리키지 않는 attestation tag 존재

공개 pull token만 사용하므로 package visibility가 private로 바뀌어도 감사는 실패한다. workflow는
`contents: read`만 허용하고 삭제 API를 호출하지 않는다. 로컬에서도 다음처럼 실행할 수 있다.

```bash
python -m ops.ghcr.audit_retention --namespace sangmu1126
```

## 정리 후보와 수동 삭제

registry tag API는 untagged package version을 나열하지 않으므로 분기마다 GitHub Packages UI
또는 Packages REST API로 별도 inventory를 확인한다. 다음 조건을 모두 만족하는 실패한 부분 게시
artifact만 정리 후보로 분류한다.

1. GitHub Release, release 증적, 배포와 rollback 목록 어디에도 참조되지 않는다.
2. SemVer tag나 보존 대상 release digest의 attestation이 아니다.
3. 최초 발견 뒤 30일 동안 격리 목록에 기록했고 같은 상태가 유지됐다.
4. version ID, digest, 생성 시각, 참조 검사와 삭제 사유를 변경 기록에 남겼다.
5. 삭제 직전 API·dashboard package inventory와 최신 녹색 release를 다시 확인했다.

삭제는 package 전체가 아니라 정확한 package version ID만 대상으로 수동 실행한다. GitHub 공식
제약상 public package version의 download가 5,000회를 넘으면 직접 삭제할 수 없으며, 삭제한
version은 namespace가 재사용되지 않은 경우 30일 안에 복원할 수 있다. 오삭제를 발견하면 새
version을 게시하기 전에 즉시 복원하고 감사 workflow를 다시 실행한다.

## 현재 기준선

2026-08-31 공개 registry 감사 결과 두 package 모두 다음 두 tag만 가진다.

- `v0.1.0`
- 해당 release manifest와 일치하는 `sha256-<digest>` attestation tag

두 package의 SemVer 집합, digest 형식과 attestation 연결이 모두 통과했다. tag API로 볼 수 없는
untagged package version의 존재 여부는 위 분기별 수동 inventory 범위다.
