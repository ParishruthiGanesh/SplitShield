# SplitShield

**Detect, repair, and quantify hidden leakage in computer-vision datasets.**

Built for the *Proof of Possible 2026* hackathon.

---

## The problem

Duplicate and near-duplicate images that cross the train/validation/test
boundary quietly inflate reported model performance: the model is graded on
samples it has effectively already seen. This *data leakage* is common in
scraped and merged datasets, hard to spot by eye, and rarely quantified.

## Intended users

Computer-vision researchers, students and ML engineers who need to know
whether their image-classification splits are trustworthy before they quote a
number.

## What SplitShield does

1. **Detect** — SHA-256 exact matching, DCT perceptual hashing (pHash) and
   embedding similarity search surface duplicate/near-duplicate pairs, with
   split-aware severity (cross-split > same-split) and conflicting-label
   detection.
2. **Explain** — a side-by-side Evidence Explorer with similarity metrics,
   filters, zoom, and human review decisions (confirm / safe / uncertain + note).
3. **Repair** — a proposed split manifest that consolidates duplicate groups
   into one split, protects the test set, excludes ambiguous-label groups, and
   explains every action. Original files are never modified.
4. **Quantify** — the **Observed Evaluation Gap**: a diagnostic classifier
   (logistic regression on frozen embeddings) is trained on the original train
   split and scored on the original vs. leakage-quarantined test set, with
   bootstrap confidence intervals.
5. **Export** — a reproducible audit report (printable HTML → PDF, JSON) plus
   CSV/JSON manifests, carrying the dataset fingerprint, config, package
   versions and random seed.

## How SplitShield differs

