"""Dataset inventory statistics and the Dataset Integrity Score.

The score is a deterministic, fully documented weighted rule system. No model
or LLM is involved. Every component is reported with its inputs so a reader
can recompute it by hand from the report.

Formula
-------
For each pair-based category *c*::

    affected(c) = number of DISTINCT samples appearing in any finding of c
    rate(c)     = affected(c) / total_valid_samples
    penalty(c)  = weight(c) * min(1, rate(c) / saturation(c))

``saturation`` is the affected-sample rate at which a category incurs its full
weight. Dividing by ``total_valid_samples`` is what makes the score fair across
dataset sizes: ten leaked images in a 100-image dataset is a far worse problem
than ten in a 100,000-image dataset, and the rate captures that.

Imbalance categories use their own bounded ramps (see below) because they are
properties of the distribution, not counts of affected samples.

    integrity_score = clamp(100 - sum(penalty(c)), 0, 100)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from statistics import median

from ..domain import FindingKind, Severity
from .classify import PairFinding
from .indexing import SampleRecord

# --- Scoring constants (documented in METHODOLOGY.md) ---------------------
WEIGHTS: dict[str, float] = {
    FindingKind.EXACT_CROSS_SPLIT.value: 35.0,
    FindingKind.CONFLICTING_LABEL.value: 25.0,
    FindingKind.NEAR_CROSS_SPLIT.value: 20.0,
    FindingKind.SEMANTIC_OVERLAP.value: 8.0,
    FindingKind.CORRUPT_SAMPLE.value: 6.0,
    FindingKind.SAME_SPLIT_REDUNDANCY.value: 5.0,
    FindingKind.CLASS_IMBALANCE.value: 3.0,
    FindingKind.SPLIT_IMBALANCE.value: 3.0,
}

SATURATION: dict[str, float] = {
    FindingKind.EXACT_CROSS_SPLIT.value: 0.05,
    FindingKind.CONFLICTING_LABEL.value: 0.03,
    FindingKind.NEAR_CROSS_SPLIT.value: 0.10,
    FindingKind.SEMANTIC_OVERLAP.value: 0.25,
    FindingKind.CORRUPT_SAMPLE.value: 0.10,
    FindingKind.SAME_SPLIT_REDUNDANCY.value: 0.30,
}

# Class imbalance ramp: imbalance ratio (largest class / smallest class).
CLASS_IMBALANCE_OK = 2.0
CLASS_IMBALANCE_FULL = 10.0
# Split imbalance ramp: acceptable test-split fraction band.
TEST_FRACTION_MIN = 0.05
TEST_FRACTION_IDEAL_LOW = 0.10
TEST_FRACTION_IDEAL_HIGH = 0.40


@dataclass
class ScoreComponent:
    category: str
    weight: float
    affected_samples: int
    rate: float
    saturation: float | None
    penalty: float
    explanation: str


@dataclass
class IntegrityScore:
    score: float
    grade: str
    components: list[ScoreComponent] = field(default_factory=list)
    total_penalty: float = 0.0
    total_valid_samples: int = 0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "total_penalty": self.total_penalty,
            "total_valid_samples": self.total_valid_samples,
            "components": [asdict(c) for c in self.components],
            "formula": (
                "score = clamp(100 - sum(weight_c * min(1, rate_c / saturation_c)), 0, 100) "
                "where rate_c = distinct_affected_samples_c / total_valid_samples"
            ),
        }


def _grade(score: float) -> str:
    if score >= 90:
        return "Low risk"
    if score >= 75:
        return "Moderate risk"
    if score >= 50:
        return "High risk"
    return "Severe risk"


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def pct(p: float) -> float:
        if len(ordered) == 1:
            return round(ordered[0], 4)
        pos = p * (len(ordered) - 1)
        low = int(pos)
        high = min(low + 1, len(ordered) - 1)
        frac = pos - low
        return round(ordered[low] * (1 - frac) + ordered[high] * frac, 4)

    return {
        "min": round(ordered[0], 4),
        "p25": pct(0.25),
        "median": round(median(ordered), 4),
        "p75": pct(0.75),
        "max": round(ordered[-1], 4),
    }


def build_inventory(samples: list[SampleRecord], rejected: list[dict]) -> dict:
    """Dataset inventory: counts, distributions and imbalance measures."""
    valid = [s for s in samples if not s.corrupt]
    corrupt = [s for s in samples if s.corrupt]

    per_split = Counter(s.split.value for s in valid)
    per_class: dict[str, Counter] = defaultdict(Counter)
    class_totals: Counter = Counter()
    for s in valid:
        per_class[s.split.value][s.label] += 1
        class_totals[s.label] += 1

    all_classes = sorted(class_totals)
    # A class is "missing" from a split when it appears elsewhere but not there.
    missing: list[dict] = []
    for split in sorted(per_split):
        for cls in all_classes:
            if per_class[split].get(cls, 0) == 0:
                missing.append({"split": split, "label": cls})

    counts = [class_totals[c] for c in all_classes]
    imbalance_ratio = (max(counts) / min(counts)) if counts and min(counts) > 0 else None

    total_valid = len(valid)
    test_fraction = (per_split.get("test", 0) / total_valid) if total_valid else 0.0

    return {
        "total_samples": len(samples),
        "total_valid_samples": total_valid,
        "total_corrupt_samples": len(corrupt),
        "rejected_files": rejected,
        "rejected_count": len(rejected),
        "per_split": dict(sorted(per_split.items())),
        "per_class_total": {c: class_totals[c] for c in all_classes},
        "per_split_class": {k: dict(sorted(v.items())) for k, v in sorted(per_class.items())},
        "classes": all_classes,
        "class_count": len(all_classes),
        "missing_class_in_split": missing,
        "class_imbalance_ratio": round(imbalance_ratio, 3) if imbalance_ratio else None,
        "test_fraction": round(test_fraction, 4),
        "dimensions": {
            "width": _percentiles([float(s.width) for s in valid if s.width]),
            "height": _percentiles([float(s.height) for s in valid if s.height]),
            "aspect_ratio": _percentiles(
                [s.aspect_ratio for s in valid if s.aspect_ratio is not None]
            ),
            "file_size_bytes": _percentiles([float(s.bytes) for s in valid if s.bytes]),
        },
        "formats": dict(Counter(s.img_format for s in valid if s.img_format)),
        "corrupt_samples": [
            {"id": s.id, "split": s.split.value, "label": s.label, "error": s.error}
            for s in corrupt
        ],
    }


def build_dataset_issues(inventory: dict) -> list[dict]:
    """Non-pair findings: corrupt files, class imbalance, split imbalance."""
    issues: list[dict] = []

    if inventory["total_corrupt_samples"]:
        issues.append(
            {
                "id": "issue_corrupt",
                "kind": FindingKind.CORRUPT_SAMPLE.value,
                "severity": Severity.MEDIUM.value,
                "title": f"{inventory['total_corrupt_samples']} corrupt or unreadable image(s)",
                "detail": {"samples": inventory["corrupt_samples"]},
            }
        )

    ratio = inventory.get("class_imbalance_ratio")
    if ratio and ratio > CLASS_IMBALANCE_OK:
        severity = Severity.MEDIUM if ratio >= 5 else Severity.LOW
        issues.append(
            {
                "id": "issue_class_imbalance",
                "kind": FindingKind.CLASS_IMBALANCE.value,
                "severity": severity.value,
                "title": f"Class imbalance ratio {ratio:.1f}x (largest class / smallest class)",
                "detail": {"per_class_total": inventory["per_class_total"], "ratio": ratio},
            }
        )

    frac = inventory.get("test_fraction", 0.0)
    per_split = inventory.get("per_split", {})
    if "test" not in per_split:
        issues.append(
            {
                "id": "issue_no_test_split",
                "kind": FindingKind.SPLIT_IMBALANCE.value,
                "severity": Severity.MEDIUM.value,
                "title": "No test split detected",
                "detail": {"per_split": per_split},
            }
        )
    elif frac < TEST_FRACTION_MIN or frac > TEST_FRACTION_IDEAL_HIGH:
        issues.append(
            {
                "id": "issue_split_imbalance",
                "kind": FindingKind.SPLIT_IMBALANCE.value,
                "severity": Severity.LOW.value,
                "title": f"Test split is {frac * 100:.1f}% of the dataset",
                "detail": {"per_split": per_split, "test_fraction": frac},
            }
        )

    if inventory["missing_class_in_split"]:
        issues.append(
            {
                "id": "issue_missing_classes",
                "kind": FindingKind.CLASS_IMBALANCE.value,
                "severity": Severity.LOW.value,
                "title": f"{len(inventory['missing_class_in_split'])} class/split combination(s) empty",
                "detail": {"missing": inventory["missing_class_in_split"]},
            }
        )
    return issues


def compute_integrity_score(
    inventory: dict,
    findings: list[PairFinding],
    excluded_finding_ids: set[str] | None = None,
) -> IntegrityScore:
    """Compute the transparent 0-100 Dataset Integrity Score.

    ``excluded_finding_ids`` lets the report recompute the score with findings a
    human marked "safe/expected" removed, without altering the algorithmic
    evidence stored alongside it.
    """
    excluded = excluded_finding_ids or set()
    total_valid = max(1, int(inventory.get("total_valid_samples") or 0))
    components: list[ScoreComponent] = []

    # --- Pair-based categories ---------------------------------------
    affected: dict[str, set[int]] = defaultdict(set)
    for f in findings:
        if f.id in excluded:
            continue
        affected[f.kind.value].add(f.a_idx)
        affected[f.kind.value].add(f.b_idx)

    for category in (
        FindingKind.EXACT_CROSS_SPLIT.value,
        FindingKind.CONFLICTING_LABEL.value,
        FindingKind.NEAR_CROSS_SPLIT.value,
        FindingKind.SEMANTIC_OVERLAP.value,
        FindingKind.SAME_SPLIT_REDUNDANCY.value,
    ):
        count = len(affected.get(category, set()))
        rate = count / total_valid
        sat = SATURATION[category]
        weight = WEIGHTS[category]
        penalty = weight * min(1.0, rate / sat) if count else 0.0
        components.append(
            ScoreComponent(
                category=category,
                weight=weight,
                affected_samples=count,
                rate=round(rate, 6),
                saturation=sat,
                penalty=round(penalty, 3),
                explanation=(
                    f"{count} of {total_valid} valid samples ({rate * 100:.2f}%) are involved in "
                    f"{category.replace('_', ' ')}; full weight applies at {sat * 100:.0f}%."
                ),
            )
        )

    # --- Corrupt samples ----------------------------------------------
    corrupt_count = int(inventory.get("total_corrupt_samples") or 0)
    corrupt_rate = corrupt_count / total_valid
    corrupt_sat = SATURATION[FindingKind.CORRUPT_SAMPLE.value]
    corrupt_penalty = (
        WEIGHTS[FindingKind.CORRUPT_SAMPLE.value] * min(1.0, corrupt_rate / corrupt_sat)
        if corrupt_count
        else 0.0
    )
    components.append(
        ScoreComponent(
            category=FindingKind.CORRUPT_SAMPLE.value,
            weight=WEIGHTS[FindingKind.CORRUPT_SAMPLE.value],
            affected_samples=corrupt_count,
            rate=round(corrupt_rate, 6),
            saturation=corrupt_sat,
            penalty=round(corrupt_penalty, 3),
            explanation=(
                f"{corrupt_count} unreadable file(s); full weight applies at "
                f"{corrupt_sat * 100:.0f}% of the dataset."
            ),
        )
    )

    # --- Class imbalance ----------------------------------------------
    ratio = inventory.get("class_imbalance_ratio") or 1.0
    span = CLASS_IMBALANCE_FULL - CLASS_IMBALANCE_OK
    ramp = min(1.0, max(0.0, (ratio - CLASS_IMBALANCE_OK) / span))
    class_penalty = WEIGHTS[FindingKind.CLASS_IMBALANCE.value] * ramp
    components.append(
        ScoreComponent(
            category=FindingKind.CLASS_IMBALANCE.value,
            weight=WEIGHTS[FindingKind.CLASS_IMBALANCE.value],
            affected_samples=inventory.get("class_count", 0),
            rate=round(ratio, 4),
            saturation=CLASS_IMBALANCE_FULL,
            penalty=round(class_penalty, 3),
            explanation=(
                f"Imbalance ratio {ratio:.2f}x. No penalty at or below "
                f"{CLASS_IMBALANCE_OK:.0f}x, full weight at {CLASS_IMBALANCE_FULL:.0f}x."
            ),
        )
    )

    # --- Split imbalance ------------------------------------------------
    per_split = inventory.get("per_split", {})
    frac = float(inventory.get("test_fraction") or 0.0)
    if "test" not in per_split:
        split_ramp, split_reason = 1.0, "No test split present."
    elif frac < TEST_FRACTION_MIN:
        split_ramp = 1.0
        split_reason = f"Test split is only {frac * 100:.1f}% of the dataset."
    elif frac < TEST_FRACTION_IDEAL_LOW:
        split_ramp = (TEST_FRACTION_IDEAL_LOW - frac) / (
            TEST_FRACTION_IDEAL_LOW - TEST_FRACTION_MIN
        )
        split_reason = f"Test split ({frac * 100:.1f}%) is smaller than the 10-40% comfort band."
    elif frac > TEST_FRACTION_IDEAL_HIGH:
        split_ramp = min(1.0, (frac - TEST_FRACTION_IDEAL_HIGH) / 0.3)
        split_reason = f"Test split ({frac * 100:.1f}%) is larger than the 10-40% comfort band."
    else:
        split_ramp, split_reason = 0.0, f"Test split ({frac * 100:.1f}%) is within the 10-40% band."

    split_penalty = WEIGHTS[FindingKind.SPLIT_IMBALANCE.value] * split_ramp
    components.append(
        ScoreComponent(
            category=FindingKind.SPLIT_IMBALANCE.value,
            weight=WEIGHTS[FindingKind.SPLIT_IMBALANCE.value],
            affected_samples=per_split.get("test", 0),
            rate=round(frac, 4),
            saturation=None,
            penalty=round(split_penalty, 3),
            explanation=split_reason,
        )
    )

    total_penalty = sum(c.penalty for c in components)
    score = max(0.0, min(100.0, 100.0 - total_penalty))
    return IntegrityScore(
        score=round(score, 1),
        grade=_grade(score),
        components=components,
        total_penalty=round(total_penalty, 3),
        total_valid_samples=total_valid,
    )
