"""Audit report and CSV exports.

The report is a self-contained printable HTML document (browser print-to-PDF
gives a faithful PDF). Every value in it comes from the persisted analysis
results - nothing is recomputed or invented at render time.
"""
from __future__ import annotations

import csv
import html
import io
import platform
from datetime import datetime, timezone

from .config import settings
from .db import get_conn, jload


def _versions() -> dict:
    import numpy
    import PIL
    import sklearn

    import imagehash

    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pillow": PIL.__version__,
        "imagehash": imagehash.__version__,
        "scikit-learn": sklearn.__version__,
    }


def _job(job_id: str) -> dict:
    row = get_conn().execute("SELECT * FROM jobs WHERE id=? AND deleted=0", (job_id,)).fetchone()
    if row is None:
        raise ValueError("Job not found")
    return dict(row)


def _findings(job_id: str) -> list[dict]:
    rows = get_conn().execute(
        """SELECT f.*, r.decision AS review_decision, r.note AS review_note
           FROM findings f
           LEFT JOIN reviews r ON r.job_id=f.job_id AND r.finding_id=f.id
           WHERE f.job_id=?
           ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
                    f.similarity DESC""",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def findings_csv(job_id: str) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "finding_id", "kind", "severity", "confidence_label", "method",
            "sample_a", "sample_b", "split_a", "split_b", "class_a", "class_b",
            "distance", "similarity", "cross_split", "conflicting_label",
            "group_id", "review_decision", "review_note",
        ]
    )
    for f in _findings(job_id):
        writer.writerow(
            [
                f["id"], f["kind"], f["severity"], f["confidence_label"], f["method"],
                f["sample_a"], f["sample_b"], f["split_a"], f["split_b"],
                f["class_a"], f["class_b"], f["distance"], f["similarity"],
                f["cross_split"], f["conflicting_label"], f["group_id"],
                f["review_decision"] or "unreviewed", f["review_note"] or "",
            ]
        )
    return out.getvalue()


def repair_csv(plan: dict) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["sample_id", "original_split", "proposed_split", "class", "group_id", "action", "reason"]
    )
    for e in plan.get("entries", []):
        writer.writerow(
            [
                e["sample_id"], e["original_split"], e["proposed_split"],
                e["label"], e["group_id"] or "", e["action"], e["reason"],
            ]
        )
    return out.getvalue()


def build_report_json(job_id: str) -> dict:
    job = _job(job_id)
    summary = jload(job["summary_json"], {})
    findings = _findings(job_id)
    reviews = {
        f["id"]: {"decision": f["review_decision"] or "unreviewed", "note": f["review_note"]}
        for f in findings
    }
    return {
        "report_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit": {
            "job_id": job["id"],
            "source": job["source"],
            "dataset_name": job["dataset_name"],
            "created_at": job["created_at"],
            "dataset_fingerprint_sha256": job["fingerprint"],
        },
        "configuration": jload(job["config_json"], {}),
        "environment": {
            "package_versions": _versions(),
            "random_seed": settings.random_seed,
            "embedding_backend": summary.get("embedding_backend"),
            "embedding_note": summary.get("backend_note"),
        },
        "summary": summary,
        "evaluation": jload(job["eval_json"], None),
        "repair_plan": jload(job["repair_json"], None),
        "findings": [
            {
                "id": f["id"], "kind": f["kind"], "severity": f["severity"],
                "confidence_label": f["confidence_label"], "method": f["method"],
                "sample_a": f["sample_a"], "sample_b": f["sample_b"],
                "split_a": f["split_a"], "split_b": f["split_b"],
                "class_a": f["class_a"], "class_b": f["class_b"],
                "distance": f["distance"], "similarity": f["similarity"],
                "cross_split": bool(f["cross_split"]),
                "conflicting_label": bool(f["conflicting_label"]),
                "review": reviews[f["id"]],
            }
            for f in findings
        ],
        "limitations": LIMITATIONS,
        "responsible_use": RESPONSIBLE_USE,
    }


LIMITATIONS = [
    "Perceptual hashing (pHash) is robust to rescaling and recompression but NOT to "
    "aggressive crops, rotations or flips; such variants may only surface via the "
    "embedding stage, or not at all.",
    "The similarity stage measures visual appearance. When the classical descriptor "
    "backend is active it does not capture conceptual similarity between visually "
    "different images.",
    "The Observed Evaluation Gap is computed with a diagnostic linear classifier on "
    "frozen embeddings; production models may be more or less sensitive to the same leakage.",
    "Findings below the configured thresholds are invisible; thresholds trade recall "
    "against review burden and require human validation.",
    "Only image classification datasets in the documented folder layout are supported.",
]

