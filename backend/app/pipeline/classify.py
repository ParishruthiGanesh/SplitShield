"""Turn candidate pairs into classified, severity-ranked findings.

Evidence precedence is strict: SHA-256 > pHash > embedding. A pair discovered
by several methods keeps the strongest evidence as its primary classification
and records the weaker corroborating methods in ``detail``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ..domain import ConfidenceLabel, FindingKind, Method, Severity
from .indexing import SampleRecord
from .similarity import CandidatePair


@dataclass
class PairFinding:
    """A classified relationship between two samples."""

    id: str
    kind: FindingKind
    severity: Severity
    confidence_label: ConfidenceLabel
    method: Method
    a_idx: int
    b_idx: int
    distance: float
    similarity: float
    cross_split: bool
    conflicting_label: bool
    detail: dict = field(default_factory=dict)


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _classify_one(
    a: SampleRecord,
    b: SampleRecord,
    method: Method,
    strong: bool,
) -> tuple[FindingKind, Severity, ConfidenceLabel]:
    """Decide kind/severity/wording for one pair.

    ``strong`` means the evidence is strong enough to call the pair a probable
    duplicate rather than merely similar (exact match, or a pHash distance at
    or below the strong threshold).
    """
    cross_split = a.split != b.split
    conflicting = a.label != b.label

    if method is Method.SHA256:
        confidence = ConfidenceLabel.CONFIRMED_EXACT
    elif method is Method.PHASH:
        confidence = ConfidenceLabel.LIKELY_NEAR if strong else ConfidenceLabel.REQUIRES_REVIEW
    else:
        confidence = ConfidenceLabel.POSSIBLE_SEMANTIC

    # Conflicting labels on a probable duplicate are the most damaging finding:
    # the same image teaches the model two different answers.
    if conflicting and strong:
        severity = Severity.CRITICAL if method is Method.SHA256 else Severity.HIGH
        return FindingKind.CONFLICTING_LABEL, severity, confidence

    if cross_split:
        if method is Method.SHA256:
            return FindingKind.EXACT_CROSS_SPLIT, Severity.CRITICAL, confidence
        if method is Method.PHASH:
            return (
                FindingKind.NEAR_CROSS_SPLIT,
                Severity.HIGH if strong else Severity.MEDIUM,
                confidence,
            )
        return FindingKind.SEMANTIC_OVERLAP, Severity.MEDIUM, confidence

    # Same split: redundancy rather than leakage.
    if method is Method.EMBEDDING:
        return FindingKind.SEMANTIC_OVERLAP, Severity.LOW, confidence
    return FindingKind.SAME_SPLIT_REDUNDANCY, Severity.LOW, confidence


def build_findings(
    samples: list[SampleRecord],
    exact_groups: list[list[int]],
    phash_pairs: Iterable[CandidatePair],
    embedding_pairs: Iterable[CandidatePair],
    phash_strong_threshold: int,
) -> list[PairFinding]:
    """Merge all three evidence sources into one deduplicated finding list."""
    best: dict[tuple[int, int], PairFinding] = {}
    corroboration: dict[tuple[int, int], set[str]] = {}

    def record(
        a_idx: int,
        b_idx: int,
        method: Method,
        distance: float,
        similarity: float,
        strong: bool,
    ) -> None:
        key = _pair_key(a_idx, b_idx)
        corroboration.setdefault(key, set()).add(method.value)

        # Strict precedence: never let weaker evidence overwrite stronger.
        existing = best.get(key)
        precedence = {Method.SHA256: 3, Method.PHASH: 2, Method.EMBEDDING: 1}
        if existing is not None and precedence[Method(existing.method)] >= precedence[method]:
            return

        a, b = samples[key[0]], samples[key[1]]
        kind, severity, confidence = _classify_one(a, b, method, strong)
        best[key] = PairFinding(
            id=f"f_{key[0]}_{key[1]}",
            kind=kind,
            severity=severity,
            confidence_label=confidence,
            method=method,
            a_idx=key[0],
            b_idx=key[1],
            distance=distance,
            similarity=similarity,
            cross_split=a.split != b.split,
            conflicting_label=a.label != b.label,
        )

    # 1. Exact duplicates - every pair within each digest group.
    for group in exact_groups:
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                record(group[i], group[j], Method.SHA256, 0.0, 1.0, strong=True)

    # 2. Perceptual near-duplicates.
    for pair in phash_pairs:
        record(
            pair.a_idx,
            pair.b_idx,
            Method.PHASH,
            pair.distance,
            pair.similarity,
            strong=pair.distance <= phash_strong_threshold,
        )

    # 3. Embedding similarity - never counts as "strong" on its own.
    for pair in embedding_pairs:
        record(pair.a_idx, pair.b_idx, Method.EMBEDDING, pair.distance, pair.similarity, strong=False)

    for key, finding in best.items():
        methods = sorted(corroboration.get(key, set()))
        finding.detail = {
            "methods": methods,
            "corroborated_by_multiple_methods": len(methods) > 1,
        }
    return sorted(
        best.values(),
        key=lambda f: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[f.severity.value],
            -f.similarity,
        ),
    )
