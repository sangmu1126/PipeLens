import { useCallback, useEffect, useMemo, useState } from "react";
import type { Analysis, CurrentUser, FeedbackAccuracy } from "./types";

const categoryLabels: Record<string, string> = {
  test_failure: "테스트",
  build_failure: "빌드",
  dependency_installation_failure: "의존성",
  lint_or_formatter_failure: "Lint",
  docker_build_failure: "Docker",
  deployment_authentication_failure: "배포 인증",
  missing_environment_variable: "환경변수",
  timeout: "Timeout",
  resource_exhaustion: "리소스",
  github_actions_workflow_error: "Workflow",
  unknown: "미분류",
};

const statusLabels = {
  queued: "대기",
  running: "분석 중",
  completed: "완료",
  failed: "실패",
};

function App() {
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [selectedRun, setSelectedRun] = useState<number | null>(() => {
    const value = Number(new URLSearchParams(window.location.search).get("run_id"));
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<CurrentUser | null | undefined>(undefined);

  const loadAnalyses = useCallback(async () => {
    try {
      const response = await fetch("/api/analyses?limit=100");
      if (response.status === 401) {
        setUser(null);
        return;
      }
      if (!response.ok) throw new Error(`분석 목록 요청 실패 (${response.status})`);
      const data = (await response.json()) as Analysis[];
      setAnalyses(data);
      setSelectedRun((current) =>
        current && data.some((item) => item.run_id === current)
          ? current
          : data[0]?.run_id ?? null,
      );
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initialize = async () => {
      try {
        const response = await fetch("/api/me");
        if (response.status === 401) {
          setUser(null);
          setLoading(false);
          return;
        }
        if (!response.ok) throw new Error(`사용자 정보 요청 실패 (${response.status})`);
        setUser((await response.json()) as CurrentUser);
        await loadAnalyses();
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "연결하지 못했습니다.");
        setLoading(false);
      }
    };
    void initialize();
  }, [loadAnalyses]);

  useEffect(() => {
    if (!user) return;
    const timer = window.setInterval(() => void loadAnalyses(), 30_000);
    return () => window.clearInterval(timer);
  }, [loadAnalyses, user]);

  const selected = analyses.find((analysis) => analysis.run_id === selectedRun) ?? null;
  const stats = useMemo(() => {
    const completed = analyses.filter((item) => item.status === "completed").length;
    const active = analyses.filter((item) => ["queued", "running"].includes(item.status)).length;
    const confidences = analyses
      .map((item) => item.diagnosis?.confidence)
      .filter((value): value is number => value !== undefined);
    const average = confidences.length
      ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
      : 0;
    return { completed, active, average };
  }, [analyses]);

  const updateFeedback = (runId: number, feedback: Analysis["feedback"]) => {
    setAnalyses((items) =>
      items.map((item) => (item.run_id === runId ? { ...item, feedback } : item)),
    );
  };

  const logout = async () => {
    await fetch("/auth/logout", { method: "POST" });
    setUser(null);
    setAnalyses([]);
  };

  const selectRun = (runId: number) => {
    setSelectedRun(runId);
    const url = new URL(window.location.href);
    url.searchParams.set("run_id", runId.toString());
    window.history.replaceState({}, "", url);
  };

  if (user === undefined) {
    return <AccessScreen loading error={error} />;
  }
  if (user === null) {
    return <AccessScreen />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>PipeLens</span>
        </div>
        <div className="topbar-meta">
          {user.avatar_url && <img src={user.avatar_url} alt="" />}
          <span>{user.login}</span>
          <button onClick={() => void logout()}>로그아웃</button>
        </div>
      </header>

      <main>
        <section className="hero">
          <div>
            <p className="eyebrow">CI FAILURE INTELLIGENCE</p>
            <h1>실패의 첫 원인을<br />근거와 함께 찾습니다.</h1>
            <p className="hero-copy">로그, 코드 변경, Workflow 설정을 교차 검증한 분석 결과입니다.</p>
          </div>
          <div className="stats" aria-label="분석 통계">
            <Stat label="전체 실행" value={analyses.length.toString().padStart(2, "0")} />
            <Stat label="진단 완료" value={stats.completed.toString().padStart(2, "0")} accent />
            <Stat label="진행 중" value={stats.active.toString().padStart(2, "0")} />
            <Stat label="평균 신뢰도" value={`${Math.round(stats.average * 100)}%`} />
          </div>
        </section>

        {error && <div className="alert"><strong>연결 오류</strong><span>{error}</span></div>}

        {user.installations.length === 0 ? (
          <section className="install-card">
            <p className="eyebrow">CONNECT GITHUB APP</p>
            <h2>분석할 저장소를 연결하세요.</h2>
            <p>PipeLens GitHub App을 계정 또는 조직에 설치하면 실패한 Workflow 분석이 여기에 표시됩니다.</p>
            <a href="/github/install">GitHub App 설치하기 ↗</a>
          </section>
        ) : (

        <section className="workspace">
          <div className="list-panel">
            <div className="section-heading">
              <div><p className="eyebrow">RECENT RUNS</p><h2>최근 분석</h2></div>
              <button className="refresh" onClick={() => void loadAnalyses()} disabled={loading}>
                {loading ? "불러오는 중" : "새로고침"}
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>저장소 / Workflow</th><th>상태</th><th>오류 유형</th><th>신뢰도</th><th>실행 시각</th></tr></thead>
                <tbody>
                  {analyses.map((analysis) => (
                    <tr key={analysis.run_id} className={analysis.run_id === selectedRun ? "selected" : ""}>
                      <td>
                        <button className="run-select" onClick={() => selectRun(analysis.run_id)}>
                          <strong>{analysis.repository}</strong>
                          <span>{analysis.trust_level === "untrusted_fork" ? "외부 Fork · " : ""}{analysis.workflow_name} · {analysis.head_sha.slice(0, 7)}</span>
                        </button>
                      </td>
                      <td><StatusBadge status={analysis.status} /></td>
                      <td>{categoryLabels[analysis.classification?.category ?? "unknown"] ?? analysis.classification?.category}</td>
                      <td><Confidence value={analysis.diagnosis?.confidence ?? analysis.classification?.confidence} /></td>
                      <td className="date-cell">{formatDate(analysis.created_at)}</td>
                    </tr>
                  ))}
                  {!loading && analyses.length === 0 && (
                    <tr><td colSpan={5} className="empty-row">아직 수집된 Workflow 실패가 없습니다.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <aside className="detail-panel">
            {selected ? (
              <AnalysisDetail analysis={selected} onFeedback={updateFeedback} />
            ) : (
              <div className="detail-empty"><span>◎</span><p>분석을 선택하면 근거와 해결 방법을 확인할 수 있습니다.</p></div>
            )}
          </aside>
        </section>
        )}
      </main>
      <footer><span>PipeLens</span><span>Evidence over assumptions.</span></footer>
    </div>
  );
}

function AccessScreen({ loading = false, error = null }: { loading?: boolean; error?: string | null }) {
  return <div className="access-shell">
    <div className="access-brand"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>PipeLens</div>
    <main className="access-card">
      <p className="eyebrow">CI FAILURE INTELLIGENCE</p>
      <h1>{loading ? "연결 상태를 확인하고 있습니다." : "GitHub와 연결해 분석을 시작하세요."}</h1>
      <p>{error ?? "접근 가능한 GitHub App 설치만 확인하고, 해당 저장소의 실패 분석만 보여드립니다."}</p>
      {!loading && <a href="/auth/github/login">GitHub로 로그인 ↗</a>}
    </main>
  </div>;
}

function Stat({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className={`stat ${accent ? "accent" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

function StatusBadge({ status }: { status: Analysis["status"] }) {
  return <span className={`status status-${status}`}><i />{statusLabels[status]}</span>;
}

function Confidence({ value }: { value: number | undefined }) {
  if (value === undefined) return <span className="muted">—</span>;
  const percent = Math.round(value * 100);
  return <span className="confidence"><i><b style={{ width: `${percent}%` }} /></i>{percent}%</span>;
}

function AnalysisDetail({ analysis, onFeedback }: { analysis: Analysis; onFeedback: (runId: number, feedback: Analysis["feedback"]) => void }) {
  const diagnosis = analysis.diagnosis;
  return (
    <div className="detail-content">
      <div className="detail-topline"><StatusBadge status={analysis.status} /><a href={analysis.html_url} target="_blank" rel="noreferrer">GitHub에서 보기 ↗</a></div>
      <h2>{diagnosis?.summary ?? "분석 결과를 기다리는 중입니다."}</h2>
      <p className="run-id">RUN #{analysis.run_id} · {analysis.workflow_name}</p>
      {analysis.trust_level === "untrusted_fork" && (
        <div className="trust-warning">
          <strong>외부 Fork의 비신뢰 실행</strong>
          <span>Fork에서 생성된 로그·코드·Workflow는 LLM에 전송하지 않았으며 규칙 기반 결과만 제공합니다.</span>
        </div>
      )}

      {diagnosis && <>
        <DetailSection number="01" title="추정 원인">
          <p className="root-cause">{diagnosis.root_cause}</p>
          {analysis.classification?.related_step && (
            <p className="step-location"><span>실패 위치</span>{analysis.classification.related_step}</p>
          )}
          <Confidence value={diagnosis.confidence} />
          {diagnosis.conflicts.map((conflict) => <p className="conflict" key={conflict}>{conflict}</p>)}
          {diagnosis.notes.map((note) => <p className="note" key={note}>{note}</p>)}
        </DetailSection>

        <DetailSection number="02" title="검증된 근거">
          <div className="evidence-list">
            {diagnosis.evidence.map((item, index) => <article className="evidence" key={`${item.source}-${index}`}>
              <div><span>{item.source}</span>{item.location && <small>{item.location}</small>}</div>
              <code>{item.content}</code>
            </article>)}
          </div>
        </DetailSection>

        <DetailSection number="03" title="관련 변경 파일">
          {analysis.baseline_sha && (
            <p className="comparison-range">
              직전 성공 <code>{analysis.baseline_sha.slice(0, 7)}</code>
              <span>→</span>
              실패 <code>{analysis.head_sha.slice(0, 7)}</code>
            </p>
          )}
          {analysis.related_files.length ? analysis.related_files.map((file) => <article className="file-card" key={file.filename}>
            <div><code>{file.filename}</code><strong>{Math.round(file.score * 100)}%</strong></div>
            <p>{file.reasons.join(" · ")}</p>
            {file.patch_excerpt && <pre>{file.patch_excerpt}</pre>}
          </article>) : <p className="muted">직접 연결되는 변경 파일을 찾지 못했습니다.</p>}
        </DetailSection>

        <DetailSection number="04" title="권장 해결 방법">
          <ol className="suggestions">{diagnosis.suggestions.map((item, index) => <li key={`${item.description}-${index}`}>
            <span>{String(index + 1).padStart(2, "0")}</span><div><p>{item.description}</p>{item.file && <code>{item.file}</code>}{item.patch && <pre>{item.patch}</pre>}</div>
          </li>)}</ol>
        </DetailSection>

        <FeedbackForm analysis={analysis} onSaved={(feedback) => onFeedback(analysis.run_id, feedback)} />
      </>}
    </div>
  );
}

function DetailSection({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <section className="detail-section"><header><span>{number}</span><h3>{title}</h3></header>{children}</section>;
}

function FeedbackForm({ analysis, onSaved }: { analysis: Analysis; onSaved: (feedback: Analysis["feedback"]) => void }) {
  const [accuracy, setAccuracy] = useState<FeedbackAccuracy | null>(analysis.feedback?.accuracy ?? null);
  const [resolved, setResolved] = useState(analysis.feedback?.suggestion_resolved ?? false);
  const [comment, setComment] = useState(analysis.feedback?.comment ?? "");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    setAccuracy(analysis.feedback?.accuracy ?? null);
    setResolved(analysis.feedback?.suggestion_resolved ?? false);
    setComment(analysis.feedback?.comment ?? "");
    setState("idle");
  }, [analysis.run_id, analysis.feedback]);

  const submit = async () => {
    if (!accuracy) return;
    setState("saving");
    try {
      const response = await fetch(`/api/analyses/${analysis.run_id}/feedback`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accuracy, suggestion_resolved: resolved, comment: comment || null }),
      });
      if (!response.ok) throw new Error("feedback request failed");
      onSaved(await response.json());
      setState("saved");
    } catch {
      setState("error");
    }
  };

  return <section className="feedback-box">
    <p className="eyebrow">FEEDBACK LOOP</p><h3>이 분석이 도움이 되었나요?</h3>
    <div className="rating-buttons">
      {(["accurate", "partial", "inaccurate"] as FeedbackAccuracy[]).map((value) => (
        <button key={value} className={accuracy === value ? "active" : ""} onClick={() => setAccuracy(value)}>
          {value === "accurate" ? "정확함" : value === "partial" ? "일부 정확" : "정확하지 않음"}
        </button>
      ))}
    </div>
    <label className="resolved-check"><input type="checkbox" checked={resolved} onChange={(event) => setResolved(event.target.checked)} /><span>제안으로 문제가 해결됨</span></label>
    <textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={2000} placeholder="규칙과 프롬프트 개선에 도움이 될 내용을 남겨주세요. (선택)" />
    <div className="feedback-actions"><span>{state === "saved" ? "저장되었습니다." : state === "error" ? "저장하지 못했습니다." : ""}</span><button onClick={() => void submit()} disabled={!accuracy || state === "saving"}>{state === "saving" ? "저장 중" : "피드백 저장"}</button></div>
  </section>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default App;
