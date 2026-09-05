from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MatchStatus(StrEnum):
    MATCH = "MATCH"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    DIVERGENCE = "DIVERGENCE"
    UNMATCHED = "UNMATCHED"
    DUPLICATE = "DUPLICATE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MatchCardinality(StrEnum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"


class DatasetSummary(BaseModel):
    dataset_id: str
    label: str
    filename: str
    rows: int
    columns: list[str]
    preview: list[dict[str, Any]]
    suggested_mapping: dict[str, str | None]


class ColumnMapping(BaseModel):
    amount: str
    date: str | None = None
    description: str | None = None
    document: str | None = None


class ReconciliationRules(BaseModel):
    amount_tolerance: float = Field(default=0.0, ge=0)
    date_tolerance_days: int = Field(default=0, ge=0, le=31)
    description_similarity: float = Field(default=0.82, ge=0, le=1)
    require_document_exact: bool = False
    auto_approve_threshold: float = Field(default=0.95, ge=0, le=1)
    probable_match_threshold: float = Field(default=0.75, ge=0, le=1)
    group_matching_enabled: bool = True
    max_group_size: int = Field(default=3, ge=2, le=5)
    group_match_threshold: float = Field(default=0.85, ge=0, le=1)
    group_candidate_limit: int = Field(default=18, ge=4, le=30)


class ReconciliationCreate(BaseModel):
    left_dataset_id: str
    right_dataset_id: str
    left_mapping: ColumnMapping
    right_mapping: ColumnMapping
    rules: ReconciliationRules = ReconciliationRules()
    template_id: str | None = None


class ReconciliationTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=240)
    left_mapping: ColumnMapping
    right_mapping: ColumnMapping
    rules: ReconciliationRules = ReconciliationRules()
    left_columns: list[str] = Field(default_factory=list)
    right_columns: list[str] = Field(default_factory=list)


class ReconciliationTemplate(ReconciliationTemplateCreate):
    template_id: str
    created_at: str
    updated_at: str


class TemplateApplyRequest(BaseModel):
    left_dataset_id: str
    right_dataset_id: str


class TemplateApplication(BaseModel):
    template: ReconciliationTemplate
    compatible: bool
    missing_left_columns: list[str] = Field(default_factory=list)
    missing_right_columns: list[str] = Field(default_factory=list)


class MatchPair(BaseModel):
    pair_id: str
    left_index: int | None = None
    right_index: int | None = None
    left_indices: list[int] = Field(default_factory=list)
    right_indices: list[int] = Field(default_factory=list)
    match_cardinality: MatchCardinality = MatchCardinality.ONE_TO_ONE
    status: MatchStatus
    confidence: float = Field(ge=0, le=1)
    amount_left: float | None = None
    amount_right: float | None = None
    amount_difference: float | None = None
    date_left: str | None = None
    date_right: str | None = None
    description_left: str | None = None
    description_right: str | None = None
    document_left: str | None = None
    document_right: str | None = None
    reasons: list[str] = Field(default_factory=list)
    left_row: dict[str, Any] | None = None
    right_row: dict[str, Any] | None = None
    left_rows: list[dict[str, Any]] = Field(default_factory=list)
    right_rows: list[dict[str, Any]] = Field(default_factory=list)


class ReconciliationSummary(BaseModel):
    reconciliation_id: str
    total_left: int
    total_right: int
    matched: int
    probable_matches: int
    divergences: int
    unmatched: int
    duplicates: int
    manual_review: int
    one_to_many: int = 0
    many_to_one: int = 0
    grouped_matches: int = 0
    reconciled_left_rows: int = 0
    reconciled_right_rows: int = 0
    match_rate: float
    total_amount_left: float
    total_amount_right: float
    net_difference: float


class ReconciliationResult(BaseModel):
    summary: ReconciliationSummary
    pairs: list[MatchPair]


class ManualDecision(BaseModel):
    decision: Literal["approve", "reject"]