Duplicate detection itself is not new — [FiftyOne](https://voxel51.com/fiftyone/),
[CleanVision](https://github.com/cleanlab/cleanvision) and
[Cleanlab](https://cleanlab.ai/) are excellent at it. SplitShield's focus is the
**leakage workflow on top of detection**: split-aware severity, human-reviewed
evidence, test-set-protecting repair, and careful quantification of the
observed evaluation difference. We deliberately avoid causal language: the gap
is *evidence of sensitivity to leakage*, not proof that leakage caused a
specific accuracy boost.

## Architecture

```text
┌────────────────────┐         ┌───────────────────────────────────────┐
│  Next.js frontend   │  HTTP   │  FastAPI backend                       │
│  (React 19, TS,     ├────────►│                                        │
│  Tailwind, Recharts)│  JSON   │  ┌──────────── pipeline ────────────┐  │
│                     │         │  │ ingest → index → exact → pHash    │  │
│  landing / upload   │         │  │ → embeddings → classify → score   │  │
│  dashboard / review │         │  │ → repair → evaluation → report    │  │
│  repair / report    │         │  └──────────────────────────────────┘  │
└────────────────────┘         │  SQLite (jobs, findings, reviews)       │
                               │  Local object storage (random IDs)      │
                               └───────────────────────────────────────┘
```

* **Jobs** run in a bounded thread pool; every stage transition is persisted so
  the UI polls and never blocks.
* **Storage** is a local directory abstraction (random internal IDs, never user
  paths) with an interface that an S3-compatible layer can replace later.
* **Embeddings** are pluggable: MobileNetV3-Small (ImageNet) when
  torch + weights are available, otherwise a documented classical appearance
  descriptor (structure + chromaticity + gradient histograms). The active
  backend is always reported honestly in the UI and report.

## Supported dataset format

A ZIP archive of an image-classification dataset:

```text
dataset.zip
├── train/
│   ├── class_a/ img001.jpg …
│   └── class_b/ img050.png …
├── val/            # optional (val/valid/validation/dev all accepted)
│   └── class_a/ …
└── test/
    ├── class_a/ …
    └── class_b/ …
```

* Formats: **JPG/JPEG, PNG, WebP** (validated by file signature, not extension).
* A single wrapper directory (`dataset/train/...`) is tolerated.
* Corrupt images are quarantined and reported — they never crash a job.
* Video is **not** supported in this MVP; the pipeline's sample abstraction is
  designed so frame-sampled videos can be added later.

### Detection-style layout (no class folders)

Datasets whose images sit directly inside split folders — the layout used by
YOLO and most detection tools (`images/train/img.jpg`, `images/val/…`,
`images/test/…`) — are also accepted. Such samples are treated as **unlabeled**:

* Exact, near-duplicate and appearance-similarity leakage detection run normally.
* Conflicting-label detection and the evaluation-gap experiment are disabled,
  with the reason stated in the dashboard and report (they require class labels).
* Non-image files (`labels/*.txt`, `data.yaml`) are ignored safely.

## Local setup

Prerequisites: Python 3.11+, Node 20+.

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
# OpenAPI docs: http://localhost:8000/docs

# Frontend (second terminal)
cd frontend
npm install
npm run dev          # http://localhost:3000
# or production: npm run build && npm run start
```

Optional learned embeddings (needs network access to pytorch.org):

```bash
backend/.venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

If the weights are unavailable the classical descriptor is used automatically
and labeled as such.

## Docker setup

```bash
docker compose up --build
# Frontend: http://localhost:3000   API docs: http://localhost:8000/docs
```

Uploaded data lives in the `splitshield-data` volume and auto-deletes after
`SPLITSHIELD_RETENTION_HOURS` (default 24).

## Environment variables

All optional; see `backend/.env.example` for the complete list with defaults.
Key ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPLITSHIELD_DATA_DIR` | `/tmp/splitshield-data` | uploads, extracted data, SQLite |
| `SPLITSHIELD_MAX_UPLOAD_BYTES` | 512 MiB | archive size limit |
| `SPLITSHIELD_MAX_UNCOMPRESSED_BYTES` | 2 GiB | zip-bomb guard |
| `SPLITSHIELD_MAX_FILE_COUNT` | 50 000 | entries per archive |
| `SPLITSHIELD_RETENTION_HOURS` | 24 | auto-delete window |
| `SPLITSHIELD_PHASH_THRESHOLD` | 8 | near-duplicate Hamming threshold |
| `SPLITSHIELD_SEMANTIC_THRESHOLD` | 0.90 | cosine-similarity threshold |
| `SPLITSHIELD_EMBEDDING_BACKEND` | `auto` | `auto` / `torch` / `classical` / `off` |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://localhost:8000` | backend origin |

No secrets are required anywhere. `.env.example` files contain placeholders only.

## Testing

```bash
# Backend: 84 unit/integration tests
cd backend && .venv/bin/python -m pytest tests/ -q

# Frontend type-check + lint + build
cd frontend && npx tsc --noEmit && npm run lint && npm run build

# E2E (needs backend :8000 and frontend :3000 running)
cd frontend && npx playwright test
```

Test coverage includes: ZIP path-traversal prevention, zip-bomb guards, file
signature validation, exact/perceptual detection, cross-split grouping,
conflicting labels, Integrity-Score determinism and normalisation, repair
rules, review persistence, evaluation-gap calculation and eligibility, API
job flow, deletion, and demo ground-truth recovery.

## Demo instructions

1. Open the app → **Try demonstration dataset** (or `POST /api/audits/demo`).
2. The demo is a deterministic synthetic dataset (116 images, 3 classes)
   generated at audit time with **known planted defects** — exact train/test
   duplicates, recompressed/resized/cropped/brightened variants, a
   conflicting-label pair, a corrupt file and class imbalance — documented in
   a generated `GROUND_TRUTH.json`. It runs through **exactly the same
   pipeline as uploads**; nothing is precomputed.
3. Walk the tabs: Dashboard → Evidence Explorer (review a pair) → Repair
   Studio (export the manifest) → Report.

## Methodology (short version)

* **Exact:** SHA-256 over file bytes; only these are called “confirmed”.
* **Near:** 64-bit DCT pHash; Hamming ≤ 8 flags a pair, ≤ 4 = “likely near
  duplicate”, else “requires human review”.
* **Similarity:** normalized embeddings + cosine top-k search (never unbounded
  all-pairs); matches are “possible overlap”, never auto-duplicates.
* **Integrity Score (0–100):**
  `score = clamp(100 − Σ weight_c · min(1, rate_c/saturation_c))` with
  documented weights (exact cross-split 35, conflicting labels 25, near-dup
  cross-split 20, overlap 8, corrupt 6, redundancy 5, imbalances 3+3) and
  rates normalized by dataset size. Full details in
  [`METHODOLOGY.md`](METHODOLOGY.md).
* **Observed Evaluation Gap:** same trained model, original vs quarantined
  test set, macro-F1 + bootstrap CIs, seed recorded. Guardrails against causal
  over-claiming are printed with every result.

## Privacy & security

* No facial recognition, no identity inference, no external upload of images.
* Signature-based file validation; safe extraction (traversal, symlink,
  zip-bomb, per-file and total-size guards); uploads are never executed.
* Random internal storage paths; configurable retention; one-click
  “Delete my audit”.
* Datasets must be legally obtained by the uploader.

## Known limitations

* Rotated/flipped/heavily-cropped copies can evade pHash and the classical
  descriptor.
* The classical descriptor measures appearance, not concepts; true semantic
  overlap detection requires the learned backend.
* The diagnostic classifier is not a production model; small test sets give
  unstable gap estimates (read the CIs).
* Image classification only; no video, no detection/segmentation formats yet.
* Single-node deployment; SQLite is not a multi-writer store.

## Responsible-use statement

SplitShield is a dataset-quality tool. It must not be used to identify people,
re-identify anonymised data, or audit datasets you have no right to process.
Reported metrics are diagnostic evidence, not certification: a high Integrity
Score does not guarantee a leak-free dataset.

## Technologies

FastAPI · Pydantic · Pillow · ImageHash · NumPy · SciPy · scikit-learn ·
SQLite · Next.js 15 · React 19 · TypeScript (strict) · Tailwind CSS 4 ·
Recharts · Playwright · Docker Compose. Full license list in
[`THIRD_PARTY_DISCLOSURES.md`](THIRD_PARTY_DISCLOSURES.md).

## What was built during the hackathon

Everything in this repository — backend pipeline, API, frontend, demo
generator, tests, docs — was written during the hackathon window. See
[`HACKATHON_SUBMISSION.md`](HACKATHON_SUBMISSION.md) and
[`BUILD_STATUS.md`](BUILD_STATUS.md).

## Future improvements

* MP4 frame sampling with per-video sample groups (backend abstraction ready).
* FAISS index for 100k+ image datasets.
* Learned-embedding backend bundled via ONNX to remove the torch dependency.
* S3-compatible storage driver; multi-user auth; team review workflows.
* COCO/YOLO detection-format support.
