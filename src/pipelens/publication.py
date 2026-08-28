import html

from pipelens.models import Classification, Diagnosis, RelatedFile, TrustLevel

MAX_GITHUB_BODY_CHARS = 60_000


def render_github_diagnosis(
    run_id: int,
    classification: Classification,
    diagnosis: Diagnosis,
    related_files: list[RelatedFile],
    details_url: str,
    trust_level: TrustLevel = TrustLevel.TRUSTED,
) -> str:
    sections = [
        "## PipeLens 실패 진단",
        "",
    ]
    if trust_level is TrustLevel.UNTRUSTED_FORK:
        sections.extend(
            [
                "> [!WARNING]",
                "> 외부 Fork에서 시작된 실행입니다. 규칙 기반 진단만 수행했으며,",
                "> Fork의 로그·코드·Workflow 내용은 LLM에 전송하지 않았습니다.",
                "",
            ]
        )
    sections.extend(
        [
            _safe(diagnosis.summary),
            "",
        f"**오류 유형:** `{classification.category.value}`  ",
        f"**신뢰도:** {diagnosis.confidence:.0%}  ",
        f"**관련 Step:** {_safe(classification.related_step or '확인 불가')}",
        "",
        "### 추정 원인",
        "",
        _safe(diagnosis.root_cause),
        "",
        "### 검증된 근거",
            "",
        ]
    )
    for evidence in diagnosis.evidence:
        location = f" · {_safe(evidence.location)}" if evidence.location else ""
        sections.extend(
            [
                f"**{_safe(evidence.source)}{location}**",
                _code_block(evidence.content),
                "",
            ]
        )

    sections.extend(["### 관련 변경 파일", ""])
    if related_files:
        for item in related_files:
            reasons = " · ".join(_safe(reason) for reason in item.reasons)
            sections.append(f"- `{_safe(item.filename)}` ({item.score:.0%}) — {reasons}")
    else:
        sections.append("로그와 직접 연결되는 변경 파일을 찾지 못했습니다.")

    sections.extend(["", "### 권장 해결 방법", ""])
    for index, suggestion in enumerate(diagnosis.suggestions, 1):
        target = f" (`{_safe(suggestion.file)}`)" if suggestion.file else ""
        sections.append(f"{index}. {_safe(suggestion.description)}{target}")
        if suggestion.patch:
            sections.extend(["", _code_block(suggestion.patch), ""])
    if not diagnosis.suggestions:
        sections.append("검증 가능한 수정 제안을 생성하지 못했습니다.")

    if diagnosis.conflicts:
        sections.extend(["", "### 분석 충돌", ""])
        sections.extend(f"- {_safe(item)}" for item in diagnosis.conflicts)
    if diagnosis.notes:
        sections.extend(["", "### 참고", ""])
        sections.extend(f"- {_safe(item)}" for item in diagnosis.notes)

    sections.extend(
        [
            "",
            "---",
            f"[PipeLens에서 전체 분석 보기]({_safe_url(details_url)}) · Workflow run `{run_id}`",
        ]
    )
    body = "\n".join(sections)
    if len(body) <= MAX_GITHUB_BODY_CHARS:
        return body
    suffix = f"\n\n---\n내용이 길어 일부를 생략했습니다. [전체 분석 보기]({_safe_url(details_url)})"
    return body[: MAX_GITHUB_BODY_CHARS - len(suffix)] + suffix


def _safe(value: str) -> str:
    return html.escape(value, quote=False).replace("@", "@\u200b")


def _safe_url(value: str) -> str:
    return value.replace("(", "%28").replace(")", "%29").replace(" ", "%20")


def _code_block(value: str) -> str:
    return f"<pre><code>{_safe(value)}</code></pre>"
