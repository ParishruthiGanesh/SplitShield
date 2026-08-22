"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, type JobStatus, type Summary } from "@/lib/api";
import Dashboard from "@/components/dashboard";
import EvidenceExplorer from "@/components/evidence-explorer";
import RepairStudio from "@/components/repair-studio";
import ReportPanel from "@/components/report-panel";

type Tab = "dashboard" | "evidence" | "repair" | "report";

const TABS: { key: Tab; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "evidence", label: "Evidence Explorer" },
  { key: "repair", label: "Repair Studio" },
  { key: "report", label: "Report" },
];

export default function AuditClient({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [evidenceFilter, setEvidenceFilter] = useState<Record<string, string>>({});

  const refreshSummary = useCallback(() => {
    api.summary(jobId).then(setSummary).catch(() => undefined);
  }, [jobId]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await api.jobStatus(jobId);
        if (cancelled) return;
        setStatus(s);
        if (s.status === "complete") {
          refreshSummary();
        } else if (s.status === "queued" || s.status === "running") {
          timer = setTimeout(poll, 1200);
        }
      } catch (e) {
        if (!cancelled && e instanceof ApiError && e.status === 404) setNotFound(true);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, refreshSummary]);

  const openEvidence = (filter: Record<string, string>) => {
    setEvidenceFilter(filter);
    setTab("evidence");
  };

  const deleteAudit = async () => {
    if (!window.confirm("Delete this audit and all uploaded data immediately?")) return;
    await api.deleteAudit(jobId);
    router.push("/upload");
  };

  if (notFound) {
    return (
      <div className="pt-20 text-center">
        <h1 className="text-2xl font-bold">Audit not found</h1>
        <p className="mt-2 text-muted">It may have been deleted or expired by retention.</p>
      </div>
    );
  }

  if (!status) {
    return <p className="pt-20 text-center text-muted animate-pulse-soft">Connecting…</p>;
  }

  if (status.status === "failed") {
    return (
      <div className="mx-auto max-w-xl pt-20 text-center">
        <h1 className="text-2xl font-bold text-danger">Audit failed</h1>
        <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm">
          {status.error ?? "Unknown error."}
        </p>
        <p className="mt-4 text-sm text-muted">
          Check the dataset layout (train/&lt;class&gt;/image.jpg) and try again.
        </p>
      </div>
    );
  }

  if (status.status !== "complete" || !summary) {
    return <ProgressView status={status} />;
  }

  return (
    <div className="pt-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {status.dataset_name ?? "Dataset audit"}
          </h1>
          <p className="mt-0.5 text-xs text-muted">
            {status.job_id} · created {new Date(status.created_at).toLocaleString()} ·
            auto-deletes {new Date(status.expires_at).toLocaleString()}
          </p>
        </div>
        <button
          type="button"
          onClick={deleteAudit}
          className="rounded-lg border border-danger/40 px-3 py-1.5 text-sm text-danger transition hover:bg-danger/10"
        >
          Delete my audit
        </button>
      </div>

      <div role="tablist" aria-label="Audit sections" className="mt-6 flex gap-1 border-b border-edge">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-t-lg px-4 py-2 text-sm font-medium transition ${
              tab === t.key
                ? "border border-b-0 border-edge bg-raised text-accent"
                : "text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="pt-6">
        {tab === "dashboard" && (
          <Dashboard summary={summary} onDrillDown={openEvidence} jobId={jobId} />
        )}
        {tab === "evidence" && (
          <EvidenceExplorer
            jobId={jobId}
            initialFilter={evidenceFilter}
            onReviewChanged={refreshSummary}
          />
        )}
        {tab === "repair" && <RepairStudio jobId={jobId} />}
        {tab === "report" && <ReportPanel jobId={jobId} summary={summary} />}
      </div>
    </div>
  );
}

function ProgressView({ status }: { status: JobStatus }) {
  return (
    <div className="mx-auto max-w-lg pt-20">
      <h1 className="text-center text-2xl font-bold">Analyzing dataset…</h1>
      <p className="mt-1 text-center text-sm text-muted">{status.message ?? status.stage_label}</p>

      <div
        role="progressbar"
        aria-valuenow={Math.round(status.progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-6 h-2 overflow-hidden rounded-full bg-panel"
      >
        <div
          className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: `${Math.max(3, status.progress * 100)}%` }}
        />
      </div>

      <ol className="mt-8 space-y-2">
        {status.stages.map((stage) => (
          <li key={stage.key} className="flex items-center gap-3 text-sm">
            <span
              aria-hidden="true"
              className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${
                stage.state === "complete"
                  ? "border-ok bg-ok/20 text-ok"
                  : stage.state === "active"
                    ? "border-accent text-accent animate-pulse-soft"
                    : "border-edge text-muted"
              }`}
            >
              {stage.state === "complete" ? "✓" : "•"}
            </span>
            <span className={stage.state === "pending" ? "text-muted" : ""}>{stage.label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
