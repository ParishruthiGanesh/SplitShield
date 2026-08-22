"""Integrity Score determinism and repair-manifest rules."""
from __future__ import annotations

from app.domain import FindingKind, Split
from app.pipeline.classify import build_findings
from app.pipeline.indexing import SampleRecord
from app.pipeline.repair import build_repair_plan
from app.pipeline.scoring import compute_integrity_score


def _sample(i, split, label, corrupt=False):
    return SampleRecord(
        id=f"s{i}", split=Split(split), label=label,
        rel_path=f"{split}/{label}/{i}.png", stored_path=None, corrupt=corrupt,
    )


def _clean_inventory(n=100, test_frac=0.2, imbalance=1.0, corrupt=0):
    return {
        "total_valid_samples": n,
        "total_corrupt_samples": corrupt,
        "class_imbalance_ratio": imbalance,
        "test_fraction": test_frac,
        "per_split": {"train": int(n * (1 - test_frac)), "test": int(n * test_frac)},
        "class_count": 2,
    }


class TestIntegrityScore:
    def test_clean_dataset_scores_100(self):
        s = compute_integrity_score(_clean_inventory(), [])
        assert s.score == 100.0
        assert s.grade == "Low risk"

    def test_exact_leakage_penalised_hardest(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a"),
                   _sample(2, "train", "a"), _sample(3, "test", "a")]
        exact = build_findings(samples, [[0, 1]], [], [], 4)
        semantic = build_findings(
            samples, [], [],
            [__import__("app.pipeline.similarity", fromlist=["CandidatePair"]).CandidatePair(2, 3, 0.05, 0.95)],
            4,
        )
        inv = _clean_inventory()
        s_exact = compute_integrity_score(inv, exact)
        s_sem = compute_integrity_score(inv, semantic)
        assert s_exact.score < s_sem.score

    def test_normalised_by_dataset_size(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        small = compute_integrity_score(_clean_inventory(n=20), findings)
        large = compute_integrity_score(_clean_inventory(n=10000), findings)
        assert small.score < large.score

    def test_deterministic(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "b")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        inv = _clean_inventory(corrupt=2, imbalance=6.0)
        assert compute_integrity_score(inv, findings).to_dict() == \
               compute_integrity_score(inv, findings).to_dict()

    def test_excluding_reviewed_findings_raises_score(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        inv = _clean_inventory(n=30)
        with_f = compute_integrity_score(inv, findings)
        without = compute_integrity_score(inv, findings, {findings[0].id})
        assert without.score > with_f.score

    def test_breakdown_components_sum(self):
        inv = _clean_inventory(corrupt=5, imbalance=12.0, test_frac=0.02)
        s = compute_integrity_score(inv, [])
        assert abs(sum(c.penalty for c in s.components) - s.total_penalty) < 1e-6
        assert s.score == max(0.0, min(100.0, round(100 - s.total_penalty, 1)))


class TestRepair:
    def test_cross_split_group_consolidated_out_of_test(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a"), _sample(2, "test", "a")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        plan = build_repair_plan(samples, findings)
        moved = {e.sample_id: e for e in plan.entries}
        assert moved["s1"].proposed_split == "train"
        assert moved["s1"].action == "move"
        assert moved["s2"].action == "keep"
        assert plan.moves == 1

    def test_majority_test_group_moves_to_test(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a"), _sample(2, "test", "a")]
        findings = build_findings(samples, [[0, 1, 2]], [], [], 4)
        plan = build_repair_plan(samples, findings)
        by_id = {e.sample_id: e for e in plan.entries}
        assert by_id["s0"].proposed_split == "test"
        assert by_id["s1"].proposed_split == "test"

    def test_conflicting_label_group_excluded(self):
        samples = [_sample(0, "train", "cat"), _sample(1, "train", "dog")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        plan = build_repair_plan(samples, findings)
        assert all(e.action == "exclude" for e in plan.entries)
        assert plan.groups[0]["resolution"] == "exclude_pending_review"

    def test_safe_review_removes_group(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        plan = build_repair_plan(samples, findings, {findings[0].id: "safe"})
        assert all(e.action == "keep" for e in plan.entries)
        assert plan.moves == 0

    def test_semantic_only_included_on_optin_or_confirmation(self):
        from app.pipeline.similarity import CandidatePair

        samples = [_sample(0, "train", "a"), _sample(1, "test", "a")]
        findings = build_findings(samples, [], [], [CandidatePair(0, 1, 0.05, 0.95)], 4)
        assert findings[0].kind is FindingKind.SEMANTIC_OVERLAP

        default = build_repair_plan(samples, findings)
        assert default.moves == 0 and default.warnings  # warned, not grouped

        opted = build_repair_plan(samples, findings, include_semantic=True)
        assert opted.moves == 1

        confirmed = build_repair_plan(samples, findings, {findings[0].id: "confirmed"})
        assert confirmed.moves == 1

    def test_corrupt_samples_excluded(self):
        samples = [_sample(0, "train", "a"), _sample(1, "train", "a", corrupt=True)]
        plan = build_repair_plan(samples, [])
        by_id = {e.sample_id: e for e in plan.entries}
        assert by_id["s1"].action == "exclude"
        assert "Corrupt" in by_id["s1"].reason

    def test_originals_never_touched(self):
        samples = [_sample(0, "train", "a"), _sample(1, "test", "a")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        plan = build_repair_plan(samples, findings)
        # Manifest-only: every input sample appears exactly once, no deletions.
        assert sorted(e.sample_id for e in plan.entries) == ["s0", "s1"]
