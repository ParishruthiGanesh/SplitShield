"""SplitShield API.

All endpoints are documented via OpenAPI at ``/docs``. Errors use FastAPI's
standard ``{"detail": ...}`` envelope with meaningful status codes.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import jobs as jobs_mod
from .config import ensure_dirs, settings
from .db import get_conn, init_db, jdump, jload, write_tx
from .domain import STAGE_LABELS, STAGE_ORDER, JobStatus, Stage
from .report import build_report_html, build_report_json, findings_csv, repair_csv
from .schemas import (
    AuditConfigIn,
    JobCreated,
    JobStatusOut,
    RepairOptionsIn,
    ReviewIn,
)

logger = logging.getLogger("splitshield")

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    init_db()

    async def retention_loop() -> None:
        while True:
            try:
                removed = jobs_mod.sweep_expired()
                if removed:
                    logger.info("Retention sweep removed %d expired audit(s)", removed)
            except Exception:
                logger.exception("Retention sweep failed")
            await asyncio.sleep(settings.retention_sweep_seconds)

    task = asyncio.create_task(retention_loop())
    yield
    task.cancel()


app = FastAPI(
    title="SplitShield API",
    version=API_VERSION,
    description=(
        "Detect, repair, and quantify hidden leakage in computer-vision datasets. "
        "All analysis runs locally; uploads are retained only for the configured "
        "retention window and can be deleted at any time."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


def _job_or_404(job_id: str) -> dict:
    job = jobs_mod.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Audit not found (it may have been deleted).")
    return job


def _complete_job_or_409(job_id: str) -> dict:
    job = _job_or_404(job_id)
    if job["status"] != JobStatus.COMPLETE.value:
        raise HTTPException(
            status_code=409,
            detail=f"Audit is not complete (status: {job['status']}).",
        )
    return job


# ---------------------------------------------------------------------------
# Health & meta
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness/readiness probe."""
    get_conn().execute("SELECT 1").fetchone()
    return {"status": "ok", "version": API_VERSION}


@app.get("/api/capabilities", tags=["meta"])
def capabilities() -> dict:
    """What the current deployment can and cannot do (honest feature flags)."""
    from .pipeline.embeddings import get_provider  # noqa: PLC0415

    provider, note = get_provider(settings.embedding_backend)
    return {
        "version": API_VERSION,
        "embedding_backend": provider.info.__dict__ if provider else None,
        "embedding_note": note,
        "video_support": False,
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_file_count": settings.max_file_count,
            "max_uncompressed_bytes": settings.max_uncompressed_bytes,
            "retention_hours": settings.retention_hours,
        },
        "defaults": {
            "phash_threshold": settings.phash_threshold,
            "phash_strong_threshold": settings.phash_strong_threshold,
            "semantic_threshold": settings.semantic_threshold,
            "semantic_top_k": settings.semantic_top_k,
        },
    }


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------


@app.post("/api/audits/upload", response_model=JobCreated, status_code=202, tags=["audits"])
async def create_audit_from_upload(
    file: UploadFile = File(...),
    config: str | None = None,
) -> JobCreated:
    """Create an audit from an uploaded ZIP dataset.

    ``config`` is an optional JSON-encoded ``AuditConfigIn`` (multipart forms
    cannot carry nested JSON bodies cleanly).
    """
    cfg_model = AuditConfigIn()
    if config:
        try:
            cfg_model = AuditConfigIn.model_validate_json(config)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid config: {exc}") from exc

    filename = file.filename or "dataset.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=415, detail="Only ZIP archives are accepted.")

    ensure_dirs()
    tmp_name = f"up_{secrets.token_urlsafe(10)}.zip"
    tmp_path = settings.uploads_dir / tmp_name

    written = 0
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Upload exceeds the "
                            f"{settings.max_upload_bytes // (1024 * 1024)} MiB limit."
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to store upload.") from exc

    if written == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    job_id = jobs_mod.create_job("upload", filename, cfg_model.model_dump())
    jobs_mod.run_audit_async(job_id, tmp_path, demo=False)
    return JobCreated(job_id=job_id, status="queued")


