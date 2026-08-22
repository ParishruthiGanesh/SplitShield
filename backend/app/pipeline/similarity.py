"""Candidate-pair generation for the three detection stages.

Complexity notes (documented because they bound dataset size):

* **Exact** - hash-bucket group-by on SHA-256. O(n).
* **Perceptual** - chunked pairwise Hamming distance over 64-bit pHashes using
  ``np.bitwise_count``. This is exact (no missed pairs) and vectorised; memory
  is bounded by processing ``CHUNK`` rows at a time. O(n^2) time but with a
  very small constant - roughly 4e8 comparisons/second on one core.
* **Embedding** - k-nearest-neighbour search via scikit-learn rather than an
  uncontrolled all-pairs materialisation. Only the top-k neighbours per sample
  are ever produced, bounding output to O(n*k). FAISS can be swapped in behind
  the same function signature for very large datasets.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

CHUNK = 512


@dataclass(frozen=True)
class CandidatePair:
    """An undirected candidate pair, always stored with ``a_idx < b_idx``."""

    a_idx: int
    b_idx: int
    distance: float
    similarity: float


def group_exact(digests: list[str | None]) -> list[list[int]]:
    """Group sample indices sharing an identical SHA-256 digest."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for idx, digest in enumerate(digests):
        if digest:
            buckets[digest].append(idx)
    return [sorted(idxs) for idxs in buckets.values() if len(idxs) > 1]


def _phash_to_uint64(hex_hash: str) -> int:
    return int(hex_hash, 16)


def perceptual_candidates(
    phashes: list[str | None], threshold: int, hash_bits: int = 64
) -> list[CandidatePair]:
    """All pairs whose pHash Hamming distance is <= ``threshold``.

    Exhaustive and exact; chunked to keep peak memory proportional to
    ``CHUNK * n`` rather than ``n^2``.
    """
    valid_idx = [i for i, h in enumerate(phashes) if h]
    if len(valid_idx) < 2:
        return []

    try:
        values = np.array(
            [_phash_to_uint64(phashes[i]) for i in valid_idx], dtype=np.uint64  # type: ignore[arg-type]
        )
    except ValueError:
        return []

    index = np.array(valid_idx, dtype=np.int64)
    pairs: list[CandidatePair] = []

    for start in range(0, len(values), CHUNK):
        stop = min(start + CHUNK, len(values))
        block = values[start:stop, None] ^ values[None, :]
        dist = np.bitwise_count(block).astype(np.int16)

        # Only keep the upper triangle relative to absolute position.
        rows = np.arange(start, stop)[:, None]
        cols = np.arange(len(values))[None, :]
        mask = (dist <= threshold) & (cols > rows)

        for r, c in zip(*np.nonzero(mask)):
            a_pos, b_pos = start + int(r), int(c)
            d = int(dist[r, c])
            pairs.append(
                CandidatePair(
                    a_idx=int(index[a_pos]),
                    b_idx=int(index[b_pos]),
                    distance=float(d),
                    similarity=round(max(0.0, 1.0 - d / hash_bits), 6),
                )
            )
    return pairs


def embedding_candidates(
    embeddings: np.ndarray,
    valid_mask: np.ndarray,
    threshold: float,
    top_k: int = 10,
) -> list[CandidatePair]:
    """Top-k cosine-similarity neighbours above ``threshold``.

    ``embeddings`` must already be L2-normalised, so cosine similarity is a
    plain dot product. Rows where ``valid_mask`` is False are excluded.
    """
    from sklearn.neighbors import NearestNeighbors  # noqa: PLC0415

    idx = np.nonzero(valid_mask)[0]
    if idx.size < 2:
        return []

    matrix = embeddings[idx]
    k = int(min(top_k + 1, idx.size))

    nn = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute")
    nn.fit(matrix)
    distances, neighbours = nn.kneighbors(matrix, n_neighbors=k)

    seen: set[tuple[int, int]] = set()
    pairs: list[CandidatePair] = []
    for row in range(idx.size):
        for col in range(k):
            other = int(neighbours[row, col])
            if other == row:
                continue
            similarity = float(1.0 - distances[row, col])
            if similarity < threshold:
                continue
            a, b = int(idx[row]), int(idx[other])
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                CandidatePair(
                    a_idx=key[0],
                    b_idx=key[1],
                    distance=round(1.0 - similarity, 6),
                    similarity=round(similarity, 6),
                )
            )
    return pairs


class UnionFind:
    """Disjoint-set forest used to build duplicate groups from pairs."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))
        self._rank = [0] * size

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self._parent)):
            out[self.find(i)].append(i)
        return {root: members for root, members in out.items() if len(members) > 1}
