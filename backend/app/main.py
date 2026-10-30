"""FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import approvals, reads, runs
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.db.session import transaction

MAX_BODY_BYTES = 64 * 1024


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Operations AI API",
        version="0.1.0",
        description="Simulated support-operations agent. All refunds and messages are simulated.",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Request-ID"],
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error_code": "payload_too_large",
                                                          "message": "Request body too large"})
        return await call_next(request)

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        checks: dict[str, str] = {}
        try:
            with transaction() as session:
                session.execute(text("SELECT 1"))
                checks["database"] = "ok"
                found = session.execute(text("SELECT to_regclass('langgraph.checkpoints')")).scalar()
                checks["checkpointer"] = "ok" if found else "missing (run migrate)"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ok" if ok else "degraded", "checks": checks,
                                     "agent_model": settings.agent_model})

    app.include_router(reads.router, tags=["reads"])
    app.include_router(runs.router, tags=["runs"])
    app.include_router(approvals.router, tags=["approvals"])
    return app


app = create_app()