@app.post("/api/audits/demo", response_model=JobCreated, status_code=202, tags=["audits"])
def create_audit_from_demo(config: AuditConfigIn | None = None) -> JobCreated:
    """Create an audit of the built-in synthetic demonstration dataset.

    The demo runs through exactly the same pipeline as uploads; nothing is
    precomputed.
    """
    cfg = (config or AuditConfigIn()).model_dump()
    job_id = jobs_mod.create_job("demo", "SplitShield synthetic demo", cfg)
    jobs_mod.run_audit_async(job_id, None, demo=True)
    return JobCreated(job_id=job_id, status="queued")


# ---------------------------------------------------------------------------
# Job status and results
# ---------------------------------------------------------------------------


@app.get("/api/audits/{job_id}", response_model=JobStatusOut, tags=["audits"])
def get_audit_status(job_id: str) -> JobStatusOut:
    job = _job_or_404(job_id)
    current = job["stage"]
    reached = True
    stages = []
    for stage in STAGE_ORDER:
        if stage is Stage.QUEUED:
            continue
        stages.append(
            {
                "key": stage.value,
                "label": STAGE_LABELS[stage],
                "state": (
                    "complete"
                    if not reached or job["status"] == JobStatus.COMPLETE.value
                    else ("active" if stage.value == current else "pending")
                ),
            }
        )
        if stage.value == current:
            reached = False
    return JobStatusOut(
        job_id=job["id"],
        status=job["status"],
        stage=job["stage"],
        stage_label=STAGE_LABELS.get(Stage(job["stage"]), job["stage"]),
        stages=stages,
        progress=job["progress"],
        message=job["message"],
        error=job["error"],
        source=job["source"],
        dataset_name=job["dataset_name"],
        created_at=job["created_at"],
        expires_at=job["expires_at"],
    )


@app.get("/api/audits/{job_id}/summary", tags=["audits"])
def get_audit_summary(job_id: str) -> JSONResponse:
    job = _complete_job_or_409(job_id)
    summary = jload(job["summary_json"], {})
    reviews = jobs_mod.get_reviews(job_id)
    summary["review_counts"] = {
        "confirmed": sum(1 for v in reviews.values() if v == "confirmed"),
        "safe": sum(1 for v in reviews.values() if v == "safe"),
        "uncertain": sum(1 for v in reviews.values() if v == "uncertain"),
    }
    summary["evaluation"] = jload(job["eval_json"], None)
    summary["fingerprint"] = job["fingerprint"]
    issues = get_conn().execute(
        "SELECT * FROM dataset_issues WHERE job_id=?", (job_id,)
    ).fetchall()
    summary["dataset_issues"] = [
        {
            "id": r["id"], "kind": r["kind"], "severity": r["severity"],
            "title": r["title"], "detail": jload(r["detail_json"], {}),
        }
        for r in issues
    ]
    return JSONResponse(summary)


_SORTABLE = {"similarity", "severity"}


