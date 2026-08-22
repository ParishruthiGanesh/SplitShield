"""End-to-end: the demo dataset's planted defects must be recovered by the
real pipeline, verified against the generated ground-truth manifest.

Evidence strength ordering lets a finding count as recovered when it was
detected with the *expected or stronger* evidence (e.g. a planted "semantic"
crop that pHash happens to catch is a stronger result, not a failure).
"""
from __future__ import annotations

import numpy as np
import pytest

from app.demo.generate import generate_demo_dataset
from app.pipeline.classify import build_findings
from app.pipeline.embeddings import get_provider
from app.pipeline.indexing import index_sample
from app.pipeline.ingest import collect_directory
from app.pipeline.similarity import embedding_candidates, group_exact, perceptual_candidates

# Stronger-or-equal lattice for expected finding kinds.
_STRENGTH = {
    "possible_semantic_overlap": 0,
    "near_duplicate_cross_split_leakage": 1,
    "exact_cross_split_leakage": 2,
    "conflicting_label_duplicate": 2,
}


@pytest.fixture(scope="module")
def pipeline_result(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo") / "dataset"
    manifest = generate_demo_dataset(root)
    extract = collect_directory(root)
    samples = [index_sample(f) for f in extract.files]

    exact = group_exact([s.sha256 if not s.corrupt else None for s in samples])
    phash = perceptual_candidates([s.phash for s in samples], threshold=8)
    provider, _ = get_provider("classical")
    emb = provider.embed_paths([s.stored_path for s in samples])
    mask = np.array([not s.corrupt for s in samples])
    emb_pairs = embedding_candidates(emb, mask, threshold=0.90, top_k=10)
    findings = build_findings(samples, exact, phash, emb_pairs, phash_strong_threshold=4)
    return manifest, samples, findings


class TestGroundTruthRecovery:
    def test_all_planted_pairs_recovered(self, pipeline_result):
        manifest, samples, findings = pipeline_result
        pair_by_paths = {
            frozenset((samples[f.a_idx].rel_path, samples[f.b_idx].rel_path)): f
            for f in findings
        }
        missed, weaker = [], []
        for issue in manifest["planted_issues"]:
            if len(issue["files"]) != 2:
                continue
            found = pair_by_paths.get(frozenset(issue["files"]))
            if found is None:
                missed.append(issue["issue_type"])
                continue
            expected = _STRENGTH[issue["expected_finding_kind"]]
            actual = _STRENGTH.get(found.kind.value, -1)
            if actual < expected:
                weaker.append((issue["issue_type"], found.kind.value))
        assert not missed, f"Planted pairs not detected at all: {missed}"
        assert not weaker, f"Detected with weaker evidence than expected: {weaker}"

    def test_exact_duplicates_all_sha256(self, pipeline_result):
        manifest, samples, findings = pipeline_result
        exact_planted = [
            i for i in manifest["planted_issues"] if i["issue_type"] == "exact_cross_split"
        ]
        exact_found = [f for f in findings if f.kind.value == "exact_cross_split_leakage"]
        assert len(exact_found) >= len(exact_planted)
        assert all(f.method.value == "sha256" and f.similarity == 1.0 for f in exact_found)

    def test_conflicting_label_found(self, pipeline_result):
        manifest, samples, findings = pipeline_result
        conflicts = [f for f in findings if f.kind.value == "conflicting_label_duplicate"]
        assert len(conflicts) == 1
        paths = {samples[conflicts[0].a_idx].rel_path, samples[conflicts[0].b_idx].rel_path}
        planted = next(
            i for i in manifest["planted_issues"] if i["issue_type"] == "conflicting_label"
        )
        assert paths == set(planted["files"])

    def test_corrupt_file_isolated_not_fatal(self, pipeline_result):
        manifest, samples, _ = pipeline_result
        corrupt = [s for s in samples if s.corrupt]
        planted = next(
            i for i in manifest["planted_issues"] if i["issue_type"] == "corrupt_file"
        )
        assert len(corrupt) == 1
        assert corrupt[0].rel_path == planted["files"][0]

    def test_false_positive_rate_bounded(self, pipeline_result):
        """Cross-split evidence must not drown the planted signal in noise."""
        manifest, samples, findings = pipeline_result
        planted_pairs = {
            frozenset(i["files"]) for i in manifest["planted_issues"] if len(i["files"]) == 2
        }
        strong_cross = [
            f
            for f in findings
            if f.cross_split
            and f.kind.value in ("exact_cross_split_leakage", "near_duplicate_cross_split_leakage")
        ]
        unplanted = [
            f
            for f in strong_cross
            if frozenset((samples[f.a_idx].rel_path, samples[f.b_idx].rel_path))
            not in planted_pairs
        ]
        # Organic near-collisions are possible with synthetic renderers, but
        # they must stay a small minority of strong cross-split evidence.
        assert len(unplanted) <= len(strong_cross) / 2

    def test_demo_not_trivially_all_duplicates(self, pipeline_result):
        manifest, samples, findings = pipeline_result
        involved = {f.a_idx for f in findings} | {f.b_idx for f in findings}
        assert len(involved) < len(samples) * 0.5, (
            "More than half the demo dataset is flagged; demo is too dirty to be credible."
        )

    def test_deterministic_generation(self, tmp_path):
        m1 = generate_demo_dataset(tmp_path / "a")
        m2 = generate_demo_dataset(tmp_path / "b")
        assert m1["planted_issues"] == m2["planted_issues"]
        # Byte-identical corpora.
        import hashlib

        def tree_hash(root):
            h = hashlib.sha256()
            for p in sorted((tmp_path / root).rglob("*")):
                if p.is_file():
                    h.update(p.relative_to(tmp_path / root).as_posix().encode())
                    h.update(p.read_bytes())
            return h.hexdigest()

        assert tree_hash("a") == tree_hash("b")
