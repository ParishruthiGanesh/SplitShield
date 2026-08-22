"""Pydantic request/response models for the public API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditConfigIn(BaseModel):
    """Advanced-settings overrides accepted at job creation."""

    enable_exact: bool = True
    enable_perceptual: bool = True
    enable_semantic: bool = True
    phash_threshold: int | None = Field(default=None, ge=0, le=24)
    phash_strong_threshold: int | None = Field(default=None, ge=0, le=24)
    semantic_threshold: float | None = Field(default=None, ge=0.5, le=0.9999)
    semantic_top_k: int | None = Field(default=None, ge=1, le=50)
    run_evaluation: bool = True


class JobCreated(BaseModel):
    job_id: str
    status: str


class JobStatusOut(BaseModel):
    job_id: str
    status: str
    stage: str
    stage_label: str
    stages: list[dict[str, Any]]
    progress: float
    message: str | None = None
    error: str | None = None
    source: str
    dataset_name: str | None = None
    created_at: str
    expires_at: str


class ReviewIn(BaseModel):
    decision: Literal["confirmed", "safe", "uncertain", "unreviewed"]
    note: str | None = Field(default=None, max_length=2000)


class RepairOptionsIn(BaseModel):
    include_semantic: bool = False


class ErrorOut(BaseModel):
    detail: str