@app.get("/api/audits/{job_id}/findings", tags=["findings"])
def list_findings(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    severity: str | None = None,
    kind: str | None = None,
    split_pair: str | None = Query(None, description="e.g. train-test"),
    label: str | None = None,
    method: str | None = None,
    review: str | None = Query(None, description="unreviewed|confirmed|safe|uncertain"),
    sort: str = Query("severity", description="severity|similarity"),
) -> dict:
    """Paginated, filterable findings for the Evidence Explorer."""
    _complete_job_or_409(job_id)
    if sort not in _SORTABLE:
        raise HTTPException(status_code=422, detail=f"sort must be one of {sorted(_SORTABLE)}")

    where = ["f.job_id = ?"]
    params: list = [job_id]
    if severity:
        where.append("f.severity = ?")
        params.append(severity)
    if kind:
        where.append("f.kind = ?")
        params.append(kind)
    if method:
        where.append("f.method = ?")
        params.append(method)
    if label:
        where.append("(f.class_a = ? OR f.class_b = ?)")
        params.extend([label, label])
    if split_pair:
        parts = sorted(split_pair.split("-"))
        if len(parts) != 2:
            raise HTTPException(status_code=422, detail="split_pair must look like 'train-test'.")
        where.append(
            "((f.split_a = ? AND f.split_b = ?) OR (f.split_a = ? AND f.split_b = ?))"
        )
        params.extend([parts[0], parts[1], parts[1], parts[0]])
    if review:
        if review == "unreviewed":
            where.append("r.decision IS NULL")
        else:
            where.append("r.decision = ?")
            params.append(review)

    order = (
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, f.similarity DESC"
        if sort == "severity"
        else "ORDER BY f.similarity DESC"
    )

    base = (
        "FROM findings f LEFT JOIN reviews r "
        "ON r.job_id = f.job_id AND r.finding_id = f.id WHERE " + " AND ".join(where)
    )
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) AS n {base}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT f.*, r.decision AS review_decision, r.note AS review_note {base} {order} "
        "LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()

    sample_ids = {r["sample_a"] for r in rows} | {r["sample_b"] for r in rows}
    samples = {}
    if sample_ids:
        placeholders = ",".join("?" * len(sample_ids))
        for s in conn.execute(
            f"SELECT * FROM samples WHERE job_id=? AND id IN ({placeholders})",
            [job_id, *sample_ids],
        ).fetchall():
            samples[s["id"]] = {
                "id": s["id"], "split": s["split"], "label": s["label"],
                "width": s["width"], "height": s["height"], "bytes": s["bytes"],
                "corrupt": bool(s["corrupt"]),
            }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r["id"], "kind": r["kind"], "severity": r["severity"],
                "confidence_label": r["confidence_label"], "method": r["method"],
                "distance": r["distance"], "similarity": r["similarity"],
                "cross_split": bool(r["cross_split"]),
                "conflicting_label": bool(r["conflicting_label"]),
                "group_id": r["group_id"],
                "detail": jload(r["detail_json"], {}),
                "sample_a": samples.get(r["sample_a"], {"id": r["sample_a"]}),
                "sample_b": samples.get(r["sample_b"], {"id": r["sample_b"]}),
                "split_a": r["split_a"], "split_b": r["split_b"],
                "class_a": r["class_a"], "class_b": r["class_b"],
                "review": {"decision": r["review_decision"] or "unreviewed", "note": r["review_note"]},
            }
            for r in rows
        ],
    }


