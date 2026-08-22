"""Audit-job lifecycle: creation, background execution, persistence, retention.

Execution uses a bounded ``ThreadPoolExecutor`` rather than FastAPI's
``BackgroundTasks`` so job state survives request scope and concurrency is
capped. All stage transitions are persisted, so the UI polls the database and
never blocks on the worker.
"""
from __future__ import annotations

import logging
import secrets
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .config import settings
from .db import get_conn, jdump, jload, write_tx
from .demo.generate import generate_demo_dataset
from .domain import JobStatus, ReviewDecision, Stage
from .pipeline.classify import build_findings
from .pipeline.embeddings import get_provider
from .pipeline.evaluation import run_evaluation_gap
from .pipeline.indexing import index_sample
from .pipeline.ingest import (
    ExtractResult,
    IngestError,
    collect_directory,
    extract_dataset,
    fingerprint_dataset,
)
from .pipeline.repair import build_repair_plan
from .pipeline.scoring import build_dataset_issues, build_inventory, compute_integrity_score
from .pipeline.similarity import embedding_candidates, group_exact, perceptual_candidates

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()

# In-memory cache of embeddings per job (recomputed on demand if evicted).
_embedding_cache: dict[str, np.ndarray] = {}


def get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=settings.max_concurrent_jobs, thread_name_prefix="audit"
            )
        return _executor


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def new_job_id() -> str:
    return "job_" + secrets.token_urlsafe(12)


DEFAULT_JOB_CONFIG = {
    "enable_exact": True,
    "enable_perceptual": True,
    "enable_semantic": True,
    "phash_threshold": None,        # None -> settings default
    "phash_strong_threshold": None,
    "semantic_threshold": None,
    "semantic_top_k": None,
    "run_evaluation": True,
}


def resolve_config(overrides: dict | None) -> dict:
    cfg = dict(DEFAULT_JOB_CONFIG)
    if overrides:
        for key in cfg:
            if key in overrides and overrides[key] is not None:
                cfg[key] = overrides[key]
    cfg["phash_threshold"] = int(cfg["phash_threshold"] or settings.phash_threshold)
    cfg["phash_strong_threshold"] = int(
        cfg["phash_strong_threshold"] or settings.phash_strong_threshold
    )
    cfg["semantic_threshold"] = float(cfg["semantic_threshold"] or settings.semantic_threshold)
    cfg["semantic_top_k"] = int(cfg["semantic_top_k"] or settings.semantic_top_k)
    # Clamp to sane ranges so hostile input cannot cause pathological work.
    cfg["phash_threshold"] = max(0, min(24, cfg["phash_threshold"]))
    cfg["phash_strong_threshold"] = max(0, min(cfg["phash_threshold"], cfg["phash_strong_threshold"]))
    cfg["semantic_threshold"] = max(0.5, min(0.9999, cfg["semantic_threshold"]))
    cfg["semantic_top_k"] = max(1, min(50, cfg["semantic_top_k"]))
    return cfg


