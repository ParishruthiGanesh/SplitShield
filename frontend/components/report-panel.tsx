"use client";

import { useState } from "react";
import { api, type Summary } from "@/lib/api";
import { Card } from "./ui";

export default function ReportPanel({
  jobId,
  summary,
}: {
  jobId: string;
  summary: Summary;
}) {
  const [rerunning, setRerunning] = useState(false);
  const [rerunNote, setRerunNote] = useState<string | null>(null);

  const rerunEval = async () => {
    setRerunning(true);
    setRerunNote(null);
    try {
      const result = await api.rerunEvaluation(jobId);
      setRerunNote(
        result.eligible
          ? `Re-run complete. Observed gap: ${
              result.observed_evaluation_gap != null
                ? `${(result.observed_evaluation_gap * 100).toFixed(1)} points`
                : "n/a"
            } with ${result.quarantined_test_samples} quarantined test sample(s). Reload the dashboard tab to see updated numbers.`
          : `Experiment not run: ${result.reason}`,
      );
    } catch {
      setRerunNote("Re-run failed — the uploaded images may have been purged by retention.");
    } finally {
      setRerunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card title="Audit report">
        <p className="text-sm text-muted">
          The report contains every value shown in this UI — audit metadata, the dataset
          fingerprint, the full Integrity-Score breakdown, findings with review status,
          the evaluation-gap experiment (seed, sample counts, confidence intervals), the
          proposed repair, package versions, limitations and responsible-use notes.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <a
            href={api.reportHtmlUrl(jobId)}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-bg transition hover:brightness-110"
          >
            Open printable report
          </a>
          <a
            href={api.reportJsonUrl(jobId)}
            download
            className="rounded-lg border border-edge px-5 py-2.5 text-sm font-medium transition hover:border-accent-dim"
          >
            Download JSON report
          </a>
          <a
            href={api.findingsCsvUrl(jobId)}
            download
            className="rounded-lg border border-edge px-5 py-2.5 text-sm font-medium transition hover:border-accent-dim"
          >
            Download findings CSV
          </a>
        </div>
        <p className="mt-3 text-xs text-muted">
          For a PDF: open the printable report and use your browser&apos;s “Print → Save
          as PDF”. The layout is print-optimised.
        </p>
      </Card>

      <Card title="Re-run evaluation with your review decisions">
        <p className="text-sm text-muted">
          The initial experiment quarantines only algorithmically strong leakage (exact
          matches and strong perceptual matches). After you confirm or clear findings in
          the Evidence Explorer, re-run it so your decisions are honoured: confirmed
          findings join the quarantine list, findings marked safe leave it.
        </p>
        <button
          type="button"
          onClick={() => void rerunEval()}
          disabled={rerunning}
          className="mt-3 rounded-lg border border-accent-dim px-4 py-2 text-sm font-medium text-accent transition enabled:hover:bg-accent/10 disabled:opacity-40"
        >
          {rerunning ? "Re-running…" : "Re-run evaluation experiment"}
        </button>
        {rerunNote && <p className="mt-3 text-sm text-warn">{rerunNote}</p>}
      </Card>

      <Card title="Reproducibility">
        <dl className="grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
          <Row label="Dataset fingerprint" value={summary.fingerprint ?? "n/a"} mono />
          <Row
            label="Similarity backend"
            value={summary.embedding_backend?.name ?? "disabled"}
          />
          <Row
            label="Reviews recorded"
            value={`${summary.review_counts.confirmed} confirmed · ${summary.review_counts.safe} safe · ${summary.review_counts.uncertain} uncertain`}
          />
          <Row
            label="Analysis config"
            value={Object.entries(summary.config)
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(" · ")}
          />
        </dl>
      </Card>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col border-b border-edge/40 pb-1.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`break-all ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}
