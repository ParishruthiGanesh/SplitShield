"""Evaluation-gap experiment: eligibility, determinism, quarantine effect."""
from __future__ import annotations

import numpy as np
import pytest

from app.config import settings
from app.domain import Split
from app.pipeline.classify import build_findings
from app.pipeline.evaluation import check_eligibility, run_evaluation_gap
from app.pipeline.indexing import SampleRecord


def _sample(i, split, label, corrupt=False):
    return SampleRecord(
        id=f"s{i}", split=Split(split), label=label,
        rel_path=f"{split}/{label}/{i}.png", stored_path=None, corrupt=corrupt,
    )


def _separable_dataset(n_train=40, n_test=20, leak=6, seed=0):
    """Two linearly separable classes in embedding space + planted leakage.

    The last ``leak`` test samples are exact copies of training rows, so the
    model's memory of them is genuinely rewarded -> a real observed gap.
    """
    rng = np.random.RandomState(seed)
    samples, rows = [], []
    for i in range(n_train):
        label = "a" if i % 2 == 0 else "b"
        centre = np.array([1.0, 0.0]) if label == "a" else np.array([0.0, 1.0])
        vec = centre + rng.normal(0, 0.45, 2)
        samples.append(_sample(len(samples), "train", label))
        rows.append(vec)
    leak_sources = list(range(leak))
    for i in range(n_test):
        if i < leak:
            src = leak_sources[i]
            samples.append(_sample(len(samples), "test", samples[src].label))
            rows.append(rows[src])  # identical embedding == exact duplicate
        else:
            label = "a" if i % 2 == 0 else "b"
            centre = np.array([1.0, 0.0]) if label == "a" else np.array([0.0, 1.0])
            samples.append(_sample(len(samples), "test", label))
            rows.append(centre + rng.normal(0, 0.45, 2))
    matrix = np.array(rows, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    exact_groups = [[src, n_train + i] for i, src in enumerate(leak_sources)]
    findings = build_findings(samples, exact_groups, [], [], 4)
    return samples, matrix, findings


class TestEligibility:
    def test_requires_test_split(self):
        samples = [_sample(i, "train", "a") for i in range(10)]
        assert not check_eligibility(samples).eligible

    def test_requires_two_shared_classes(self):
        samples = [_sample(i, "train", "a") for i in range(10)] + [
            _sample(10 + i, "test", "b") for i in range(10)
        ]
        elig = check_eligibility(samples)
        assert not elig.eligible
        assert "classes" in elig.reason

    def test_requires_min_train_per_class(self):
        samples = (
            [_sample(i, "train", "a") for i in range(3)]
            + [_sample(3 + i, "train", "b") for i in range(8)]
            + [_sample(20 + i, "test", "a") for i in range(6)]
            + [_sample(30 + i, "test", "b") for i in range(6)]
        )
        elig = check_eligibility(samples)
        assert not elig.eligible and "fewer than" in elig.reason

    def test_ineligible_returns_reason_not_metrics(self):
        samples = [_sample(i, "train", "a") for i in range(10)]
        result = run_evaluation_gap(samples, np.zeros((10, 4), dtype=np.float32), [])
        assert result["eligible"] is False
        assert "original" not in result


class TestExperiment:
    def test_deterministic_across_runs(self):
        samples, emb, findings = _separable_dataset()
        r1 = run_evaluation_gap(samples, emb, findings)
        r2 = run_evaluation_gap(samples, emb, findings)
        assert r1 == r2

    def test_leakage_quarantined_and_gap_reported(self):
        samples, emb, findings = _separable_dataset(leak=6)
        result = run_evaluation_gap(samples, emb, findings)
        assert result["eligible"]
        assert result["quarantined_test_samples"] == 6
        assert result["cleaned"]["test_samples"] == result["original"]["test_samples"] - 6
        assert result["observed_evaluation_gap"] is not None
        # Leaked test rows are identical to train rows -> original acc should
        # not be lower than cleaned on this construction.
        assert result["observed_evaluation_gap"] >= 0
        assert result["original"]["accuracy_ci95"] is not None
        assert result["warnings"]

    def test_no_leakage_no_gap(self):
        samples, emb, findings = _separable_dataset(leak=0)
        result = run_evaluation_gap(samples, emb, [])
        assert result["quarantined_test_samples"] == 0
        assert result["observed_evaluation_gap"] is None
        assert result["cleaned"] is None

    def test_safe_review_prevents_quarantine(self):
        samples, emb, findings = _separable_dataset(leak=2)
        reviews = {f.id: "safe" for f in findings}
        result = run_evaluation_gap(samples, emb, findings, reviews)
        assert result["quarantined_test_samples"] == 0

    def test_seed_recorded(self):
        samples, emb, findings = _separable_dataset()
        result = run_evaluation_gap(samples, emb, findings)
        assert result["seed"] == settings.random_seed
