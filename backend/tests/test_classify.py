"""Label-conflict semantics, including unlabeled (detection-style) datasets."""
from app.domain import FindingKind, Split
from app.pipeline.classify import build_findings, labels_conflict
from app.pipeline.indexing import SampleRecord
from app.pipeline.ingest import UNLABELED


def _sample(i, split, label, sha=None, ph=None):
    return SampleRecord(
        id=f"s{i}", split=Split(split), label=label,
        rel_path=f"{split}/{label}/{i}.png", stored_path=None, sha256=sha, phash=ph,
    )


class TestUnlabeledDatasets:
    """Detection-style layouts (images directly in split folders) must work
    without producing label-based findings."""

    def test_unlabeled_never_conflicts(self):
        a = _sample(0, "train", UNLABELED)
        b = _sample(1, "test", UNLABELED)
        c = _sample(2, "test", "cat")
        d = _sample(3, "test", "dog")
        assert labels_conflict(a, b) is False
        assert labels_conflict(a, c) is False  # one side unlabeled -> no conflict
        assert labels_conflict(c, d) is True

    def test_exact_cross_split_still_detected_when_unlabeled(self):
        samples = [
            _sample(0, "train", UNLABELED, sha="x"),
            _sample(1, "test", UNLABELED, sha="x"),
        ]
        findings = build_findings(samples, [[0, 1]], [], [], phash_strong_threshold=4)
        assert len(findings) == 1
        assert findings[0].kind is FindingKind.EXACT_CROSS_SPLIT
        assert findings[0].conflicting_label is False

    def test_labeled_conflict_still_fires(self):
        samples = [
            _sample(0, "train", "cat", sha="y"),
            _sample(1, "train", "dog", sha="y"),
        ]
        findings = build_findings(samples, [[0, 1]], [], [], phash_strong_threshold=4)
        assert findings[0].kind is FindingKind.CONFLICTING_LABEL
