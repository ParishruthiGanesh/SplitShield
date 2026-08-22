# Hackathon submission — Proof of Possible 2026

## Project name

**SplitShield**

## Tagline

Detect, repair, and quantify hidden leakage in computer-vision datasets.

## Inspiration

Every ML practitioner has seen a model score suspiciously well, only to
discover the test set contained images the model had already trained on —
sometimes byte-identical, sometimes a recompressed or cropped copy. Tools
exist to *find* duplicates, but the workflow that matters — reviewing the
evidence, repairing the split without wrecking the test set, and honestly
quantifying what the leakage was associated with — is usually a pile of ad-hoc
notebooks. We wanted that workflow as a product.

## Problem

Duplicate and near-duplicate images crossing train/val/test boundaries inflate
reported accuracy and invalidate comparisons. Leakage is common in scraped,
merged and versioned datasets, invisible at a glance, and rarely measured.

## Intended users

CV researchers, students, and ML engineers auditing image-classification
datasets before trusting or publishing results.

## What it does

* Ingests a dataset ZIP (train/val/test folder convention) with hardened
  extraction — signature validation, traversal and zip-bomb guards.
* Detects **exact duplicates** (SHA-256), **near duplicates** (64-bit DCT
  pHash, exhaustive Hamming search) and **appearance-similar pairs**
  (embedding + cosine top-k), each with split-aware severity and cautious
  confidence language.
* Flags **conflicting-label duplicates**, corrupt files, class and split
  imbalance, and computes a documented, deterministic **Dataset Integrity
  Score** with a full breakdown.
* **Evidence Explorer**: side-by-side pair review with zoom, filters, and
  persisted human decisions that influence downstream outputs without ever
  overwriting algorithmic evidence.
* **Repair Studio**: a proposed split manifest that consolidates duplicate
  groups into single splits, protects the test set, excludes ambiguous-label
  groups, explains every action, and exports CSV/JSON. Original files are
  never touched.
* **Observed Evaluation Gap**: trains a seeded diagnostic classifier on frozen
  embeddings, scores it on the original vs. leakage-quarantined test set, and
  reports both accuracies, macro-F1 and bootstrap confidence intervals — with
  explicit anti-overclaiming warnings.
* Exports a reproducible **audit report** (printable HTML→PDF, JSON) with the
  dataset fingerprint, config, package versions and seed.
* Ships a deterministic **synthetic demo dataset** with a ground-truth
  manifest of planted defects, processed by the identical pipeline as uploads.

## How it works

FastAPI backend runs a staged pipeline (validate → index → exact → perceptual
→ embedding → score → evaluate → report) in a bounded worker pool with every
stage transition persisted to SQLite; the Next.js frontend polls job state and
renders dashboards, evidence, repair and report views from the computed
results. Embeddings are pluggable: MobileNetV3-Small when torch and weights
are available, otherwise a validated classical appearance descriptor — the
active backend is always disclosed in the UI and report.

## Technical architecture

Next.js 15 (TypeScript strict, Tailwind 4, Recharts) ↔ FastAPI (Python 3.11,
Pydantic v2) · SQLite WAL · Pillow + ImageHash + NumPy + scikit-learn ·
Playwright E2E · Docker Compose. See `ARCHITECTURE.md`.

## What was built during the hackathon

Everything in the repository: the full backend pipeline and API, the complete
frontend, the demo generator with ground-truth verification, 84 backend tests
plus a browser E2E test, Dockerfiles/Compose, and all documentation.

## Challenges

* **No access to pretrained weights** in the build environment (network
  policy blocks pytorch.org and Hugging Face). Instead of faking "semantic"
  analysis, we built and *validated* a classical appearance descriptor
  (structure + chromaticity + gradient blocks) and made the backend
  auto-detect and honestly label whichever provider is active.
* **A global colour histogram turned out to be anti-discriminative** during
  validation (brightness-shifted copies scored *lower* than unrelated
  images). Per-block similarity diagnosis led us to replace it with an
  illumination-invariant spatial chromaticity map — variants now score ≥0.94
  vs ≤0.81 for the 99th percentile of unrelated pairs.
* **Crops defeat pHash** even at 96% retention. We rescoped crop detection to
  the embedding stage, sized the demo's planted crops to measured
  detectability, and documented the limitation rather than hiding it.
* **Thread-local SQLite connections** went stale across test-isolated data
  directories; fixed by keying the cached connection on the database path.

## Accomplishments

* 13/13 planted demo defect pairs recovered by the real pipeline, verified in
  CI against the generated ground-truth manifest.
* A genuinely measured evaluation gap on the demo (same trained model, test
  accuracy drops when quarantining leaked samples) with bootstrap CIs.
* Security-first ingestion that survives hostile archives (traversal,
  zip-bombs, type confusion) with tests proving each guard.
* An honest product: every number in the UI is computed, every fallback is
  disclosed, every claim is scoped.

## Lessons learned

Validate perceptual features against a ground-truth benchmark *before*
building UI on them; measure per-component similarity when a metric
misbehaves; and "strongest honest fallback" beats "impressive but simulated"
— the classical descriptor caught every planted transform in the demo.

## Responsible delivery

No facial recognition or identity inference; local-only analysis;
signature-validated, never-executed uploads; random internal paths;
configurable retention plus one-click deletion; cautious evidence language;
causality explicitly not claimed. See `RESPONSIBLE_AI.md`.

## Limitations

Rotations/flips/heavy crops can evade detection; the classical descriptor
measures appearance, not concepts; the diagnostic classifier is not a
production model; image classification only; single-node prototype. See
README "Known limitations".

## Future work

MP4 frame sampling, FAISS for 10⁵⁺ images, ONNX-bundled learned embeddings,
S3 storage driver, detection/segmentation dataset formats, team review flows.

## Technologies

Python 3.11 · FastAPI · Pydantic · Pillow · ImageHash · NumPy · SciPy ·
scikit-learn · SQLite · TypeScript · Next.js 15 · React 19 · Tailwind CSS 4 ·
Recharts · Playwright · Docker.

## Third-party disclosures

See `THIRD_PARTY_DISCLOSURES.md`. Prior art acknowledged: FiftyOne,
CleanVision, Cleanlab.

## Team contribution

Solo build (with AI pair-programming assistance) during the hackathon window:
architecture, pipeline, frontend, tests and documentation.
