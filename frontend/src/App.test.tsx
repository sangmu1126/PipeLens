import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Analysis, CurrentUser } from "./types";

const currentUser: CurrentUser = {
  github_user_id: 1,
  login: "octocat",
  avatar_url: null,
  installations: [{
    installation_id: 7,
    account_login: "acme",
    account_type: "Organization",
    repository_selection: "all",
  }],
};

function analysis(overrides: Partial<Analysis>): Analysis {
  return {
    run_id: 1,
    repository: "acme/api",
    workflow_name: "CI",
    head_sha: "abcdef123456",
    html_url: "https://github.com/acme/api/actions/runs/1",
    trust_level: "trusted",
    baseline_sha: null,
    status: "completed",
    classification: {
      category: "test_failure",
      confidence: 0.9,
      first_error: "pytest failed",
      related_step: "test",
      matched_rules: ["pytest"],
    },
    diagnosis: null,
    related_files: [],
    workflow_path: null,
    execution_context: null,
    model_name: null,
    prompt_version: null,
    feedback: null,
    error: null,
    analysis_started_at: null,
    analysis_completed_at: null,
    queue_wait_seconds: null,
    duration_seconds: null,
    total_latency_seconds: null,
    stage_history: [],
    created_at: "2026-08-29T12:00:00Z",
    updated_at: "2026-08-29T12:00:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, cursor?: string): Response {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (cursor) headers.set("X-PipeLens-Next-Cursor", cursor);
  return new Response(JSON.stringify(body), { status: 200, headers });
}

describe("PipeLens dashboard", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("shows the GitHub login screen for an unauthenticated user", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    render(<App />);

    expect(await screen.findByRole("link", { name: /GitHub로 로그인/ })).toHaveAttribute(
      "href",
      "/auth/github/login",
    );
  });

  it("loads the next cursor page without duplicating existing runs", async () => {
    const firstPage = [
      analysis({ run_id: 3, repository: "acme/api" }),
      analysis({ run_id: 2, repository: "acme/web" }),
    ];
    const secondPage = [
      analysis({ run_id: 2, repository: "acme/web" }),
      analysis({ run_id: 1, repository: "acme/worker" }),
    ];
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/me") return jsonResponse(currentUser);
      return url.includes("cursor=next-page")
        ? jsonResponse(secondPage)
        : jsonResponse(firstPage, "next-page");
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => {
      expect(within(screen.getByRole("table")).getByText("acme/api")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "이전 분석 더 보기" }));

    await waitFor(() => {
      expect(within(screen.getByRole("table")).getByText("acme/worker")).toBeInTheDocument();
    });
    expect(within(screen.getByRole("table")).getAllByText("acme/web")).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("cursor=next-page"))).toBe(
      true,
    );
  });

  it("requests and renders a server-side status filter", async () => {
    const completed = analysis({ run_id: 11, repository: "acme/api" });
    const failed = analysis({ run_id: 12, repository: "acme/web", status: "failed" });
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/me") return jsonResponse(currentUser);
      return url.includes("status=completed")
        ? jsonResponse([completed])
        : jsonResponse([completed, failed]);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => {
      expect(within(screen.getByRole("table")).getByText("acme/web")).toBeInTheDocument();
    });
    await user.selectOptions(screen.getByLabelText("상태"), "completed");

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("status=completed")),
      ).toBe(true);
      expect(within(screen.getByRole("table")).queryByText("acme/web")).not.toBeInTheDocument();
    });
    expect(within(screen.getByRole("table")).getByText("acme/api")).toBeInTheDocument();
  });
});
