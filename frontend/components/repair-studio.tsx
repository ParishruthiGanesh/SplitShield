"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type RepairPlan } from "@/lib/api";
import { Card, SplitBadge } from "./ui";

export default function RepairStudio({ jobId }: { jobId: string }) {
  const [plan, setPlan] = useState<RepairPlan | null>(null);
  const [includeSemantic, setIncludeSemantic] = useState(false);
  const [busy, setBusy] = useState(false);

  const regenerate = useCallback(
    async (semantic: boolean) => {
      setBusy(true);
      try {
        setPlan(await api.regenerateRepair(jobId, semantic));
      } finally {
        setBusy(false);
      }
    },
    [jobId],
  );

  useEffect(() => {
    // Always regenerate on mount so current review decisions are honoured.
    void regenerate(false);
  }, [regenerate]);

  if (!plan) {
    return <p className="py-16 text-center text-muted animate-pulse-soft">Building repair plan…</p>;
  }

  const changed = plan.entries.filter((e) => e.action !== "keep");

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-edge bg-panel p-4 text-sm">
        <p>
          <strong>Nothing is modified in place.</strong> SplitShield proposes a repair
          manifest — a list of per-sample moves and exclusions with reasons. Your
          original archive and files are untouched; apply the manifest with your own
          tooling (each row carries the original archive path).
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeSemantic}
            disabled={busy}
            onChange={(e) => {
              setIncludeSemantic(e.target.checked);
              void regenerate(e.target.checked);
            }}
            className="h-4 w-4 accent-[var(--accent)]"
          />
          Include <em>unreviewed</em> possible-overlap matches in grouping
        </label>
        <span className="text-xs text-muted">
          (Findings you marked “safe” are always excluded; ones you “confirmed” are
          always included.)
        </span>
        <div className="ml-auto flex gap-2">
          <a
            href={api.repairCsvUrl(jobId)}
            className="rounded-lg border border-accent-dim px-4 py-2 text-sm font-medium text-accent transition hover:bg-accent/10"
            download
          >
            Export CSV manifest
          </a>
          <a
            href={api.repairJsonUrl(jobId)}
            className="rounded-lg border border-edge px-4 py-2 text-sm font-medium transition hover:border-accent-dim"
            download
          >
            Export JSON
          </a>
        </div>
      </div>

      {plan.warnings.length > 0 && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
          {plan.warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}

      {/* Before / after */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Split counts — before → after">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted">
              <tr>
                <th className="py-1.5">Split</th>
                <th className="py-1.5">Before</th>
                <th className="py-1.5">After repair</th>
                <th className="py-1.5">Δ</th>
              </tr>
            </thead>
            <tbody>
              {Array.from(
                new Set([
                  ...Object.keys(plan.before_counts),
                  ...Object.keys(plan.after_counts),
                ]),
              )
                .sort()
                .map((split) => {
                  const before = plan.before_counts[split] ?? 0;
                  const after = plan.after_counts[split] ?? 0;
                  return (
                    <tr key={split} className="border-t border-edge/60">
                      <td className="py-1.5">
                        <SplitBadge split={split} />
                      </td>
                      <td className="py-1.5 tabular-nums">{before}</td>
                      <td className="py-1.5 tabular-nums">{after}</td>
                      <td
                        className={`py-1.5 tabular-nums ${
                          after < before ? "text-warn" : after > before ? "text-ok" : "text-muted"
                        }`}
                      >
                        {after - before >= 0 ? `+${after - before}` : after - before}
                      </td>
                    </tr>
                  );
                })}
              <tr className="border-t border-edge/60 text-muted">
                <td className="py-1.5">excluded</td>
                <td className="py-1.5">—</td>
                <td className="py-1.5 tabular-nums">{plan.exclusions}</td>
                <td className="py-1.5" />
              </tr>
            </tbody>
          </table>
        </Card>

        <Card title="Summary">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted">Duplicate groups formed</dt>
              <dd className="font-medium tabular-nums">{plan.groups.length}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Samples moved</dt>
              <dd className="font-medium tabular-nums">{plan.moves}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Samples excluded</dt>
              <dd className="font-medium tabular-nums">{plan.exclusions}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Samples untouched</dt>
              <dd className="font-medium tabular-nums">
                {plan.entries.length - changed.length}
              </dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted">
            Repair strategy: duplicate groups are consolidated into a single split,
            preferring to keep the <strong>test set clean</strong> (groups move out of
            test into train unless majority-test). Conflicting-label groups are excluded
            pending human labeling.
          </p>
        </Card>
      </div>

      {/* Groups */}
      <Card title={`Duplicate groups (${plan.groups.length})`}>
        {plan.groups.length === 0 ? (
          <p className="text-sm text-muted">No duplicate groups — nothing to repair.</p>
        ) : (
          <div className="space-y-3">
            {plan.groups.map((g) => (
              <details key={g.group_id} className="rounded-lg border border-edge bg-panel">
                <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="font-mono text-xs text-accent">{g.group_id}</span>
                  <span>{g.members.length} samples</span>
                  <span className="text-xs text-muted">
                    splits: {Object.entries(g.splits).map(([s, n]) => `${s}:${n}`).join(" ")}
                  </span>
                  {g.labels.length > 1 && (
                    <span className="rounded bg-danger/20 px-1.5 py-0.5 text-xs text-danger">
                      conflicting labels: {g.labels.join(", ")}
                    </span>
                  )}
                  <span className="ml-auto rounded bg-raised px-2 py-0.5 text-xs text-muted">
                    {g.resolution.replace(/_/g, " ")}
                  </span>
                </summary>
                <div className="border-t border-edge px-3 py-2 text-xs text-muted">
                  <p className="mb-2">{g.reason}</p>
                  <p className="font-mono">{g.members.join(", ")}</p>
                </div>
              </details>
            ))}
          </div>
        )}
      </Card>

      {/* Changed entries table */}
      <Card title={`Proposed changes (${changed.length})`}>
        {changed.length === 0 ? (
          <p className="text-sm text-muted">The current plan proposes no changes.</p>
        ) : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-raised uppercase text-muted">
                <tr>
                  <th className="py-1.5 pr-3">Sample</th>
                  <th className="py-1.5 pr-3">Class</th>
                  <th className="py-1.5 pr-3">From</th>
                  <th className="py-1.5 pr-3">To</th>
                  <th className="py-1.5 pr-3">Action</th>
                  <th className="py-1.5">Reason</th>
                </tr>
              </thead>
              <tbody>
                {changed.map((e) => (
                  <tr key={e.sample_id} className="border-t border-edge/50">
                    <td className="py-1.5 pr-3 font-mono">{e.sample_id}</td>
                    <td className="py-1.5 pr-3">{e.label}</td>
                    <td className="py-1.5 pr-3">{e.original_split}</td>
                    <td className="py-1.5 pr-3">{e.proposed_split}</td>
                    <td
                      className={`py-1.5 pr-3 font-semibold ${
                        e.action === "exclude" ? "text-danger" : "text-warn"
                      }`}
                    >
                      {e.action}
                    </td>
                    <td className="py-1.5 text-muted">{e.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
