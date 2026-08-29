import base64
import binascii
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from pipelens.auth import AuthenticatedSession, AuthenticationError, AuthService
from pipelens.bootstrap import create_runtime
from pipelens.config import Settings, get_settings
from pipelens.github import GitHubConfigurationError
from pipelens.models import (
    AnalysisRecord,
    AnalysisRequest,
    AnalysisStatus,
    CurrentUser,
    ErrorCategory,
    FeedbackRecord,
    FeedbackRequest,
)
from pipelens.queue import AnalysisQueue
from pipelens.security import InvalidSignatureError, verify_github_signature
from pipelens.store import AnalysisCursor, AnalysisStore
from pipelens.worker import AnalysisWorker


async def reconcile_queued_analyses(store: AnalysisStore, queue: AnalysisQueue) -> int:
    reconciled = 0
    for analysis_request in store.queued_requests():
        if await queue.enqueue(analysis_request):
            reconciled += 1
    return reconciled


def _encode_analysis_cursor(cursor: AnalysisCursor) -> str:
    payload = json.dumps([cursor.created_at.isoformat(), cursor.run_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_analysis_cursor(value: str) -> AnalysisCursor:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        created_at_value, run_id = json.loads(decoded)
        created_at = datetime.fromisoformat(created_at_value)
        if created_at.tzinfo is None or not isinstance(run_id, int) or run_id < 1:
            raise ValueError
    except (binascii.Error, json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid analysis cursor") from exc
    return AnalysisCursor(created_at, run_id)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    runtime = create_runtime(settings)
    store, metrics = runtime.store, runtime.metrics
    auth = AuthService(settings, store, runtime.github)
    local_worker = (
        AnalysisWorker(
            runtime.pipeline,
            runtime.queue,
            runtime.store,
            runtime.metrics,
            settings.worker_max_attempts,
            settings.worker_heartbeat_seconds,
        )
        if settings.queue_backend == "memory"
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.initialize()
        reconciled = await reconcile_queued_analyses(store, runtime.queue)
        if reconciled:
            metrics.queue_reconciled.inc(reconciled)
        metrics.queue_depth.set(await runtime.queue.size())
        if local_worker:
            await local_worker.start()
        yield
        if local_worker:
            await local_worker.stop()
        await runtime.queue.close()
        store.close()

    app = FastAPI(title="PipeLens API", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.pipeline = runtime.pipeline
    app.state.queue = runtime.queue
    app.state.metrics = metrics
    app.state.auth = auth

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
        return response

    def get_store(request: Request) -> AnalysisStore:
        return request.app.state.store

    def require_session(request: Request) -> AuthenticatedSession:
        session = auth.authenticate(request.cookies.get("pipelens_session"))
        if session is None:
            raise HTTPException(status_code=401, detail="GitHub login required")
        return session

    async def analysis_access(request: Request) -> set[int] | None:
        if not settings.auth_required:
            return None
        session = require_session(request)
        installations = await auth.sync_installations(
            session.user.github_user_id, session.access_token
        )
        return {
            item.installation_id
            for item in installations
        }

    @app.get("/healthz", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    async def readiness(
        request: Request,
        analysis_store: Annotated[AnalysisStore, Depends(get_store)],
    ) -> Response:
        checks: dict[str, str] = {}
        try:
            analysis_store.healthcheck()
        except Exception:
            checks["database"] = "unavailable"
        else:
            checks["database"] = "ok"
        try:
            await request.app.state.queue.healthcheck()
        except Exception:
            checks["queue"] = "unavailable"
        else:
            checks["queue"] = "ok"
        ready = all(result == "ok" for result in checks.values())
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(metrics.registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    @app.get("/auth/github/login", tags=["auth"])
    async def github_login() -> RedirectResponse:
        try:
            client_id, _ = auth.require_oauth_configuration()
        except GitHubConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        state = auth.new_oauth_state()
        response = RedirectResponse(
            runtime.github.authorization_url(client_id, auth.callback_url, state),
            status_code=status.HTTP_302_FOUND,
        )
        response.set_cookie(
            "pipelens_oauth_state",
            state,
            max_age=600,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
        )
        return response

    @app.get("/auth/github/callback", tags=["auth"])
    async def github_callback(
        request: Request,
        code: str,
        state: str | None = None,
    ) -> RedirectResponse:
        try:
            auth.verify_oauth_state(state, request.cookies.get("pipelens_oauth_state"))
            session_token, _ = await auth.complete_login(code)
        except AuthenticationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (GitHubConfigurationError, KeyError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        response = RedirectResponse(settings.public_url, status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("pipelens_oauth_state")
        response.set_cookie(
            "pipelens_session",
            session_token,
            max_age=settings.session_ttl_days * 86_400,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
        )
        return response

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
    async def logout(
        request: Request,
        session: Annotated[AuthenticatedSession, Depends(require_session)],
    ) -> Response:
        auth.store.delete_auth_session(session.session_hash)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie("pipelens_session")
        return response

    @app.get("/api/me", response_model=CurrentUser, tags=["auth"])
    async def current_user(
        session: Annotated[AuthenticatedSession, Depends(require_session)],
    ) -> CurrentUser:
        installations = await auth.sync_installations(
            session.user.github_user_id, session.access_token
        )
        return CurrentUser(**session.user.model_dump(), installations=installations)

    @app.get("/github/install", tags=["github"])
    async def install_github_app(
        _: Annotated[AuthenticatedSession, Depends(require_session)],
    ) -> RedirectResponse:
        if not settings.github_app_slug:
            raise HTTPException(status_code=503, detail="GitHub App slug is not configured")
        return RedirectResponse(
            f"https://github.com/apps/{settings.github_app_slug}/installations/new",
            status_code=status.HTTP_302_FOUND,
        )

    @app.get("/github/setup", tags=["github"])
    async def github_setup(
        installation_id: int,
        session: Annotated[AuthenticatedSession, Depends(require_session)],
    ) -> RedirectResponse:
        installations = await auth.sync_installations(
            session.user.github_user_id, session.access_token
        )
        if installation_id not in {item.installation_id for item in installations}:
            raise HTTPException(status_code=403, detail="installation is not accessible to user")
        return RedirectResponse(settings.public_url, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED, tags=["github"])
    async def github_webhook(
        request: Request,
        analysis_store: Annotated[AnalysisStore, Depends(get_store)],
        x_github_event: Annotated[str | None, Header()] = None,
        x_github_delivery: Annotated[str | None, Header()] = None,
        x_hub_signature_256: Annotated[str | None, Header()] = None,
    ) -> Response:
        body = await request.body()
        try:
            verify_github_signature(body, x_hub_signature_256, settings.webhook_secret)
        except InvalidSignatureError as exc:
            metrics.webhooks.labels(outcome="invalid_signature").inc()
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        if x_github_event != "workflow_run":
            metrics.webhooks.labels(outcome="ignored_event").inc()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        if not x_github_delivery:
            metrics.webhooks.labels(outcome="invalid_payload").inc()
            raise HTTPException(status_code=400, detail="missing X-GitHub-Delivery header")
        try:
            payload = json.loads(body)
            run = payload["workflow_run"]
            repository = payload["repository"]["full_name"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            metrics.webhooks.labels(outcome="invalid_payload").inc()
            raise HTTPException(status_code=400, detail="invalid workflow_run payload") from exc
        if run.get("conclusion") != "failure" or payload.get("action") != "completed":
            metrics.webhooks.labels(outcome="ignored_run").inc()
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        installation_id = payload.get("installation", {}).get("id")
        if installation_id is None:
            metrics.webhooks.labels(outcome="invalid_payload").inc()
            raise HTTPException(status_code=400, detail="payload has no GitHub App installation id")
        record = AnalysisRecord(
            run_id=run["id"],
            delivery_id=x_github_delivery,
            repository=repository,
            workflow_name=run.get("name", "unknown workflow"),
            head_sha=run["head_sha"],
            html_url=run["html_url"],
            installation_id=installation_id,
        )
        created = analysis_store.create_if_absent(record)
        existing = record if created else analysis_store.get(record.run_id)
        enqueued = False
        if (
            existing
            and existing.status is AnalysisStatus.QUEUED
            and existing.installation_id is not None
        ):
            try:
                enqueued = await request.app.state.queue.enqueue(
                    AnalysisRequest(
                        run_id=existing.run_id,
                        repository=existing.repository,
                        installation_id=existing.installation_id,
                        head_sha=existing.head_sha,
                    )
                )
            except Exception as exc:
                metrics.webhooks.labels(outcome="queue_error").inc()
                raise HTTPException(status_code=503, detail="analysis queue unavailable") from exc
            metrics.queue_depth.set(await request.app.state.queue.size())
        outcome = "accepted" if created else "recovered" if enqueued else "duplicate"
        metrics.webhooks.labels(outcome=outcome).inc()
        return Response(
            content=json.dumps({"accepted": created or enqueued, "run_id": record.run_id}),
            media_type="application/json",
            status_code=status.HTTP_202_ACCEPTED,
        )

    @app.get("/api/analyses", response_model=list[AnalysisRecord], tags=["analyses"])
    async def list_analyses(
        response: Response,
        analysis_store: Annotated[AnalysisStore, Depends(get_store)],
        installation_ids: Annotated[set[int] | None, Depends(analysis_access)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        repository: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
        analysis_status: Annotated[
            AnalysisStatus | None, Query(alias="status")
        ] = None,
        category: ErrorCategory | None = None,
        cursor: str | None = None,
    ) -> list[AnalysisRecord]:
        page = analysis_store.list_page(
            limit,
            installation_ids,
            repository=repository,
            status=analysis_status,
            category=category,
            cursor=_decode_analysis_cursor(cursor) if cursor else None,
        )
        if page.next_cursor is not None:
            response.headers["X-PipeLens-Next-Cursor"] = _encode_analysis_cursor(
                page.next_cursor
            )
        return page.records

    @app.get("/api/analyses/{run_id}", response_model=AnalysisRecord, tags=["analyses"])
    async def get_analysis(
        run_id: int,
        analysis_store: Annotated[AnalysisStore, Depends(get_store)],
        installation_ids: Annotated[set[int] | None, Depends(analysis_access)],
    ) -> AnalysisRecord:
        record = analysis_store.get(run_id, installation_ids)
        if not record:
            raise HTTPException(status_code=404, detail="analysis not found")
        return record

    @app.put(
        "/api/analyses/{run_id}/feedback",
        response_model=FeedbackRecord,
        tags=["feedback"],
    )
    async def save_feedback(
        run_id: int,
        feedback: FeedbackRequest,
        analysis_store: Annotated[AnalysisStore, Depends(get_store)],
        installation_ids: Annotated[set[int] | None, Depends(analysis_access)],
    ) -> FeedbackRecord:
        saved = analysis_store.save_feedback(run_id, feedback, installation_ids)
        if saved is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        if feedback.accuracy is not None:
            metrics.feedback.labels(dimension="accuracy", value=feedback.accuracy.value).inc()
        if feedback.suggestion_resolved is not None:
            metrics.feedback.labels(
                dimension="suggestion_resolved",
                value=str(feedback.suggestion_resolved).lower(),
            ).inc()
        return saved

    return app


app = create_app()
