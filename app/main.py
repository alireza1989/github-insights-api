import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory, create_tables
from app.logging_config import configure_logging, get_logger
from app.routers import health

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Tests inject settings via app.state.settings before the lifespan starts so
    # they get an isolated in-memory DB.  In production app.state has no settings yet.
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    engine = build_engine(settings.database_url, echo=settings.debug)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.settings = settings

    await create_tables(engine)
    logger.info("startup complete", version=settings.app_version)

    yield

    await engine.dispose()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GitHub Insights API",
        description=(
            "Ingests GitHub collaboration data, computes reviewer-load and cycle-time metrics, "
            "and generates LLM-powered narrative insights."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: object) -> Response:
        request_id = str(uuid.uuid4())
        import structlog

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router)

    # Deferred router imports avoid circular deps and let models register first
    from app.routers import insights, metrics, sync  # noqa: PLC0415

    app.include_router(sync.router)
    app.include_router(metrics.router, prefix="/metrics")
    app.include_router(insights.router)

    @app.get("/", include_in_schema=False)
    async def serve_ui() -> FileResponse:
        return FileResponse("ui/index.html")

    return app


app = create_app()
