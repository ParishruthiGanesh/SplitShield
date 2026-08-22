"""Split-repair proposal generation.

Principles (enforced, not aspirational):

* Original files are never modified or deleted - the output is a *manifest*.
* All members of one duplicate group end up in a single split.
* The test set's integrity is protected first: a group spanning train and
  test is consolidated *out* of test into train (evaluating on leaked
  samples is worse than losing a little training data), unless the group is
  majority-test, in which case it moves to test and out of train.
* Conflicting-label groups cannot be auto-repaired (the correct label is
  unknowable from pixels) - they are proposed for exclusion pending review.
* Corrupt samples are proposed for exclusion.
* Every action carries a human-readable reason.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from ..domain import FindingKind, ReviewDecision
from .classify import PairFinding
from .indexing import SampleRecord
from .similarity import UnionFind


@dataclass
class RepairEntry:
    sample_id: str
    rel_path: str
    original_split: str
    proposed_split: str
    label: str
    group_id: str | None
    action: str  # keep | move | exclude
    reason: str


@dataclass
class RepairPlan:
    entries: list[RepairEntry]
    groups: list[dict]
    moves: int
    exclusions: int
    before_counts: dict
    after_counts: dict
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "entries": [asdict(e) for e in self.entries],
            "groups": self.groups,
            "moves": self.moves,
            "exclusions": self.exclusions,
            "before_counts": self.before_counts,
            "after_counts": self.after_counts,
            "warnings": self.warnings,
        }


# Which finding kinds bind two samples into one "must stay together" group.
_GROUPING_KINDS = {
    FindingKind.EXACT_CROSS_SPLIT,
    FindingKind.NEAR_CROSS_SPLIT,
    FindingKind.CONFLICTING_LABEL,
    FindingKind.SAME_SPLIT_REDUNDANCY,
}


def build_repair_plan(
    samples: list[SampleRecord],
    findings: list[PairFinding],
    reviews: dict[str, str] | None = None,
    include_semantic: bool = False,
) -> RepairPlan:
    """Produce a repair manifest from findings plus optional human decisions.

    ``reviews`` maps finding id -> ReviewDecision value. Findings marked
    ``safe`` are ignored for grouping. Semantic-overlap findings participate
    only when ``include_semantic`` is True *or* a human confirmed them.
    """
    reviews = reviews or {}
    n = len(samples)
    uf = UnionFind(n)
    warnings: list[str] = []

    for f in findings:
        decision = reviews.get(f.id, ReviewDecision.UNREVIEWED.value)
        if decision == ReviewDecision.SAFE.value:
            continue
        if f.kind in _GROUPING_KINDS:
            uf.union(f.a_idx, f.b_idx)
        elif f.kind is FindingKind.SEMANTIC_OVERLAP:
            if include_semantic or decision == ReviewDecision.CONFIRMED.value:
                uf.union(f.a_idx, f.b_idx)

    raw_groups = uf.groups()

    # Track which groups contain a conflicting-label pair that is not resolved.
    conflicted_roots: set[int] = set()
    for f in findings:
        if f.kind is FindingKind.CONFLICTING_LABEL and reviews.get(f.id) != ReviewDecision.SAFE.value:
            root = uf.find(f.a_idx)
            if root in raw_groups:
                conflicted_roots.add(root)

    proposed: dict[int, tuple[str, str, str | None]] = {}  # idx -> (split, action, group)
    groups_meta: list[dict] = []

    for gnum, (root, members) in enumerate(sorted(raw_groups.items())):
        gid = f"g{gnum:04d}"
        member_samples = [samples[i] for i in members]
        split_counts = Counter(s.split.value for s in member_samples)
        labels = {s.label for s in member_samples}

        if root in conflicted_roots:
            # Correct label unknown -> propose exclusion, demand human review.
            for i in members:
                proposed[i] = (
                    "excluded",
                    "exclude",
                    gid,
                )
            groups_meta.append(
                {
                    "group_id": gid,
                    "members": [samples[i].id for i in members],
                    "splits": dict(split_counts),
                    "labels": sorted(labels),
                    "resolution": "exclude_pending_review",
                    "reason": (
                        "Group contains the same image under conflicting labels; the "
                        "correct label cannot be inferred automatically."
                    ),
                }
            )
            continue

        # Choose the target split. Protect test: if the group has any train
        # presence, consolidate into train unless it is majority-test.
        if len(split_counts) == 1:
            target = next(iter(split_counts))
            resolution = "already_single_split"
            reason = "All group members share one split; deduplication is optional."
        else:
            test_count = split_counts.get("test", 0)
            non_test = sum(v for k, v in split_counts.items() if k != "test")
            if test_count > non_test:
                target = "test"
                reason = (
                    "Group is majority-test; moving the minority out of train/val "
                    "sacrifices less data than rebuilding the test set."
                )
            else:
                target = "train" if split_counts.get("train") else next(iter(split_counts))
                reason = (
                    "Cross-split duplicate group consolidated into train to keep the "
                    "test set free of samples the model may have memorised."
                )
            resolution = f"consolidate_to_{target}"

        for i in members:
            current = samples[i].split.value
            if current == target:
                proposed[i] = (target, "keep", gid)
            else:
                proposed[i] = (target, "move", gid)

        groups_meta.append(
            {
                "group_id": gid,
                "members": [samples[i].id for i in members],
                "splits": dict(split_counts),
                "labels": sorted(labels),
                "resolution": resolution,
                "reason": reason,
            }
        )

    # Corrupt samples are excluded.
    entries: list[RepairEntry] = []
    for i, s in enumerate(samples):
        if s.corrupt:
            entries.append(
                RepairEntry(
                    sample_id=s.id,
                    rel_path=s.rel_path,
                    original_split=s.split.value,
                    proposed_split="excluded",
                    label=s.label,
                    group_id=None,
                    action="exclude",
                    reason=f"Corrupt or unreadable image ({s.error or 'decode failure'}).",
                )
            )
            continue

        if i in proposed:
            target, action, gid = proposed[i]
            if action == "exclude":
                reason = "Member of a conflicting-label duplicate group; label is ambiguous."
            elif action == "move":
                reason = next(
                    g["reason"] for g in groups_meta if g["group_id"] == gid
                )
            else:
                reason = "Duplicate-group member already in the target split."
            entries.append(
                RepairEntry(
                    sample_id=s.id,
                    rel_path=s.rel_path,
                    original_split=s.split.value,
                    proposed_split=target,
                    label=s.label,
                    group_id=gid,
                    action=action,
                    reason=reason,
                )
            )
        else:
            entries.append(
                RepairEntry(
                    sample_id=s.id,
                    rel_path=s.rel_path,
                    original_split=s.split.value,
                    proposed_split=s.split.value,
                    label=s.label,
                    group_id=None,
                    action="keep",
                    reason="No duplicate relationship detected.",
                )
            )

    before = Counter(s.split.value for s in samples)
    after = Counter(e.proposed_split for e in entries if e.proposed_split != "excluded")

    # Class-balance warning if a class lost a large share of its test samples.
    test_before: Counter = Counter(s.label for s in samples if s.split.value == "test")
    test_after: Counter = Counter(
        e.label for e in entries if e.proposed_split == "test"
    )
    for cls, count_before in test_before.items():
        count_after = test_after.get(cls, 0)
        if count_before >= 3 and count_after < count_before * 0.5:
            warnings.append(
                f"Class '{cls}' would lose {count_before - count_after} of "
                f"{count_before} test samples; consider sourcing fresh test data."
            )

    uncertain = sum(
        1
        for f in findings
        if f.kind is FindingKind.SEMANTIC_OVERLAP
        and reviews.get(f.id, "unreviewed") == "unreviewed"
    )
    if uncertain and not include_semantic:
        warnings.append(
            f"{uncertain} unreviewed possible-overlap finding(s) were NOT grouped. "
            "Enable 'include uncertain matches' or review them to include."
        )

    moves = sum(1 for e in entries if e.action == "move")
    exclusions = sum(1 for e in entries if e.action == "exclude")
    return RepairPlan(
        entries=entries,
        groups=groups_meta,
        moves=moves,
        exclusions=exclusions,
        before_counts=dict(before),
        after_counts=dict(after),
        warnings=warnings,
    )
