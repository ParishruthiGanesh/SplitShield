# SplitShield architecture

## Overview

Two deployable services plus a shared analysis pipeline:

```text
frontend (Next.js 15, TS strict, Tailwind 4, Recharts)
  ├── /            landing
  ├── /upload      drag-and-drop + advanced settings
  ├── /audit/[id]  progress → dashboard | evidence | repair | report tabs
  └── /methodology public method + limitation docs

backend (FastAPI, Python 3.11)
  ├── app/main.py        HTTP surface (OpenAPI at /docs)
  ├── app/jobs.py        job lifecycle, thread-pool execution, retention
  ├── app/db.py          SQLite persistence (WAL, serialized writes)
  ├── app/report.py      report + CSV rendering from persisted results
  ├── app/demo/          deterministic synthetic demo generator
  └── app/pipeline/
        ingest.py        safe ZIP extraction + layout classification
        indexing.py      SHA-256, pHash, metadata, corruption isolation
        embeddings.py    pluggable providers (torch | classical)
        similarity.py    exact grouping, pHash pairs, k-NN search, union-find
        classify.py      evidence precedence + severity assignment
        scoring.py       inventory, dataset issues, Integrity Score
        repair.py        split-repair manifest planner
        evaluation.py    Observed Evaluation Gap experiment
```

## Key decisions

| Decision | Rationale |
| --- | --- |
| **SQLite + `sqlite3`** (no ORM) | Durable job state and paginated queries with zero infra. All SQL lives in `db.py`/`main.py`; a Postgres swap is contained. WAL mode + a process-wide write lock fits the single-writer model. |
| **ThreadPoolExecutor over Celery/RQ** | The MVP is single-node; a bounded in-process pool with *persisted stage transitions* gives restart-safe status without a broker. The `run_audit_async` seam is where a real queue would slot in. |
| **Pluggable embeddings with an honest fallback** | The deployment environment may not be able to fetch pretrained weights. Rather than fake "semantic" analysis, the classical appearance descriptor is used and *labeled as such* everywhere (UI, API, report). `torch_backend_available()` probes weights at runtime. |
| **Chunked exact pHash search over LSH/BK-tree** | `np.bitwise_count` over 64-bit ints compares ~10⁸ pairs/s per core with zero recall loss. For the ≤50k-image MVP cap this is simpler and *provably exhaustive*; an index becomes worthwhile only far beyond that. |
| **k-NN (scikit-learn brute cosine) for embeddings** | Bounded output (top-k), no O(n²) materialisation. FAISS can replace it behind `embedding_candidates()` without touching callers. |
| **Reviews stored separately from findings** | Human decisions must influence repair/eval/report but never overwrite algorithmic evidence. `reviews` is a separate table joined at read time. |
| **Repair = manifest, not file mutation** | Silently rewriting a user's dataset is unacceptable; the manifest (CSV/JSON with reasons) is auditable and reversible. |
| **Demo generated at request time** | Guarantees the demo exercises the identical pipeline; determinism comes from a fixed seed, verified byte-identical by test. |

## Data flow of one audit

1. `POST /api/audits/upload` streams the ZIP to `uploads/<random>.zip`
   (size-capped), creates a `jobs` row, schedules `_run_audit_safe`.
2. **Validating** — `inspect_archive` walks the central directory: entry
   count, per-file and total uncompressed caps, compression-ratio guard,
   traversal/symlink rejection, extension check.
3. **Indexing** — accepted members stream out under generated internal ids
   (`s0000001.jpg`); magic bytes are sniffed; SHA-256, pHash, dimensions
   recorded; decode failures become `corrupt` samples.
4. **Exact** — digest group-by.
5. **Near** — exhaustive chunked Hamming search at the configured threshold.
6. **Semantic** — active provider embeds all valid images; top-k cosine
   neighbours above threshold become candidates.
7. **Scoring** — candidates merge with strict evidence precedence
   (sha256 > phash > embedding), get classified and persisted; inventory,
   dataset issues and the Integrity Score are computed.
8. **Evaluation** — if eligible, the diagnostic classifier runs (seeded).
9. **Report** — repair plan persisted; job marked complete.

Review updates (`PATCH .../review`) recompute repair and (on demand)
re-run the evaluation with quarantine decisions honoured; the original
evidence rows are immutable.

## Retention & deletion

A background task sweeps expired jobs every `retention_sweep_seconds`,
removing extracted files and DB rows. `DELETE /api/audits/{id}` does the same
immediately. Embeddings are cached in memory per job and evicted on delete.

## Storage abstraction

All artefact paths derive from `settings.data_dir`; `job_storage_dir()` is the
single seam for later S3-compatible storage (presigned upload, remote extract
worker).

## Scaling the design later

* Queue: replace the executor submit with a broker task; stages already persist.
* Search: FAISS IVF index behind `embedding_candidates` for 10⁵–10⁷ images.
* Storage: S3 driver + signed image URLs in `get_sample_image`.
* Video: `ingest` produces "samples"; a frame-sampler would emit frames as
  samples sharing a `source_group`, which the repair planner already respects
  via duplicate groups.
