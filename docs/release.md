# 컨테이너 릴리스 정책과 절차

## 현재 상태

첫 [`v0.1.0` release](https://github.com/sangmu1126/PipeLens/releases/tag/v0.1.0)가 게시됐다.
API·대시보드 GHCR image와 각 digest의 SLSA provenance·CycloneDX SBOM attestation을 GitHub
API와 GHCR OCI registry 양쪽에서 검증했다. 정확한 digest와 검증 결과는
[v0.1.0 릴리스 증적](releases/v0.1.0.md)에 기록한다.

GitHub Release 자체는 immutable 설정을 켜기 전에 발행돼 `immutable: false`다. image digest와
attestation 검증 결과를 GitHub Release의 불변성으로 오해하지 않는다. 공식 정책상 설정은
미래 release에만 적용되므로 다음 release 전에 repository 설정을 변경해야 한다.

## 릴리스 단위

- release tag는 선행 0이 없는 `vMAJOR.MINOR.PATCH` 형식만 허용한다.
- tag commit은 `main` 이력에 포함돼야 한다.
- tag version은 `pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json`의 root와
  workspace version에 모두 일치해야 한다.
- image는 `ghcr.io/<owner>/pipelens-api:<tag>`와
  `ghcr.io/<owner>/pipelens-dashboard:<tag>`로 게시한다.
- `latest` tag는 만들지 않는다. 배포와 검증에는 version tag보다 immutable digest를 사용한다.
- 같은 version tag를 다른 commit에 다시 사용하지 않는다. 수정은 patch version을 올려 새
  release로 만든다.

## 자동 검증과 게시 순서

`.github/workflows/release.yml`은 tag push 뒤 다음 순서를 image별로 실행한다.

1. tag 형식, 세 version file과 `main` ancestry를 검증한다.
2. OCI source, revision, version과 MIT license label을 포함해 image를 로컬 빌드한다.
3. 수정 가능한 HIGH/CRITICAL OS·language package 취약점이 없는지 검사한다.
4. CycloneDX SBOM을 만들고 형식, version, serial number와 component 존재를 검증한다.
5. non-root runtime USER와 API readiness 또는 대시보드 HTTP 응답을 검사한다.
6. 모든 사전 검증을 통과한 image만 GHCR에 push하고 registry digest를 확정한다.
7. short-lived GitHub OIDC/Sigstore 인증서로 SLSA provenance와 CycloneDX SBOM attestation을
   각각 서명해 GitHub attestation API와 GHCR에 게시한다.

checkout, registry login, Trivy와 attestation Action은 모두 검증한 release commit SHA로
고정한다. 저장소가 개인 소유이므로 organization 전용 artifact storage record는 만들지 않는다.

## 후속 릴리스 전 확인

1. version 변경을 별도 commit으로 반영하고 Python·npm manifest와 lockfile을 동기화한다.
2. 해당 commit의 CI와 CodeQL이 모두 성공했는지 확인한다.
3. `vMAJOR.MINOR.PATCH` tag를 그 `main` commit에 생성해 push한다.
4. `Release containers`의 validate와 API·대시보드 publish job이 모두 성공했는지 확인한다.
5. 두 GHCR package의 digest, provenance와 SBOM attestation을 아래 방식으로 검증한다.
6. 검증된 tag로 GitHub Release를 만들고 변경 사항과 두 image digest를 release note에 기록한다.

GitHub Release는 자동으로 만들지 않는다. package visibility, release note와 immutable
release 설정을 사람이 확인해야 하며, tag push만으로 제품 배포가 완료됐다고 보지 않는다.
release immutability가 활성화되면 draft에 필요한 asset과 note를 모두 준비한 뒤 publish한다.

## 소비자 검증

먼저 GHCR에 로그인하고 version image를 받은 뒤 tag가 가리키는 digest를 사용한다.

```bash
docker pull ghcr.io/sangmu1126/pipelens-api:v0.1.0
image_ref="$(docker image inspect ghcr.io/sangmu1126/pipelens-api:v0.1.0 \
  --format '{{index .RepoDigests 0}}')"
```

provenance는 repository, signer workflow와 source tag를 함께 제한해 검증한다.

```bash
gh attestation verify "oci://$image_ref" \
  --repo sangmu1126/PipeLens \
  --signer-workflow sangmu1126/PipeLens/.github/workflows/release.yml \
  --source-ref refs/tags/v0.1.0
```

같은 digest의 CycloneDX SBOM attestation은 predicate type을 명시한다.

```bash
gh attestation verify "oci://$image_ref" \
  --repo sangmu1126/PipeLens \
  --signer-workflow sangmu1126/PipeLens/.github/workflows/release.yml \
  --source-ref refs/tags/v0.1.0 \
  --predicate-type https://cyclonedx.org/bom
```

대시보드 image도 같은 절차로 검증한다. registry에 저장된 bundle을 직접 사용할 때는
`--bundle-from-oci`를 추가한다.

## 실패와 복구

- push 전 scan·SBOM·runtime 검증이 실패하면 image는 게시되지 않는다. 원인을 고친 뒤 patch
  version을 올린다.
- matrix 한쪽이 push 뒤 실패하면 성공한 tag를 옮기지 않고 실패 job을 재실행한다. digest와
  두 attestation이 모두 확인되기 전에는 GitHub Release를 만들지 않는다.
- 게시 후 결함은 기존 tag를 덮어쓰지 않고 새 patch release로 복구한다.
- 운영 배포 rollback은 이전에 검증된 digest로 되돌린다. tag 이름만으로 rollback 대상을
  선택하지 않는다.
