# 저장소 보호와 변경 절차

## `main` 보호 정책

2026-08-30부터 `main`에는 GitHub branch protection을 적용한다.

- 모든 변경은 pull request를 통해 반영한다.
- 1인 저장소가 자기 PR을 승인할 수 없어 교착되는 것을 피하기 위해 승인 인원은 0명으로 두되,
  PR 자체와 모든 필수 status check는 강제한다.
- PR branch는 최신 `main`을 기준으로 다시 검증해야 한다(`strict: true`).
- 해결되지 않은 review conversation이 있으면 merge할 수 없다.
- 관리자에게도 같은 정책을 적용한다.
- merge commit은 허용하지 않고 선형 이력을 유지한다.
- force push와 branch 삭제를 허용하지 않는다.

필수 check는 모두 GitHub Actions app(`app_id: 15368`)이 만든 다음 context로 제한한다.

| Workflow | Required context |
| --- | --- |
| CI | `backend` |
| CI | `Python 3.14 compatibility` |
| CI | `dashboard` |
| CI | `Build container (api)` |
| CI | `Build container (dashboard)` |
| CodeQL | `Analyze (python)` |
| CodeQL | `Analyze (javascript-typescript)` |

## 변경 절차

1. 최신 `main`에서 목적별 branch를 만든다.
2. 서로 독립적으로 검토할 변경은 별도 commit으로 유지한다.
3. branch를 push하고 PR을 만든다.
4. 7개 필수 check와 추가 workflow가 성공했는지 확인한다.
5. review conversation이 모두 해결된 뒤 squash 또는 rebase 방식으로 merge한다.
6. merge commit의 `main` CI·CodeQL도 성공하는지 확인한다.

필수 job 이름을 바꾸면 기존 context가 영구 대기할 수 있다. 이 경우 새 이름의 job을 먼저
추가해 성공 실행을 만든 뒤 branch protection context를 갱신하고, 마지막에 이전 job 이름을
제거한다. workflow 변경과 protection 변경을 한 번에 추측으로 적용하지 않는다.

## 보호 범위 밖의 항목

branch protection은 version tag와 GitHub Release asset을 잠그지 않는다. Release workflow는
tag의 `main` ancestry와 version 일치를 별도로 검사한다. GitHub release immutability 설정은
2026-08-30 활성화했으며 미래 release부터 tag와 asset을 보호한다. `v0.1.0`은 해당 설정 전에
게시돼 immutable release가 아니다.

repository ruleset은 아직 사용하지 않는다. 현재 요구는 단일 `main` branch protection으로
충족하며, tag pattern 보호나 여러 branch의 공통 정책이 필요할 때 ruleset으로 이전한다.

설정 뒤 첫 보호된 변경은 [PR #18](https://github.com/sangmu1126/PipeLens/pull/18)에서
검증했다. check 실행 중에는 merge 상태가 `BLOCKED`였고, 등록한 7개 필수 context가 모두
성공한 뒤 `CLEAN`으로 바뀌었다. PR은 `c1e5bc7`로 squash merge됐으며 merge된 `main`의
[CI run 33288653155](https://github.com/sangmu1126/PipeLens/actions/runs/33288653155)와
[CodeQL run 33288653056](https://github.com/sangmu1126/PipeLens/actions/runs/33288653056)도
성공했다.
