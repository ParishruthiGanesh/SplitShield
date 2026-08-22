"""Exact/perceptual detection, cross-split grouping, conflicting labels."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.domain import ConfidenceLabel, FindingKind, Method, Severity, Split
from app.pipeline.classify import build_findings
from app.pipeline.indexing import (
    SampleRecord,
    compute_phash,
    hamming_distance,
    index_sample,
    phash_similarity,
)
from app.pipeline.ingest import ExtractedFile
from app.pipeline.similarity import (
    UnionFind,
    group_exact,
    perceptual_candidates,
)


def _sample(i, split, label, sha=None, ph=None):
    return SampleRecord(
        id=f"s{i}", split=Split(split), label=label, rel_path=f"{split}/{label}/{i}.png",
        stored_path=None, sha256=sha, phash=ph,
    )


class TestExact:
    def test_sha_grouping(self):
        groups = group_exact(["aa", "bb", "aa", None, "bb", "bb"])
        assert sorted(map(tuple, groups)) == [(0, 2), (1, 4, 5)]

    def test_index_sample_computes_sha_and_phash(self, tmp_path, make_image):
        p = tmp_path / "img.png"
        make_image(3).save(p)
        item = ExtractedFile("s1", p, "train/a/img.png", Split.TRAIN, "a", p.stat().st_size)
        rec = index_sample(item)
        assert rec.sha256 and len(rec.sha256) == 64
        assert rec.phash and not rec.corrupt
        assert rec.width == rec.height == 96

    def test_corrupt_image_marked_not_crashing(self, tmp_path, make_image):
        p = tmp_path / "broken.jpg"
        buf = io.BytesIO()
        make_image(1).save(buf, format="JPEG")
        p.write_bytes(buf.getvalue()[: len(buf.getvalue()) // 3])
        item = ExtractedFile("s1", p, "train/a/broken.jpg", Split.TRAIN, "a", 1)
        rec = index_sample(item)
        assert rec.corrupt and rec.error
        assert rec.sha256  # digest still computed from bytes


class TestPerceptual:
    def test_identical_images_distance_zero(self, make_image):
        img = make_image(5)
        assert hamming_distance(compute_phash(img), compute_phash(img.copy())) == 0

    def test_recompression_within_threshold(self, make_image, tmp_path):
        img = make_image(6)
        p1, p2 = tmp_path / "a.png", tmp_path / "b.jpg"
        img.save(p1)
        img.save(p2, quality=40)
        with Image.open(p1) as a, Image.open(p2) as b:
            d = hamming_distance(compute_phash(a.convert("RGB")), compute_phash(b.convert("RGB")))
        assert d <= 8

    def test_unrelated_images_far_apart(self, make_image):
        d = hamming_distance(compute_phash(make_image(1)), compute_phash(make_image(2)))
        assert d > 8

    def test_candidates_exhaustive_and_deduped(self):
        hashes = ["00" * 8, "01" + "00" * 7, "ff" * 8, None]
        pairs = perceptual_candidates(hashes, threshold=2)
        assert [(p.a_idx, p.b_idx) for p in pairs] == [(0, 1)]
        assert pairs[0].distance == 1
        assert pairs[0].similarity == phash_similarity(1, 64)


class TestClassification:
    def test_exact_cross_split_is_critical(self):
        samples = [_sample(0, "train", "cat"), _sample(1, "test", "cat")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        f = findings[0]
        assert f.kind is FindingKind.EXACT_CROSS_SPLIT
        assert f.severity is Severity.CRITICAL
        assert f.confidence_label is ConfidenceLabel.CONFIRMED_EXACT
        assert f.cross_split and not f.conflicting_label

    def test_conflicting_label_beats_cross_split(self):
        samples = [_sample(0, "train", "cat"), _sample(1, "test", "dog")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        assert findings[0].kind is FindingKind.CONFLICTING_LABEL
        assert findings[0].severity is Severity.CRITICAL

    def test_same_split_duplicate_is_low(self):
        samples = [_sample(0, "train", "cat"), _sample(1, "train", "cat")]
        findings = build_findings(samples, [[0, 1]], [], [], 4)
        assert findings[0].kind is FindingKind.SAME_SPLIT_REDUNDANCY
        assert findings[0].severity is Severity.LOW

    def test_stronger_method_wins(self):
        from app.pipeline.similarity import CandidatePair

        samples = [_sample(0, "train", "cat"), _sample(1, "test", "cat")]
        findings = build_findings(
            samples,
            [[0, 1]],
            [CandidatePair(0, 1, 2.0, 0.96)],
            [CandidatePair(0, 1, 0.01, 0.99)],
            4,
        )
        assert len(findings) == 1
        assert findings[0].method is Method.SHA256
        assert findings[0].detail["methods"] == ["embedding", "phash", "sha256"]

    def test_weak_phash_requires_review(self):
        from app.pipeline.similarity import CandidatePair

        samples = [_sample(0, "train", "cat"), _sample(1, "test", "cat")]
        findings = build_findings(samples, [], [CandidatePair(0, 1, 7.0, 0.89)], [], 4)
        assert findings[0].confidence_label is ConfidenceLabel.REQUIRES_REVIEW
        assert findings[0].severity is Severity.MEDIUM


class TestUnionFind:
    def test_transitive_groups(self):
        uf = UnionFind(6)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(4, 5)
        groups = sorted(sorted(v) for v in uf.groups().values())
        assert groups == [[0, 1, 2], [4, 5]]