def create_job(source: str, dataset_name: str | None, config: dict | None) -> str:
    job_id = new_job_id()
    now = _now()
    cfg = resolve_config(config)
    with write_tx() as conn:
        conn.execute(
            """INSERT INTO jobs (id, status, stage, progress, source, dataset_name,
               config_json, created_at, updated_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                JobStatus.QUEUED.value,
                Stage.QUEUED.value,
                0.0,
                source,
                dataset_name,
                jdump(cfg),
                _iso(now),
                _iso(now),
                _iso(now + timedelta(hours=settings.retention_hours)),
            ),
        )
    return job_id


def get_job(job_id: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM jobs WHERE id=? AND deleted=0", (job_id,)).fetchone()
    return dict(row) if row else None


def _update_job(job_id: str, **fields) -> None:
    fields["updated_at"] = _iso(_now())
    columns = ", ".join(f"{k}=?" for k in fields)
    with write_tx() as conn:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), job_id))


def _set_stage(job_id: str, stage: Stage, progress: float, message: str = "") -> None:
    _update_job(
        job_id,
        stage=stage.value,
        progress=round(progress, 3),
        message=message,
        status=JobStatus.RUNNING.value if stage is not Stage.COMPLETE else JobStatus.COMPLETE.value,
    )


def job_storage_dir(job_id: str) -> Path:
    """Per-job randomised storage directory (never derived from user input)."""
    return settings.extract_dir / job_id


def run_audit_async(job_id: str, zip_path: Path | None, demo: bool) -> None:
    get_executor().submit(_run_audit_safe, job_id, zip_path, demo)


def _run_audit_safe(job_id: str, zip_path: Path | None, demo: bool) -> None:
    try:
        _run_audit(job_id, zip_path, demo)
    except IngestError as exc:
        logger.warning("Job %s rejected: %s", job_id, exc)
        _update_job(job_id, status=JobStatus.FAILED.value, error=str(exc))
    except Exception:
        logger.exception("Job %s crashed", job_id)
        _update_job(
            job_id,
            status=JobStatus.FAILED.value,
            error="Internal analysis error. The uploaded data has been discarded.",
        )
        logger.debug("%s", traceback.format_exc())
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)


def _run_audit(job_id: str, zip_path: Path | None, demo: bool) -> None:
    job = get_job(job_id)
    if job is None:
        return
    cfg = jload(job["config_json"], {})

    # ---- Stage: validating / extraction --------------------------------
    _set_stage(job_id, Stage.VALIDATING, 0.02, "Validating archive structure")
    dest = job_storage_dir(job_id)
    if demo:
        generate_demo_dataset(dest / "dataset")
        extract: ExtractResult = collect_directory(dest / "dataset")
    else:
        assert zip_path is not None
        extract = extract_dataset(zip_path, dest / "dataset")
    _update_job(job_id, storage_path=str(dest))

    # ---- Stage: indexing -------------------------------------------------
    _set_stage(job_id, Stage.INDEXING, 0.08, f"Indexing {len(extract.files)} images")
    samples = []
    total = len(extract.files)
    for pos, item in enumerate(extract.files):
        samples.append(index_sample(item, hash_size=settings.phash_size))
        if pos % 200 == 199:
            _set_stage(
                job_id, Stage.INDEXING, 0.08 + 0.22 * (pos / total), f"Indexed {pos + 1}/{total}"
            )

    with write_tx() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO samples
               (job_id,id,split,label,rel_path,sha256,phash,width,height,bytes,
                img_format,corrupt,error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    job_id, s.id, s.split.value, s.label, s.rel_path, s.sha256, s.phash,
                    s.width, s.height, s.bytes, s.img_format, int(s.corrupt), s.error,
                )
                for s in samples
            ],
        )

    digests = {s.id: s.sha256 or "" for s in samples}
    fingerprint = fingerprint_dataset(extract.files, digests)

    # ---- Stage: exact ------------------------------------------------------
    _set_stage(job_id, Stage.EXACT, 0.34, "Grouping SHA-256 digests")
    exact_groups = (
        group_exact([s.sha256 if not s.corrupt else None for s in samples])
        if cfg["enable_exact"]
        else []
    )

    # ---- Stage: near -------------------------------------------------------
    _set_stage(job_id, Stage.NEAR, 0.42, "Comparing perceptual hashes")
    phash_pairs = (
        perceptual_candidates([s.phash for s in samples], cfg["phash_threshold"])
        if cfg["enable_perceptual"]
        else []
    )

    # ---- Stage: semantic -----------------------------------------------------
    embedding_pairs = []
    backend_note = "Semantic stage disabled for this audit."
    backend_info = None
    embeddings = None
    if cfg["enable_semantic"]:
        _set_stage(job_id, Stage.SEMANTIC, 0.52, "Computing image embeddings")
        provider, backend_note = get_provider(
            settings.embedding_backend, settings.embedding_batch_size
        )
        if provider is not None:
            backend_info = provider.info.__dict__
            embeddings = provider.embed_paths([s.stored_path for s in samples])
            valid_mask = np.array([not s.corrupt for s in samples], dtype=bool)
            _set_stage(job_id, Stage.SEMANTIC, 0.62, "Searching nearest neighbours")
            embedding_pairs = embedding_candidates(
                embeddings, valid_mask, cfg["semantic_threshold"], cfg["semantic_top_k"]
            )
            _embedding_cache[job_id] = embeddings
    elif cfg["run_evaluation"]:
        # The experiment needs embeddings even when the semantic detector is off.
        provider, _ = get_provider(settings.embedding_backend, settings.embedding_batch_size)
        if provider is not None:
            embeddings = provider.embed_paths([s.stored_path for s in samples])
            _embedding_cache[job_id] = embeddings

    # ---- Stage: scoring -------------------------------------------------------
    _set_stage(job_id, Stage.SCORING, 0.72, "Classifying findings and scoring")
    findings = build_findings(
        samples, exact_groups, phash_pairs, embedding_pairs, cfg["phash_strong_threshold"]
    )

    # Assign duplicate-group ids for display.
    from .pipeline.similarity import UnionFind  # noqa: PLC0415

    uf = UnionFind(len(samples))
    for f in findings:
        uf.union(f.a_idx, f.b_idx)
    roots = {}
    for f in findings:
        root = uf.find(f.a_idx)
        roots.setdefault(root, f"g{len(roots):04d}")

    with write_tx() as conn:
        conn.execute("DELETE FROM findings WHERE job_id=?", (job_id,))
        conn.executemany(
            """INSERT INTO findings
               (job_id,id,kind,severity,confidence_label,method,sample_a,sample_b,
                split_a,split_b,class_a,class_b,distance,similarity,cross_split,
                conflicting_label,group_id,detail_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    job_id, f.id, f.kind.value, f.severity.value, f.confidence_label.value,
                    f.method.value, samples[f.a_idx].id, samples[f.b_idx].id,
                    samples[f.a_idx].split.value, samples[f.b_idx].split.value,
                    samples[f.a_idx].label, samples[f.b_idx].label,
                    f.distance, f.similarity, int(f.cross_split), int(f.conflicting_label),
                    roots.get(uf.find(f.a_idx)), jdump(f.detail),
                )
                for f in findings
            ],
        )

    inventory = build_inventory(
        samples,
        [{"path": r.path, "reason": r.reason} for r in extract.rejected],
    )
    issues = build_dataset_issues(inventory)
    with write_tx() as conn:
        conn.execute("DELETE FROM dataset_issues WHERE job_id=?", (job_id,))
        conn.executemany(
            "INSERT INTO dataset_issues (job_id,id,kind,severity,title,detail_json) VALUES (?,?,?,?,?,?)",
            [(job_id, i["id"], i["kind"], i["severity"], i["title"], jdump(i["detail"])) for i in issues],
        )

    score = compute_integrity_score(inventory, findings)

    summary = {
        "inventory": inventory,
        "integrity": score.to_dict(),
        "config": cfg,
        "backend_note": backend_note,
        "embedding_backend": backend_info,
        "counts": {
            "findings_total": len(findings),
            "exact_cross_split": sum(1 for f in findings if f.kind.value == "exact_cross_split_leakage"),
            "near_cross_split": sum(1 for f in findings if f.kind.value == "near_duplicate_cross_split_leakage"),
            "semantic_overlap": sum(1 for f in findings if f.kind.value == "possible_semantic_overlap"),
            "conflicting_label": sum(1 for f in findings if f.kind.value == "conflicting_label_duplicate"),
            "same_split_redundancy": sum(1 for f in findings if f.kind.value == "same_split_redundancy"),
            "corrupt": inventory["total_corrupt_samples"],
        },
        "severity_counts": {
            sev: sum(1 for f in findings if f.severity.value == sev)
            for sev in ("critical", "high", "medium", "low", "info")
        },
    }

    # ---- Stage: evaluation -------------------------------------------------------
    eval_result = {"eligible": False, "reason": "Evaluation disabled in configuration."}
    if cfg["run_evaluation"]:
        _set_stage(job_id, Stage.EVALUATION, 0.82, "Running diagnostic classifier")
        if embeddings is None:
            eval_result = {
                "eligible": False,
                "reason": "No embedding backend available for the diagnostic classifier.",
            }
        else:
            eval_result = run_evaluation_gap(samples, embeddings, findings, {})

    # ---- Stage: report -------------------------------------------------------
    _set_stage(job_id, Stage.REPORT, 0.92, "Building repair plan")
    repair = build_repair_plan(samples, findings, {})

    _update_job(
        job_id,
        summary_json=jdump(summary),
        eval_json=jdump(eval_result),
        repair_json=jdump(repair.to_dict()),
        fingerprint=fingerprint,
    )
    _set_stage(job_id, Stage.COMPLETE, 1.0, "Audit complete")


