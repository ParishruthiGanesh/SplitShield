"""Observed Evaluation Gap experiment.

A deliberately lightweight, fully reproducible diagnostic:

1. Embed every valid image with the active embedding provider (features are
   frozen; nothing is fine-tuned).
2. Fit multinomial logistic regression on the ORIGINAL training split.
3. Evaluate once on the ORIGINAL test split.
4. Quarantine test samples implicated in confirmed/strong cross-split leakage
   (exact SHA-256 matches and strong pHash matches by default; plus anything a
   human explicitly confirmed; minus anything a human marked safe).
5. Re-evaluate the SAME fitted model on the cleaned test subset.
6. Report both numbers, the gap, and bootstrap confidence intervals.

Interpretation guardrails are emitted with the result: the gap is evidence of
sensitivity to leakage, not proof of causation; removing samples changes the
test population; small test sets are unstable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

from ..config import settings
from ..domain import FindingKind, Method, ReviewDecision
from .classify import PairFinding
from .ingest import UNLABELED
from .indexing import SampleRecord

WARNINGS = [
    "The observed gap is evidence of sensitivity to leakage, not automatic proof of causation.",
    "Small test sets produce unstable estimates; read the confidence intervals, not the point value.",
    "Removing samples changes the test population, so the two accuracies describe different sets.",
    "Similarity thresholds require human validation; quarantine lists inherit their errors.",
    "The diagnostic baseline (frozen embeddings + logistic regression) is not a production model.",
]


@dataclass
class EvalEligibility:
    eligible: bool
    reason: str


def check_eligibility(samples: list[SampleRecord]) -> EvalEligibility:
    """Explain exactly why the experiment can or cannot run."""
    valid = [s for s in samples if not s.corrupt]
    train = [s for s in valid if s.split.value == "train"]
    test = [s for s in valid if s.split.value == "test"]

    if not train:
        return EvalEligibility(False, "No training split was found.")
    if not test:
        return EvalEligibility(False, "No test split was found.")

    train_classes = {s.label for s in train} - {UNLABELED}
    test_classes = {s.label for s in test} - {UNLABELED}
    if not train_classes and not test_classes:
        return EvalEligibility(
            False,
            "The dataset has no class labels (images sit directly in split "
            "folders), so a classification experiment cannot be trained. "
            "Leakage detection is unaffected.",
        )
    usable = train_classes & test_classes
    if len(usable) < settings.eval_min_classes:
        return EvalEligibility(
            False,
            f"Need at least {settings.eval_min_classes} classes present in both "
            f"train and test; found {len(usable)}.",
        )

    counts = {c: sum(1 for s in train if s.label == c) for c in usable}
    thin = [c for c, n in counts.items() if n < settings.eval_min_samples_per_class]
    if thin:
        return EvalEligibility(
            False,
            f"Classes with fewer than {settings.eval_min_samples_per_class} training "
            f"samples: {', '.join(sorted(thin))}.",
        )
    if len(test) < settings.eval_min_test_samples:
        return EvalEligibility(
            False,
            f"Test split has {len(test)} samples; at least "
            f"{settings.eval_min_test_samples} are required.",
        )
    return EvalEligibility(True, "Dataset is eligible for the diagnostic experiment.")


def _quarantine_test_ids(
    samples: list[SampleRecord],
    findings: list[PairFinding],
    reviews: dict[str, str],
) -> tuple[set[int], list[str]]:
    """Indices of test samples implicated in strong cross-split leakage."""
    quarantined: set[int] = set()
    reasons: list[str] = []
    for f in findings:
        decision = reviews.get(f.id, ReviewDecision.UNREVIEWED.value)
        if decision == ReviewDecision.SAFE.value:
            continue

        strong_method = f.method is Method.SHA256 or (
            f.method is Method.PHASH and f.kind is FindingKind.NEAR_CROSS_SPLIT
            and f.severity.value in ("critical", "high")
        )
        confirmed = decision == ReviewDecision.CONFIRMED.value
        if not (strong_method or confirmed):
            continue
        if not f.cross_split:
            continue

        for idx in (f.a_idx, f.b_idx):
            if samples[idx].split.value == "test" and idx not in quarantined:
                quarantined.add(idx)
                reasons.append(
                    f"{samples[idx].id}: {f.kind.value} via {f.method.value} "
                    f"(similarity {f.similarity:.3f}"
                    + (", human-confirmed)" if confirmed else ")")
                )
    return quarantined, reasons


def _bootstrap_ci(
    y_true: np.ndarray, y_pred: np.ndarray, iterations: int, seed: int
) -> dict | None:
    """Percentile-bootstrap 95% CI for accuracy."""
    n = len(y_true)
    if n < settings.eval_min_bootstrap_samples:
        return None
    rng = np.random.RandomState(seed)
    stats = np.empty(iterations)
    for i in range(iterations):
        idx = rng.randint(0, n, size=n)
        stats[i] = float(np.mean(y_true[idx] == y_pred[idx]))
    return {
        "low": round(float(np.percentile(stats, 2.5)), 4),
        "high": round(float(np.percentile(stats, 97.5)), 4),
        "iterations": iterations,
        "method": "percentile bootstrap, resampling test predictions",
    }


def run_evaluation_gap(
    samples: list[SampleRecord],
    embeddings: np.ndarray,
    findings: list[PairFinding],
    reviews: dict[str, str] | None = None,
    seed: int | None = None,
) -> dict:
    """Run the full experiment. Returns a JSON-safe result dict.

    ``embeddings`` must be row-aligned with ``samples``.
    """
    reviews = reviews or {}
    seed = settings.random_seed if seed is None else seed

    eligibility = check_eligibility(samples)
    if not eligibility.eligible:
        return {"eligible": False, "reason": eligibility.reason, "warnings": WARNINGS}

    valid_classes = sorted(
        {s.label for s in samples if not s.corrupt and s.split.value == "train"}
        & {s.label for s in samples if not s.corrupt and s.split.value == "test"}
    )
    class_to_int = {c: i for i, c in enumerate(valid_classes)}

    def rows_for(split: str) -> list[int]:
        return [
            i
            for i, s in enumerate(samples)
            if not s.corrupt and s.split.value == split and s.label in class_to_int
            and np.any(embeddings[i])
        ]

    train_rows = rows_for("train")
    test_rows = rows_for("test")
    if len(train_rows) < settings.eval_min_classes * settings.eval_min_samples_per_class:
        return {
            "eligible": False,
            "reason": "Too few embeddable training samples after filtering.",
            "warnings": WARNINGS,
        }

    x_train = embeddings[train_rows]
    y_train = np.array([class_to_int[samples[i].label] for i in train_rows])
    x_test = embeddings[test_rows]
    y_test = np.array([class_to_int[samples[i].label] for i in test_rows])

    clf = LogisticRegression(max_iter=2000, random_state=seed, C=1.0)
    clf.fit(x_train, y_train)
    pred_test = clf.predict(x_test)

    original_acc = float(accuracy_score(y_test, pred_test))
    original_f1 = float(f1_score(y_test, pred_test, average="macro", zero_division=0))
    original_ci = _bootstrap_ci(y_test, pred_test, settings.eval_bootstrap_iterations, seed)

    quarantined, reasons = _quarantine_test_ids(samples, findings, reviews)
    keep_mask = np.array([i not in quarantined for i in test_rows])
    removed = int((~keep_mask).sum())

    result: dict = {
        "eligible": True,
        "reason": eligibility.reason,
        "model": "LogisticRegression(C=1.0, max_iter=2000) on frozen embeddings",
        "classes": valid_classes,
        "seed": seed,
        "train_samples": len(train_rows),
        "original": {
            "test_samples": len(test_rows),
            "accuracy": round(original_acc, 4),
            "macro_f1": round(original_f1, 4),
            "accuracy_ci95": original_ci,
        },
        "quarantined_test_samples": removed,
        "quarantine_reasons": reasons,
        "warnings": WARNINGS,
    }

    if removed == 0:
        result["cleaned"] = None
        result["observed_evaluation_gap"] = None
        result["note"] = (
            "No test samples were implicated in strong cross-split leakage, so the "
            "cleaned evaluation is identical to the original."
        )
        return result

    if keep_mask.sum() < 2:
        result["cleaned"] = None
        result["observed_evaluation_gap"] = None
        result["note"] = (
            "Nearly the entire test split is implicated in leakage; a cleaned "
            "evaluation would be meaningless."
        )
        return result

    y_clean = y_test[keep_mask]
    pred_clean = pred_test[keep_mask]
    clean_acc = float(accuracy_score(y_clean, pred_clean))
    clean_f1 = float(f1_score(y_clean, pred_clean, average="macro", zero_division=0))
    clean_ci = _bootstrap_ci(y_clean, pred_clean, settings.eval_bootstrap_iterations, seed + 1)

    result["cleaned"] = {
        "test_samples": int(keep_mask.sum()),
        "accuracy": round(clean_acc, 4),
        "macro_f1": round(clean_f1, 4),
        "accuracy_ci95": clean_ci,
    }
    result["observed_evaluation_gap"] = round(original_acc - clean_acc, 4)
    return result
