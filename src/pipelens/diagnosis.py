from pipelens.models import Classification, Diagnosis, ErrorCategory, Evidence, Suggestion

MESSAGES: dict[ErrorCategory, tuple[str, str, str]] = {
    ErrorCategory.TEST: (
        "테스트가 실패했습니다.",
        "테스트 assertion 또는 테스트 준비 과정에서 최초 오류가 발생했습니다.",
        "최초 실패 테스트와 그 입력을 로컬에서 재현하세요.",
    ),
    ErrorCategory.BUILD: (
        "빌드 또는 컴파일이 실패했습니다.",
        "컴파일러가 코드 또는 링크 오류를 보고했습니다.",
        "최초 컴파일 오류 위치를 수정한 뒤 빌드를 다시 실행하세요.",
    ),
    ErrorCategory.DEPENDENCY: (
        "의존성 설치가 실패했습니다.",
        "패키지 버전 해석 또는 설치 단계에서 오류가 발생했습니다.",
        "lockfile과 런타임 버전을 확인하고 의존성을 다시 고정하세요.",
    ),
    ErrorCategory.LINT: (
        "Lint 또는 포맷 검사가 실패했습니다.",
        "코드 스타일 검사 도구가 위반 사항을 발견했습니다.",
        "CI와 동일한 lint/format 명령을 실행해 보고된 파일을 수정하세요.",
    ),
    ErrorCategory.DOCKER: (
        "Docker 이미지 빌드가 실패했습니다.",
        "Dockerfile의 빌드 단계가 정상적으로 완료되지 않았습니다.",
        "실패한 Dockerfile 단계와 build context를 확인하세요.",
    ),
    ErrorCategory.DEPLOY_AUTH: (
        "배포 인증에 실패했습니다.",
        "배포 대상이 현재 자격증명을 거부했습니다.",
        "배포용 secret의 만료 여부와 권한 범위를 확인하세요.",
    ),
    ErrorCategory.MISSING_ENV: (
        "필수 환경변수가 없습니다.",
        "실행에 필요한 환경변수가 workflow step에 전달되지 않았습니다.",
        "Repository/Environment secret과 workflow의 env 매핑을 확인하세요.",
    ),
    ErrorCategory.TIMEOUT: (
        "작업 제한 시간을 초과했습니다.",
        "명령이 허용된 시간 안에 끝나지 않았습니다.",
        "정체된 작업을 확인하고 필요하면 timeout-minutes를 조정하세요.",
    ),
    ErrorCategory.RESOURCE: (
        "실행 환경의 자원이 부족합니다.",
        "Runner의 디스크 또는 메모리가 소진되었습니다.",
        "캐시와 불필요한 산출물을 줄이거나 더 큰 runner를 사용하세요.",
    ),
    ErrorCategory.WORKFLOW: (
        "GitHub Actions workflow 설정이 유효하지 않습니다.",
        "Workflow YAML 표현식 또는 구문 검증에 실패했습니다.",
        "표시된 workflow 위치의 YAML과 Actions 표현식을 수정하세요.",
    ),
    ErrorCategory.UNKNOWN: (
        "실패 원인을 자동 분류하지 못했습니다.",
        "현재 로그만으로 원인을 확인할 수 없습니다.",
        "첫 오류 전후의 전체 로그와 workflow 설정을 확인하세요.",
    ),
}


def build_rule_based_diagnosis(classification: Classification) -> Diagnosis:
    summary, cause, suggestion = MESSAGES[classification.category]
    return Diagnosis(
        summary=summary,
        root_cause=cause if classification.category is not ErrorCategory.UNKNOWN else "확인 불가",
        confidence=classification.confidence,
        evidence=[
            Evidence(
                source="log",
                content=classification.first_error,
                location=classification.related_step,
            )
        ],
        suggestions=[Suggestion(description=suggestion)],
    )


def validate_diagnosis(
    diagnosis: Diagnosis, log: str, repository_files: set[str] | None = None
) -> Diagnosis:
    valid_evidence = [e for e in diagnosis.evidence if e.source != "log" or e.content in log]
    valid_suggestions = [
        s
        for s in diagnosis.suggestions
        if not s.file or (repository_files is not None and s.file in repository_files)
    ]
    if not valid_evidence:
        diagnosis.root_cause = "확인 불가"
        diagnosis.confidence = min(diagnosis.confidence, 0.3)
        diagnosis.conflicts.append("분석 결과가 입력 로그에서 확인할 수 없는 근거를 인용했습니다.")
    diagnosis.evidence = valid_evidence
    diagnosis.suggestions = valid_suggestions
    return diagnosis
