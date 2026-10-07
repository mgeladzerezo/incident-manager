import time
from collections.abc import Sequence

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app import metrics
from app.api import incidents, policies, schedules, users, webhooks
from app.auth import JwksKeyProvider, TokenVerifier
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.notifications import Notifier, build_notifiers

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    clock: Clock | None = None,
    verifier: TokenVerifier | None = None,
    notifiers: Sequence[Notifier] | None = None,
) -> FastAPI:
    """Build the application. Everything that touches the outside world can be passed in,
    which is how the tests swap in SQLite, a fake clock and locally signed tokens."""
    settings = settings or get_settings()
    app = FastAPI(title="Incident Manager", version="0.1.0")

    app.state.settings = settings
    app.state.session_factory = session_factory or make_session_factory(
        make_engine(settings.database_url)
    )
    app.state.clock = clock or SystemClock()
    app.state.verifier = verifier or TokenVerifier(
        settings.oidc_issuer, settings.oidc_audience, JwksKeyProvider(settings.jwks_url)
    )
    app.state.notifiers = list(notifiers) if notifiers is not None else build_notifiers(settings)

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.middleware("http")(_record_request_metrics)

    for module in (webhooks, incidents, schedules, policies, users):
        app.include_router(module.router, prefix=API_PREFIX)
    app.include_router(_ops_router())
    return app


async def _record_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    path = _route_template(request)
    metrics.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    metrics.HTTP_DURATION.labels(request.method, path).observe(time.perf_counter() - started)
    return response


def _route_template(request: Request) -> str:
    """Route template such as /api/v1/incidents/{incident_id}, never the raw path, so the
    metric label set stays bounded."""
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    # Depending on the FastAPI version an included router reports its path with or without
    # the include prefix.
    under_api = request.url.path.startswith(API_PREFIX) and not route.path.startswith(API_PREFIX)
    return f"{API_PREFIX}{route.path}" if under_api else route.path


def _ops_router() -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz(request: Request) -> dict[str, str]:
        try:
            with request.app.state.session_factory() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable"
            ) from exc
        return {"status": "ready"}

    @router.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
