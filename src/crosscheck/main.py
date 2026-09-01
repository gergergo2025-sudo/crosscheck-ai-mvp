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
    ConcurrencyLimitExceeded,
    CrossCheckError,
    FeedbackClaimNotFound,
    FeedbackTargetNotFound,
    RateLimitExceeded,
    RequestValidationError,
)
from .limits import NonBlockingConcurrency, SlidingWindowRateLimiter, client_identity
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
        rate_limiter: SlidingWindowRateLimiter | None = None,
        concurrency: NonBlockingConcurrency | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.adapters = adapters
        self.verifiers = verifiers
        self.classifier = classifier
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter(
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )
        self.concurrency = concurrency or NonBlockingConcurrency(settings.max_concurrent_queries)
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
    resolved_adapters = adapters or default_adapter_registry(
        resolved_settings.configured_models(), settings=resolved_settings
    )
    resolved_verifiers = verifiers or VerifierRegistry()
    rate_limiter = SlidingWindowRateLimiter(
        resolved_settings.rate_limit_requests,
        resolved_settings.rate_limit_window_seconds,
    )
    concurrency = NonBlockingConcurrency(resolved_settings.max_concurrent_queries)

    def build_runtime() -> Runtime:
        return Runtime(
            settings=resolved_settings,
            store=resolved_store,
            adapters=resolved_adapters,
            verifiers=resolved_verifiers,
            classifier=classifier,
            rate_limiter=rate_limiter,
            concurrency=concurrency,
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Configuration is loaded and ports are wired at startup, but migrations and
        # external connections stay lazy so health remains safe on a fresh machine.
        application.state.runtime = build_runtime()
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
    application.state.runtime = build_runtime()
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
        peer = request.client.host if request.client else None
        request.state.client_id = client_identity(
            peer=peer,
            forwarded_for=request.headers.get("x-forwarded-for"),
            real_ip=request.headers.get("x-real-ip"),
            trusted_proxies=resolved_settings.trusted_proxy_tokens(),
        )
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
        # Content-Length is absent or untrusted for chunked requests.  Reading and
        # caching the bounded body closes that gap while preserving FastAPI's body
        # parser for the endpoint.
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > resolved_settings.max_body_bytes:
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
        headers = None
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            headers = {"Retry-After": str(max(1, min(int(retry_after), 120)))}
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.safe_message,
            details=exc.details,
            request_id=getattr(request.state, "request_id", str(uuid4())),
            headers=headers,
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
        runtime = request.app.state.runtime
        decision = await runtime.rate_limiter.check(request.state.client_id)
        if not decision.allowed:
            raise RateLimitExceeded(retry_after=decision.retry_after_seconds)
        if not await runtime.concurrency.try_acquire():
            raise ConcurrencyLimitExceeded(retry_after=1)
        try:
            request_uuid = UUID(request.state.request_id)
        except (ValueError, AttributeError):
            request_uuid = uuid4()
        try:
            return await service.execute(payload, request_id=request_uuid)
        finally:
            runtime.concurrency.release()

    @application.post("/api/feedback", response_model=FeedbackResponse, status_code=201)
    async def feedback(
        payload: FeedbackRequest,
        request: Request,
        store: ReportStore = Depends(get_report_store),
    ) -> FeedbackResponse:
        settings = request.app.state.runtime.settings
        if payload.comment is not None and len(payload.comment) > settings.max_feedback_comment_length:
            raise RequestValidationError(
                "comment is too long",
                details={"comment": ["maximum length exceeded"]},
            )
        if payload.suggested_answer is not None and len(payload.suggested_answer) > settings.max_feedback_answer_length:
            raise RequestValidationError(
                "suggested_answer is too long",
                details={"suggested_answer": ["maximum length exceeded"]},
            )
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
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=headers)


app = create_app()