# --------------------------------------------------------------------------
# Post-hoc recomputation (review decisions change repair + eval, not evidence)
# --------------------------------------------------------------------------


def load_samples(job_id: str):
    """Reload SampleRecords from the DB (paths included) for recomputation."""
    from .domain import Split  # noqa: PLC0415
    from .pipeline.indexing import SampleRecord  # noqa: PLC0415

    rows = get_conn().execute(
        "SELECT * FROM samples WHERE job_id=? ORDER BY id", (job_id,)
    ).fetchall()
    job = get_job(job_id)
    storage = Path(job["storage_path"]) if job and job["storage_path"] else None
    out = []
    for r in rows:
        ext = Path(r["rel_path"]).suffix.lower()
        stored = (
            storage / "dataset" / r["split"] / f"{r['id']}{ext}" if storage else Path(".")
        )
        if storage and not stored.exists():
            # Demo datasets keep their original tree.
            candidate = storage / "dataset" / r["rel_path"]
            if candidate.exists():
                stored = candidate
        out.append(
            SampleRecord(
                id=r["id"], split=Split(r["split"]), label=r["label"], rel_path=r["rel_path"],
                stored_path=stored, sha256=r["sha256"], phash=r["phash"], width=r["width"],
                height=r["height"], bytes=r["bytes"] or 0, img_format=r["img_format"],
                corrupt=bool(r["corrupt"]), error=r["error"],
            )
        )
    return out