RESPONSIBLE_USE = [
    "SplitShield performs no facial recognition and no identity inference.",
    "Uploaded data never leaves the server; analysis is fully local.",
    "Uploads are deleted after the configured retention period or on demand.",
    "Only audit datasets you are legally permitted to process.",
]


def _fmt_ci(ci: dict | None) -> str:
    if not ci:
        return "n/a (sample too small)"
    return f"[{ci['low']:.3f}, {ci['high']:.3f}] ({ci['iterations']} bootstrap iterations)"


def build_report_html(job_id: str) -> str:
    data = build_report_json(job_id)
    summary = data["summary"]
    inv = summary.get("inventory", {})
    integrity = summary.get("integrity", {})
    ev = data.get("evaluation") or {}
    repair = data.get("repair_plan") or {}
    e = html.escape

    sev_counts = summary.get("severity_counts", {})
    counts = summary.get("counts", {})

    def row(label: str, value) -> str:
        return f"<tr><th>{e(str(label))}</th><td>{e(str(value))}</td></tr>"

    comp_rows = "".join(
        f"<tr><td>{e(c['category'])}</td><td>{c['weight']}</td>"
        f"<td>{c['affected_samples']}</td><td>{c['rate']}</td>"
        f"<td>{c['penalty']}</td><td class='muted'>{e(c['explanation'])}</td></tr>"
        for c in integrity.get("components", [])
    )

    finding_rows = "".join(
        f"<tr><td>{e(f['severity'])}</td><td>{e(f['kind'].replace('_', ' '))}</td>"
        f"<td>{e(f['confidence_label'])}</td><td>{e(f['method'])}</td>"
        f"<td>{e(f['sample_a'])} ({e(f['split_a'])}/{e(f['class_a'])})</td>"
        f"<td>{e(f['sample_b'])} ({e(f['split_b'])}/{e(f['class_b'])})</td>"
        f"<td>{f['similarity']:.3f}</td><td>{e(f['review']['decision'])}</td></tr>"
        for f in data["findings"][:400]
    )
    truncated_note = (
        f"<p class='muted'>Showing 400 of {len(data['findings'])} findings; "
        "the JSON/CSV exports contain the complete list.</p>"
        if len(data["findings"]) > 400
        else ""
    )

    eval_html = "<p class='muted'>Experiment not run.</p>"
    if ev:
        if not ev.get("eligible"):
            eval_html = f"<p><strong>Not run:</strong> {e(ev.get('reason', 'ineligible'))}</p>"
        else:
            orig = ev.get("original", {})
            clean = ev.get("cleaned")
            gap = ev.get("observed_evaluation_gap")
            eval_html = "<table>" + "".join(
                [
                    row("Model", ev.get("model", "")),
                    row("Random seed", ev.get("seed", "")),
                    row("Training samples", ev.get("train_samples", "")),
                    row("Original test samples", orig.get("test_samples", "")),
                    row("Original accuracy", orig.get("accuracy", "")),
                    row("Original macro-F1", orig.get("macro_f1", "")),
                    row("Original accuracy 95% CI", _fmt_ci(orig.get("accuracy_ci95"))),
                    row("Quarantined test samples", ev.get("quarantined_test_samples", 0)),
                ]
                + (
                    [
                        row("Cleaned test samples", clean.get("test_samples", "")),
                        row("Cleaned accuracy", clean.get("accuracy", "")),
                        row("Cleaned macro-F1", clean.get("macro_f1", "")),
                        row("Cleaned accuracy 95% CI", _fmt_ci(clean.get("accuracy_ci95"))),
                        row("Observed Evaluation Gap", gap),
                    ]
                    if clean
                    else [row("Cleaned evaluation", ev.get("note", "not applicable"))]
                )
            ) + "</table>"
            eval_html += (
                "<ul class='muted'>"
                + "".join(f"<li>{e(w)}</li>" for w in ev.get("warnings", []))
                + "</ul>"
            )

    versions = data["environment"]["package_versions"]
    backend = data["environment"].get("embedding_backend") or {}

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>SplitShield audit report - {e(job_id)}</title>
<style>
  body {{ font: 14px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif; color: #16202b;
         max-width: 960px; margin: 2rem auto; padding: 0 1.2rem; }}
  h1 {{ font-size: 1.6rem; border-bottom: 3px solid #0e7490; padding-bottom: .4rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 2rem; color: #0e7490; }}
  table {{ border-collapse: collapse; width: 100%; margin: .6rem 0; }}
  th, td {{ border: 1px solid #d3dbe2; padding: .35rem .55rem; text-align: left;
            vertical-align: top; font-size: .82rem; }}
  th {{ background: #f0f4f7; width: 240px; }}
  .muted {{ color: #5b6b7a; font-size: .8rem; }}
  .score {{ font-size: 2.4rem; font-weight: 700; }}
  .pill {{ display: inline-block; padding: .1rem .6rem; border-radius: 999px;
           background: #e0f2f7; color: #0e7490; font-weight: 600; }}
  @media print {{ body {{ margin: 0.5cm; max-width: none; }} h2 {{ page-break-after: avoid; }} }}
</style></head><body>
<h1>SplitShield Dataset Audit Report</h1>
<p class="muted">Generated {e(data["generated_at"])} · SplitShield report v{data["report_version"]}</p>

<h2>Audit metadata</h2>
<table>
{row("Audit ID", data["audit"]["job_id"])}
{row("Source", data["audit"]["source"])}
{row("Dataset name", data["audit"]["dataset_name"] or "n/a")}
{row("Created", data["audit"]["created_at"])}
{row("Dataset fingerprint (SHA-256 of content digests)", data["audit"]["dataset_fingerprint_sha256"] or "n/a")}
{row("Random seed", data["environment"]["random_seed"])}
</table>

<h2>Dataset summary</h2>
<table>
{row("Total samples", inv.get("total_samples", ""))}
{row("Valid samples", inv.get("total_valid_samples", ""))}
{row("Corrupt samples", inv.get("total_corrupt_samples", ""))}
{row("Rejected files", inv.get("rejected_count", ""))}
{row("Samples per split", inv.get("per_split", ""))}
{row("Samples per class", inv.get("per_class_total", ""))}
{row("Class imbalance ratio", inv.get("class_imbalance_ratio", "n/a"))}
{row("Test fraction", inv.get("test_fraction", ""))}
</table>

<h2>Dataset Integrity Score</h2>
<p><span class="score">{integrity.get("score", "?")}</span> / 100
   <span class="pill">{e(integrity.get("grade", ""))}</span></p>
<p class="muted">{e(integrity.get("formula", ""))}</p>
<table>
<tr><th>Category</th><th>Weight</th><th>Affected</th><th>Rate</th><th>Penalty</th><th>Explanation</th></tr>
{comp_rows}
</table>

<h2>Findings by severity</h2>
<table>
{row("Critical", sev_counts.get("critical", 0))}
{row("High", sev_counts.get("high", 0))}
{row("Medium", sev_counts.get("medium", 0))}
{row("Low", sev_counts.get("low", 0))}
{row("Exact cross-split leakage findings", counts.get("exact_cross_split", 0))}
{row("Near-duplicate cross-split findings", counts.get("near_cross_split", 0))}
{row("Conflicting-label findings", counts.get("conflicting_label", 0))}
{row("Possible-overlap findings", counts.get("semantic_overlap", 0))}
{row("Human reviews recorded", summary.get("review_counts", ""))}
</table>

<h2>Observed Evaluation Gap experiment</h2>
{eval_html}

<h2>Proposed repair summary</h2>
<table>
{row("Moves proposed", repair.get("moves", 0))}
{row("Exclusions proposed", repair.get("exclusions", 0))}
{row("Split counts before", repair.get("before_counts", ""))}
{row("Split counts after repair", repair.get("after_counts", ""))}
{row("Warnings", "; ".join(repair.get("warnings", []) or ["none"]))}
</table>
<p class="muted">Original files are never modified; the repair is a manifest of proposed moves.</p>

<h2>Findings detail</h2>
{truncated_note}
<table>
<tr><th>Severity</th><th>Kind</th><th>Confidence</th><th>Method</th>
<th>Sample A</th><th>Sample B</th><th>Similarity</th><th>Review</th></tr>
{finding_rows}
</table>

<h2>Analysis configuration</h2>
<table>
{"".join(row(k, v) for k, v in data["configuration"].items())}
{row("Embedding backend", backend.get("name", "disabled"))}
{row("Backend kind", backend.get("kind", "n/a"))}
{row("Backend note", data["environment"].get("embedding_note", ""))}
</table>

<h2>Environment</h2>
<table>
{"".join(row(k, v) for k, v in versions.items())}
</table>

<h2>Limitations</h2>
<ul>{"".join(f"<li>{e(item)}</li>" for item in data["limitations"])}</ul>

<h2>Privacy and responsible use</h2>
<ul>{"".join(f"<li>{e(item)}</li>" for item in data["responsible_use"])}</ul>
</body></html>"""
