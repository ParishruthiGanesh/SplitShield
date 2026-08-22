"""Core domain vocabulary: severities, finding kinds, review decisions.

Kept dependency-free so the pipeline and API share exactly one definition.
"""
from __future__ import annotations

from enum import StrEnum


class Split(StrEnum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


class FindingKind(StrEnum):
    """Leakage / integrity classifications produced by the pipeline."""

    EXACT_CROSS_SPLIT = "exact_cross_split_leakage"
    NEAR_CROSS_SPLIT = "near_duplicate_cross_split_leakage"
    SEMANTIC_OVERLAP = "possible_semantic_overlap"
    CONFLICTING_LABEL = "conflicting_label_duplicate"
    SAME_SPLIT_REDUNDANCY = "same_split_redundancy"
    CORRUPT_SAMPLE = "corrupt_sample"
    CLASS_IMBALANCE = "class_imbalance"
    SPLIT_IMBALANCE = "split_imbalance"


PAIR_KINDS = {
    FindingKind.EXACT_CROSS_SPLIT,
    FindingKind.NEAR_CROSS_SPLIT,
    FindingKind.SEMANTIC_OVERLAP,
    FindingKind.CONFLICTING_LABEL,
    FindingKind.SAME_SPLIT_REDUNDANCY,
}


class ConfidenceLabel(StrEnum):
    """Deliberately cautious language shown to users.

    The pipeline never calls an embedding match a "duplicate"; only a
    byte-identical SHA-256 match earns `CONFIRMED_EXACT`.
    """

    CONFIRMED_EXACT = "Confirmed exact duplicate"
    LIKELY_NEAR = "Likely near duplicate"
    POSSIBLE_SEMANTIC = "Possible semantic overlap"
    REQUIRES_REVIEW = "Requires human review"


class Method(StrEnum):
    SHA256 = "sha256"
    PHASH = "phash"
    EMBEDDING = "embedding"


class ReviewDecision(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    SAFE = "safe"
    UNCERTAIN = "uncertain"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


class Stage(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    INDEXING = "indexing"
    EXACT = "exact_duplicate_analysis"
    NEAR = "near_duplicate_analysis"
    SEMANTIC = "semantic_analysis"
    SCORING = "scoring"
    EVALUATION = "evaluation_experiment"
    REPORT = "report_generation"
    COMPLETE = "complete"


STAGE_ORDER: list[Stage] = [
    Stage.QUEUED,
    Stage.VALIDATING,
    Stage.INDEXING,
    Stage.EXACT,
    Stage.NEAR,
    Stage.SEMANTIC,
    Stage.SCORING,
    Stage.EVALUATION,
    Stage.REPORT,
    Stage.COMPLETE,
]

STAGE_LABELS = {
    Stage.QUEUED: "Queued",
    Stage.VALIDATING: "Validating",
    Stage.INDEXING: "Indexing",
    Stage.EXACT: "Exact duplicate analysis",
    Stage.NEAR: "Near-duplicate analysis",
    Stage.SEMANTIC: "Semantic analysis",
    Stage.SCORING: "Scoring",
    Stage.EVALUATION: "Evaluation experiment",
    Stage.REPORT: "Report generation",
    Stage.COMPLETE: "Complete",
}