def load_findings(job_id: str):
    from .domain import ConfidenceLabel, FindingKind, Method, Severity  # noqa: PLC0415
    from .pipeline.classify import PairFinding  # noqa: PLC0415

    samples = get_conn().execute(
        "SELECT id FROM samples WHERE job_id=? ORDER BY id", (job_id,)
    ).fetchall()
    index_of = {r["id"]: i for i, r in enumerate(samples)}
    rows = get_conn().execute("SELECT * FROM findings WHERE job_id=?", (job_id,)).fetchall()
    out = []
    for r in rows:
        out.append(
            PairFinding(
                id=r["id"], kind=FindingKind(r["kind"]), severity=Severity(r["severity"]),
                confidence_label=ConfidenceLabel(r["confidence_label"]), method=Method(r["method"]),
                a_idx=index_of[r["sample_a"]], b_idx=index_of[r["sample_b"]],
                distance=r["distance"] or 0.0, similarity=r["similarity"] or 0.0,
                cross_split=bool(r["cross_split"]), conflicting_label=bool(r["conflicting_label"]),
                detail=jload(r["detail_json"], {}),
            )
        )
    return out


def get_reviews(job_id: str) -> dict[str, str]:
    rows = get_conn().execute(
        "SELECT finding_id, decision FROM reviews WHERE job_id=?", (job_id,)
    ).fetchall()
    return {r["finding_id"]: r["decision"] for r in rows}


def recompute_repair(job_id: str, include_semantic: bool = False) -> dict:
    samples = load_samples(job_id)
    findings = load_findings(job_id)
    reviews = get_reviews(job_id)
    plan = build_repair_plan(samples, findings, reviews, include_semantic=include_semantic)
    _update_job(job_id, repair_json=jdump(plan.to_dict()))
    return plan.to_dict()


def recompute_evaluation(job_id: str) -> dict:
    """Re-run the evaluation-gap experiment honouring current review decisions."""
    job = get_job(job_id)
    if job is None:
        return {"eligible": False, "reason": "Job not found."}
    samples = load_samples(job_id)
    findings = load_findings(job_id)
    reviews = get_reviews(job_id)

    embeddings = _embedding_cache.get(job_id)
    if embeddings is None:
        provider, _ = get_provider(settings.embedding_backend, settings.embedding_batch_size)
        if provider is None:
            return {"eligible": False, "reason": "No embedding backend available."}
        missing = [s for s in samples if not s.stored_path.exists() and not s.corrupt]
        if missing:
            return {
                "eligible": False,
                "reason": "Uploaded images have been purged by retention; re-run the audit.",
            }
        embeddings = provider.embed_paths([s.stored_path for s in samples])
        _embedding_cache[job_id] = embeddings

    result = run_evaluation_gap(samples, embeddings, findings, reviews)
    _update_job(job_id, eval_json=jdump(result))
    return result


# --------------------------------------------------------------------------
# Deletion and retention
# --------------------------------------------------------------------------


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job is None:
        return False
    storage = job.get("storage_path")
    if storage:
        shutil.rmtree(storage, ignore_errors=True)
    _embedding_cache.pop(job_id, None)
    with write_tx() as conn:
        conn.execute("DELETE FROM samples WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM findings WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM reviews WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM dataset_issues WHERE job_id=?", (job_id,))
        conn.execute(
            "UPDATE jobs SET deleted=1, status=?, summary_json=NULL, eval_json=NULL, "
            "repair_json=NULL, storage_path=NULL WHERE id=?",
            (JobStatus.DELETED.value, job_id),
        )
    return True


def sweep_expired() -> int:
    """Delete jobs past their retention deadline. Returns count removed."""
    now = _iso(_now())
    rows = get_conn().execute(
        "SELECT id FROM jobs WHERE deleted=0 AND expires_at < ?", (now,)
    ).fetchall()
    for row in rows:
        delete_job(row["id"])
    return len(rows)
