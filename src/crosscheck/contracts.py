"""Public and provider-neutral contracts for the CrossCheck tracer.

The first slice deliberately keeps the contracts independent of any provider SDK or
ORM.  Later slices can add fields to the report while retaining these stable names
and identifiers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


QuestionType = Literal["auto", "fact", "code", "constraint"]
OutputFormat = Literal["plain", "list", "table", "steps"]
ClaimType = Literal[
    "fact",
    "code",
    "math",
    "logic",
    "opinion",
    "recommendation",
]
VerificationStatus = Literal[
    "pending",
    "verified",
    "unverified",
    "conflict",
    "unavailable",
    "not_applicable",
]
ParseStatus = Literal["parsed", "degraded"]


class StrictRequestModel(BaseModel):
    """Request-facing models reject unknown fields to catch client mistakes."""

    model_config = ConfigDict(extra="forbid")


class FlexibleResponseModel(BaseModel):
    """Response/domain models tolerate additive fields from future slices."""

    model_config = ConfigDict(extra="ignore")


class QueryRequest(StrictRequestModel):
    question: str = Field(min_length=1, max_length=10_000)
    constraints: dict[str, Any] | str | None = None
    question_type: QuestionType = "auto"
    expected_output_format: OutputFormat | None = None
    models: list[str] | None = None
    refresh: bool = False

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: dict[str, Any] | str | None) -> dict[str, Any] | str | None:
        if isinstance(value, str):
            if len(value) > 10_000:
                raise ValueError("constraints is too long")
            if not value.strip():
                return None
        elif value is not None and not isinstance(value, dict):
            raise ValueError("constraints must be an object or string")
        return value

    @field_validator("models")
    @classmethod
    def normalize_models(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for model in value:
            if not isinstance(model, str) or not model.strip():
                raise ValueError("models must contain non-empty strings")
            model_name = model.strip()
            if model_name not in seen:
                normalized.append(model_name)
                seen.add(model_name)
        if not normalized:
            raise ValueError("models must contain at least one model")
        return normalized

    @model_validator(mode="after")
    def reject_empty_explicit_models(self) -> QueryRequest:
        # Kept as a model-level guard so an explicitly supplied [] is rejected even
        # when a caller bypasses the list validator via a custom adapter.
        if self.models is not None and len(self.models) == 0:
            raise ValueError("models must contain at least one model")
        return self


class Claim(FlexibleResponseModel):
    id: UUID | None = None
    claim: str = Field(min_length=1, max_length=20_000)
    type: ClaimType
    source: str | None = Field(default=None, max_length=4_000)
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: str | None = Field(default=None, max_length=4_000)
    cluster_id: UUID | None = None
    verification_status: VerificationStatus = "pending"
    verification_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_ids: list[UUID] = Field(default_factory=list)
    verification_ids: list[UUID] = Field(default_factory=list)

    @field_validator("claim")
    @classmethod
    def claim_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim must not be blank")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def confidence_must_be_numeric(cls, value: object) -> object:
        # Pydantic considers bool an int, but a model's ``true``/``false`` is not
        # a valid self-reported confidence number for this contract.
        if isinstance(value, bool):
            raise ValueError("confidence must be a number")
        return value


class StructuredAnswer(FlexibleResponseModel):
    answer: str = Field(min_length=1, max_length=100_000)
    reasoning: str = Field(default="", max_length=20_000)
    # These collections are part of the required provider contract.  Optional
    # fields inside each claim (source and assumptions) remain nullable.
    claims: list[Claim]
    constraints_check: dict[str, Any]

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value


class VerificationResult(FlexibleResponseModel):
    id: UUID | None = None
    verifier_type: str = "deterministic"
    verifier_version: str = "1"
    status: VerificationStatus = "unverified"
    verified: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = Field(default=None, ge=0.0)
    failure_class: str | None = None

    @model_validator(mode="after")
    def verified_matches_status(self) -> VerificationResult:
        # ``verified`` is retained for compatibility with the PRD, but the closed
        # status vocabulary is authoritative.
        self.verified = self.status == "verified"
        return self


class AdapterResult(FlexibleResponseModel):
    raw_text: str = Field(default="", max_length=120_000)
    provider: str
    model: str
    latency_ms: float | None = Field(default=None, ge=0.0)
    token_usage: dict[str, Any] | None = None
    reported_cost: float | None = Field(default=None, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    status: str = "ok"
    failure_class: str | None = None


class ModelAnswer(FlexibleResponseModel):
    id: UUID
    model: str
    provider: str
    answer: str
    reasoning: str = ""
    claims: list[Claim] = Field(default_factory=list)
    constraints_check: dict[str, Any] = Field(default_factory=dict)
    parse_status: ParseStatus = "parsed"
    parse_diagnostics: list[str] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    score_components: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = Field(default=None, ge=0.0)
    token_usage: dict[str, Any] | None = None
    reported_cost: float | None = Field(default=None, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    provider_status: str = "ok"
    failure_class: str | None = None


class QuestionSummary(FlexibleResponseModel):
    id: UUID
    text: str
    constraints: dict[str, Any] | str | None = None
    question_type: Literal["fact", "code", "constraint"]
    question_type_origin: Literal[
        "explicit",
        "deterministic_code",
        "deterministic_constraints",
        "classifier",
        "fallback",
    ]
    expected_output_format: OutputFormat | None = None
    models: list[str] = Field(default_factory=list)


class ReportResponse(FlexibleResponseModel):
    report_id: UUID
    status: Literal["complete", "partial"]
    cached: bool = False
    created_at: datetime
    duration_ms: float = Field(ge=0.0)
    question: QuestionSummary
    recommended_answer: ModelAnswer | None = None
    recommendation_message: str
    consensus: list[dict[str, Any]] = Field(default_factory=list)
    disagreements: list[dict[str, Any]] = Field(default_factory=list)
    model_comparison: list[ModelAnswer] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    constraints_check: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    behavior_versions: dict[str, Any] = Field(default_factory=dict)
    cache_key_version: str | None = None
    evidence_only: bool = False


class ErrorDetail(FlexibleResponseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(FlexibleResponseModel):
    error: ErrorDetail
    request_id: str


class FeedbackRequest(StrictRequestModel):
    report_id: UUID
    helpful: bool
    comment: str | None = Field(default=None, max_length=5_000)
    claim_id: UUID | None = None
    suggested_answer: str | None = Field(default=None, max_length=20_000)


class FeedbackResponse(FlexibleResponseModel):
    feedback_id: UUID
    report_id: UUID
    created_at: datetime
