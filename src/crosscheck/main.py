"""FastAPI application entry point for CrossCheck AI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError as FastAPIRequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters import AdapterRegistry, default_adapter_registry
from .classification import Classifier
from .config import Settings, get_settings
from .contracts import (
    ErrorDetail,
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    QueryRequest,
    ReportResponse,
)
from .errors import (
    CrossCheckError,
    FeedbackClaimNotFound,
    FeedbackTargetNotFound,
)
from .persistence import Database, PersistenceError, ReportStore
from .query import QueryService
from .verifiers import VerifierRegistry


class Runtime:
    def __init__(
        self,
        *,
        settings: Settings,
        store: ReportStore,
        adapters: AdapterRegistry,
        verifiers: VerifierRegistry,
        classifier: Classifier | None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.adapters = adapters
        self.verifiers = verifiers
        self.classifier = classifier
        self.query_service = QueryService(
            settings=settings,
            store=store,
            adapters=adapters,
            verifiers=verifiers,
            classifier=classifier,
        )


def get_query_service(request: Request) -> QueryService:
    """FastAPI dependency kept public so tests and deployments can override it."""

    return request.app.state.runtime.query_service


def get_report_store(request: Request) -> ReportStore:
    """FastAPI dependency kept public for feedback and persistence tests."""

    return request.app.state.runtime.store


def create_app(
    *,
    settings: Settings | None = None,
    store: ReportStore | None = None,
    adapters: AdapterRegistry | None = None,
    verifiers: VerifierRegistry | None = None,
    classifier: Classifier | None = None,
) -> FastAPI:
    """Build an app with injectable ports for HTTP acceptance tests."""

    resolved_settings = settings or get_settings()
    database = store.database if store is not None else Database(resolved_settings.database_url)
    resolved_store = store or ReportStore(database)
    resolved_adapters = adapters or default_adapter_registry(resolved_settings.configured_models())
    resolved_verifiers = verifiers or VerifierRegistry()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Configuration is loaded and ports are wired at startup, but migrations and
        # external connections stay lazy so health remains safe on a fresh machine.
        application.state.runtime = Runtime(
            settings=resolved_settings,
            store=resolved_store,
            adapters=resolved_adapters,
            verifiers=resolved_verifiers,
            classifier=classifier,
        )
        try:
            yield
        finally:
            await resolved_store.database.dispose()

    application = FastAPI(
        title="CrossCheck AI",
        version="0.1.0",
        description="多模型答案验证与共识平台",
        lifespan=lifespan,
    )
    application.state.runtime = Runtime(
        settings=resolved_settings,
        store=resolved_store,
        adapters=resolved_adapters,
        verifiers=resolved_verifiers,
        classifier=classifier,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming[:128] if incoming else str(uuid4())
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > resolved_settings.max_body_bytes
            except ValueError:
                too_large = False
            if too_large:
                return _error_response(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    message="request body is too large",
                    request_id=request.state.request_id,
                )
        return await call_next(request)

    @application.exception_handler(FastAPIRequestValidationError)
    async def request_validation_handler(request: Request, exc: FastAPIRequestValidationError):
        details = []
        for error in exc.errors():
            details.append(
                {
                    "loc": list(error.get("loc", [])),
                    "msg": str(error.get("msg", "invalid value")),
                    "type": str(error.get("type", "value_error")),
                }
            )
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The request is invalid.",
            details=details,
            request_id=getattr(request.state, "request_id", str(uuid4())),
        )

    @application.exception_handler(CrossCheckError)
    async def crosscheck_error_handler(request: Request, exc: CrossCheckError):
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.safe_message,
            details=exc.details,
            request_id=getattr(request.state, "request_id", str(uuid4())),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        # Never echo a provider/driver exception: it may contain credentials or raw
        # upstream bodies.  The exception is intentionally only available to server
        # diagnostics, not to the public contract.
        del exc
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="CrossCheck could not complete the request.",
            request_id=getattr(request.state, "request_id", str(uuid4())),
        )

    @application.get("/health", response_model=dict[str, str])
    async def health() -> dict[str, str]:
        """Liveness endpoint independent of optional integrations."""

        return {"status": "ok"}

    @application.post("/api/query", response_model=ReportResponse, status_code=200)
    async def query(
        payload: QueryRequest,
        request: Request,
        service: QueryService = Depends(get_query_service),
    ) -> ReportResponse:
        try:
            request_uuid = UUID(request.state.request_id)
        except (ValueError, AttributeError):
            request_uuid = uuid4()
        return await service.execute(payload, request_id=request_uuid)

    @application.post("/api/feedback", response_model=FeedbackResponse, status_code=201)
    async def feedback(
        payload: FeedbackRequest,
        store: ReportStore = Depends(get_report_store),
    ) -> FeedbackResponse:
        try:
            return await store.create_feedback(payload)
        except PersistenceError as exc:
            if str(exc) == "report not found":
                raise FeedbackTargetNotFound() from exc
            if str(exc) == "claim does not belong to report":
                raise FeedbackClaimNotFound() from exc
            raise CrossCheckError() from exc

    return application


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: object | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


app = create_app()