@app.get("/api/audits/{job_id}/images/{sample_id}", tags=["findings"])
def get_sample_image(job_id: str, sample_id: str) -> FileResponse:
    """Serve one sample image for the evidence viewer.

    Paths are reconstructed from the sample's stored internal id - user input
    never touches the filesystem path.
    """
    job = _job_or_404(job_id)
    if not job["storage_path"]:
        raise HTTPException(status_code=410, detail="Audit data has been deleted.")
    row = get_conn().execute(
        "SELECT * FROM samples WHERE job_id=? AND id=?", (job_id, sample_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Sample not found.")

    storage = Path(job["storage_path"]) / "dataset"
    ext = Path(row["rel_path"]).suffix.lower()
    candidates = [
        storage / row["split"] / f"{row['id']}{ext}",
        storage / row["rel_path"],  # demo layout keeps original tree
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if not str(resolved).startswith(str(storage.resolve())):
            continue
        if resolved.exists():
            media = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
            }.get(ext, "application/octet-stream")
            return FileResponse(resolved, media_type=media)
    raise HTTPException(status_code=410, detail="Image no longer available (retention or deletion).")


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


@app.patch("/api/audits/{job_id}/findings/{finding_id}/review", tags=["findings"])
def update_review(job_id: str, finding_id: str, body: ReviewIn) -> dict:
    """Record a human-review decision. Algorithmic evidence is never modified."""
    _complete_job_or_409(job_id)
    exists = get_conn().execute(
        "SELECT 1 FROM findings WHERE job_id=? AND id=?", (job_id, finding_id)
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Finding not found.")

    from datetime import datetime, timezone  # noqa: PLC0415

    now = datetime.now(timezone.utc).isoformat()
    with write_tx() as conn:
        if body.decision == "unreviewed":
            conn.execute(
                "DELETE FROM reviews WHERE job_id=? AND finding_id=?", (job_id, finding_id)
            )
        else:
            conn.execute(
                """INSERT INTO reviews (job_id, finding_id, decision, note, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(job_id, finding_id)
                   DO UPDATE SET decision=excluded.decision, note=excluded.note,
                                 updated_at=excluded.updated_at""",
                (job_id, finding_id, body.decision, body.note, now),
            )
    return {"finding_id": finding_id, "decision": body.decision, "note": body.note}


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


@app.post("/api/audits/{job_id}/repair", tags=["repair"])
def regenerate_repair(job_id: str, body: RepairOptionsIn) -> dict:
    """Recompute the repair proposal honouring current review decisions."""
    _complete_job_or_409(job_id)
    return jobs_mod.recompute_repair(job_id, include_semantic=body.include_semantic)


@app.get("/api/audits/{job_id}/repair", tags=["repair"])
def get_repair(job_id: str) -> dict:
    job = _complete_job_or_409(job_id)
    plan = jload(job["repair_json"], None)
    if plan is None:
        raise HTTPException(status_code=404, detail="No repair plan available.")
    return plan


@app.get("/api/audits/{job_id}/repair.csv", response_class=PlainTextResponse, tags=["repair"])
def export_repair_csv(job_id: str) -> PlainTextResponse:
    job = _complete_job_or_409(job_id)
    plan = jload(job["repair_json"], None)
    if plan is None:
        raise HTTPException(status_code=404, detail="No repair plan available.")
    return PlainTextResponse(
        repair_csv(plan),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_repair.csv"'},
    )


@app.get("/api/audits/{job_id}/repair.json", tags=["repair"])
def export_repair_json(job_id: str) -> JSONResponse:
    job = _complete_job_or_409(job_id)
    plan = jload(job["repair_json"], None)
    if plan is None:
        raise HTTPException(status_code=404, detail="No repair plan available.")
    return JSONResponse(
        plan,
        headers={"Content-Disposition": f'attachment; filename="{job_id}_repair.json"'},
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@app.post("/api/audits/{job_id}/evaluation/rerun", tags=["evaluation"])
def rerun_evaluation(job_id: str) -> dict:
    """Re-run the diagnostic experiment honouring current review decisions."""
    _complete_job_or_409(job_id)
    return jobs_mod.recompute_evaluation(job_id)


# ---------------------------------------------------------------------------
# Exports & report
# ---------------------------------------------------------------------------


@app.get("/api/audits/{job_id}/findings.csv", response_class=PlainTextResponse, tags=["export"])
def export_findings_csv(job_id: str) -> PlainTextResponse:
    _complete_job_or_409(job_id)
    return PlainTextResponse(
        findings_csv(job_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{job_id}_findings.csv"'},
    )


@app.get("/api/audits/{job_id}/report.json", tags=["export"])
def export_report_json(job_id: str) -> JSONResponse:
    _complete_job_or_409(job_id)
    return JSONResponse(
        build_report_json(job_id),
        headers={"Content-Disposition": f'attachment; filename="{job_id}_report.json"'},
    )


@app.get("/api/audits/{job_id}/report.html", response_class=PlainTextResponse, tags=["export"])
def export_report_html(job_id: str) -> PlainTextResponse:
    """Printable HTML audit report (use the browser's print-to-PDF)."""
    _complete_job_or_409(job_id)
    return PlainTextResponse(build_report_html(job_id), media_type="text/html")


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


@app.delete("/api/audits/{job_id}", status_code=200, tags=["audits"])
def delete_audit(job_id: str) -> dict:
    """Delete an audit and all uploaded/extracted data immediately."""
    if not jobs_mod.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Audit not found.")
    return {"deleted": job_id}
