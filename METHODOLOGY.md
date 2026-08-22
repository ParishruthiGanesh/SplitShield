# SplitShield methodology

This document specifies every algorithm and formula used to produce numbers in
the product. Nothing in the UI or report is model-generated or hard-coded.

## 1. Ingestion & validation

* Archive entries are validated **before extraction**: entry count
  (≤ `max_file_count`), per-member size (≤ `max_member_bytes`), total
  uncompressed size (≤ `max_uncompressed_bytes`), compression ratio
  (≤ `max_compression_ratio`), safe relative paths only (no `..`, absolute
  paths, drive letters, NUL bytes), regular files only (no symlinks).
* Extracted bytes are re-checked by **magic signature** (JPEG `FF D8 FF`,
  PNG `89 50 4E 47 0D 0A 1A 0A`, WebP `RIFF....WEBP`). Extension lies are
  rejected.
* Split/label are derived from the folder layout
  (`[wrapper/]<split>/<class...>/<file>`), with aliases
  train/training, val/valid/validation/dev, test/testing/eval.
* Decode failures (Pillow verify + load) never abort the job; the file
  becomes a `corrupt_sample` finding.

## 2. Exact duplicates

SHA-256 over raw file bytes; identical digests are grouped. All pairs in a
group are findings. Only these carry the label **"Confirmed exact duplicate"**.

## 3. Near duplicates (perceptual)

64-bit DCT pHash (`imagehash.phash`, `hash_size=8`) on the RGB-converted
image. Pair generation is an **exhaustive** chunked Hamming-distance sweep
(`numpy.bitwise_count` on XORed uint64s) — no candidate can be missed at the
configured threshold.

| Hamming distance d | Interpretation |
| --- | --- |
| d = 0 | perceptually identical (bytes may differ) |
| d ≤ strong threshold (default 4) | **Likely near duplicate** |
| d ≤ threshold (default 8) | candidate — **Requires human review** |

Similarity is reported as `1 − d/64`.

Known failure modes: crops beyond a few percent, rotations, flips.

## 4. Embedding similarity

Backends (selected at runtime, always disclosed):

* **MobileNetV3-Small (ImageNet)** — 576-d global-pooled features, CPU.
  Requires torch + downloadable weights.
* **Classical appearance descriptor** (default in offline environments) —
  512-d concatenation of three L2-normalised blocks:
  1. *Structure*: 16×16 bilinear greyscale thumbnail, mean-centred,
     unit-variance (brightness/contrast invariant).
  2. *Chromaticity*: 8×8 map of (r,g)/(r+g+b) fractions, mean-centred —
     invariant to global intensity scaling by construction.
  3. *Gradients*: 4×4 spatial grid × 8 unsigned orientation bins,
     magnitude-weighted (compact HOG).

  Validation on synthetic imagery: rescaled/recompressed/92%-cropped/1.3×
  brightened copies score cosine ≥ 0.94 against the source; the 99th
  percentile of unrelated pairs is ≈ 0.81.

Search is top-k nearest neighbours by cosine (k = `semantic_top_k`, default
10) — output is O(n·k), never an unbounded all-pairs sweep. Matches above
`semantic_threshold` (default 0.90) are **"Possible semantic overlap —
requires human review"** and are never automatically treated as duplicates.

## 5. Evidence precedence & classification

When multiple methods flag one pair: `sha256 > phash > embedding`. The
stronger method defines the finding; weaker corroborations are recorded in
`detail.methods`.

| Condition | Kind | Severity |
| --- | --- | --- |
| exact match, different labels | conflicting_label_duplicate | critical |
| strong pHash, different labels | conflicting_label_duplicate | high |
| exact match, cross-split | exact_cross_split_leakage | critical |
| pHash ≤ strong thr., cross-split | near_duplicate_cross_split_leakage | high |
| pHash ≤ thr., cross-split | near_duplicate_cross_split_leakage | medium |
| embedding, cross-split | possible_semantic_overlap | medium |
| exact/pHash, same split | same_split_redundancy | low |
| embedding, same split | possible_semantic_overlap | low |

## 6. Dataset Integrity Score

```
rate_c    = distinct_affected_samples_c / total_valid_samples
penalty_c = weight_c × min(1, rate_c / saturation_c)
score     = clamp(100 − Σ penalty_c, 0, 100)
```

| Category c | weight | saturation (rate at full weight) |
| --- | --- | --- |
| exact_cross_split_leakage | 35 | 5% |
| conflicting_label_duplicate | 25 | 3% |
| near_duplicate_cross_split_leakage | 20 | 10% |
| possible_semantic_overlap | 8 | 25% |
| corrupt_sample | 6 | 10% |
| same_split_redundancy | 5 | 30% |
| class_imbalance | 3 | ramp: none ≤ 2×, full at ≥ 10× (largest/smallest class) |
| split_imbalance | 3 | ramp: 0 inside 10–40% test fraction; full at < 5%, missing test split, or ≫ 40% |

Normalising by `total_valid_samples` keeps large datasets from being punished
for absolute counts. Grades: ≥ 90 Low risk, ≥ 75 Moderate, ≥ 50 High,
else Severe. Findings a reviewer marks **safe** can be excluded from a
recomputation, but stored evidence is never altered.

## 7. Split repair rules

1. Build duplicate groups = connected components over exact + pHash findings
   (+ embedding findings if opted in or human-confirmed; findings marked
   *safe* are dropped).
2. Groups on one split: no move (optional dedup left to the user).
3. Cross-split groups: consolidate **out of test into train** — evaluating on
   memorised samples is worse than losing training data — unless the group is
   majority-test, in which case consolidate to test.
4. Conflicting-label groups: exclude entirely, pending human labeling.
5. Corrupt samples: exclude.
6. Every entry carries `(sample_id, original_split, proposed_split, class,
   group_id, action, reason)`. Original files are never touched.
7. Warnings are emitted when a class loses > 50% of its test samples.

## 8. Observed Evaluation Gap

Eligibility: labeled train **and** test splits sharing ≥ 2 classes;
≥ 5 train samples per shared class; ≥ 10 test samples. Otherwise the
experiment is disabled with the exact reason — metrics are never invented.

Procedure (fixed seed, default 1337):

1. Embed all valid images with the active backend (frozen features).
2. Fit `LogisticRegression(C=1.0, max_iter=2000)` on the original train split.
3. Predict the original test split → accuracy, macro-F1,
   95% percentile-bootstrap CI (1,000 resamples when n ≥ 20).
4. Quarantine test samples in strong cross-split leakage: SHA-256 matches,
   high/critical pHash matches, plus human-confirmed findings; minus findings
   marked safe.
5. Re-score **the same fitted model** on the remaining test samples → cleaned
   accuracy/F1/CI.
6. `observed_evaluation_gap = original_accuracy − cleaned_accuracy`.

Interpretation guardrails (attached to every result): evidence of sensitivity,
not causation; population changes when samples are removed; small-sample
instability; threshold dependence; diagnostic-only baseline.

## 9. Comparison with existing tools

FiftyOne (duplicate views, embedding exploration), CleanVision (image-issue
scanning) and Cleanlab (label errors) each cover parts of detection.
SplitShield adds the leakage-specific layer: split-aware severity, reviewable
evidence, test-protecting repair manifests, and the quantified evaluation gap
with reproducible reports.
