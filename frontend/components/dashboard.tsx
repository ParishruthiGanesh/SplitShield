"use client";

import { useState } from "react";
import type { Summary } from "@/lib/api";
import {
  AccuracyComparisonChart,
  ClassDistributionChart,
  SeverityChart,
  SplitDistributionChart,
} from "./charts";
import { Card, Stat, kindLabel } from "./ui";

export default function Dashboard({
  summary,
  onDrillDown,
}: {
  summary: Summary;
  jobId: string;
  onDrillDown: (filter: Record<string, string>) => void;
}) {
  const { integrity, counts, inventory, evaluation } = summary;
  const [showBreakdown, setShowBreakdown] = useState(false);

  const scoreTone =
    integrity.score >= 90 ? "text-ok" : integrity.score >= 75 ? "text-warn" : "text-danger";

  const fixFirst = buildFixFirst(summary, onDrillDown);

  return (
    <div className="space-y-6">
      {/* Score + status row */}
      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        <Card title="Dataset Integrity Score">
          <div className="flex items-baseline gap-3">
            <span className={`text-6xl font-bold tabular-nums ${scoreTone}`}>
              {integrity.score}
            </span>
            <span className="text-muted">/ 100</span>
          </div>
          <p className={`mt-1 font-semibold ${scoreTone}`}>{integrity.grade}</p>
          <button
            type="button"
            className="mt-3 text-xs text-accent underline-offset-2 hover:underline"
            onClick={() => setShowBreakdown((v) => !v)}
          >
            {showBreakdown ? "Hide" : "Show"} score breakdown
          </button>
        </Card>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat
            label="Exact cross-split leaks"
            value={counts.exact_cross_split}
            tone={counts.exact_cross_split ? "danger" : "ok"}
          />
          <Stat
            label="Near-duplicate leaks"
            value={counts.near_cross_split}
            tone={counts.near_cross_split ? "warn" : "ok"}
          />
          <Stat
            label="Conflicting labels"
            value={counts.conflicting_label}
            tone={counts.conflicting_label ? "danger" : "ok"}
          />
          <Stat
            label="Possible overlaps"
            value={counts.semantic_overlap}
          />
          <Stat
            label="Corrupt images"
            value={counts.corrupt}
            tone={counts.corrupt ? "warn" : "ok"}
          />
          <Stat
            label="Class imbalance"
            value={
              inventory.class_imbalance_ratio
                ? `${inventory.class_imbalance_ratio.toFixed(1)}×`
                : "–"
            }
            tone={
              (inventory.class_imbalance_ratio ?? 1) > 5
                ? "warn"
                : undefined
            }
          />
        </div>
      </div>

      {showBreakdown && (
        <Card title="Score breakdown (documented weighted formula — no model involved)">
          <p className="mb-3 font-mono text-xs text-muted">{integrity.formula}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th className="py-1.5 pr-3">Category</th>
                  <th className="py-1.5 pr-3">Weight</th>
                  <th className="py-1.5 pr-3">Affected</th>
                  <th className="py-1.5 pr-3">Penalty</th>
                  <th className="py-1.5">Explanation</th>
                </tr>
              </thead>
              <tbody>
                {integrity.components.map((c) => (
                  <tr key={c.category} className="border-t border-edge/60">
                    <td className="py-1.5 pr-3">{kindLabel(c.category)}</td>
                    <td className="py-1.5 pr-3 tabular-nums">{c.weight}</td>
                    <td className="py-1.5 pr-3 tabular-nums">{c.affected_samples}</td>
                    <td className="py-1.5 pr-3 tabular-nums">
                      {c.penalty > 0 ? `−${c.penalty}` : "0"}
                    </td>
                    <td className="py-1.5 text-xs text-muted">{c.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* What to fix first */}
      {fixFirst.length > 0 && (
        <Card title="What should I fix first?">
          <ol className="space-y-2">
            {fixFirst.map((item, i) => (
              <li key={item.key} className="flex items-start gap-3 text-sm">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-panel text-xs font-bold text-accent">
                  {i + 1}
                </span>
                <div>
                  <button
                    type="button"
                    onClick={item.action}
                    className="text-left font-medium text-accent underline-offset-2 hover:underline"
                  >
                    {item.title}
                  </button>
                  <p className="text-xs text-muted">{item.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {/* Evaluation gap */}
      <Card title="Observed Evaluation Gap">
        {evaluation && evaluation.eligible && evaluation.original ? (
          evaluation.cleaned ? (
            <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
              <div>
                <AccuracyComparisonChart
                  original={{ accuracy: evaluation.original.accuracy }}
                  cleaned={{ accuracy: evaluation.cleaned.accuracy }}
                />
                <p className="mt-2 text-sm">
                  Removing{" "}
                  <strong>{evaluation.quarantined_test_samples}</strong> test samples
                  implicated in strong cross-split leakage changed the diagnostic
                  model&apos;s accuracy from{" "}
                  <strong>{(evaluation.original.accuracy * 100).toFixed(1)}%</strong> to{" "}
                  <strong>{(evaluation.cleaned.accuracy * 100).toFixed(1)}%</strong> — an
                  observed gap of{" "}
                  <strong className="text-warn">
                    {((evaluation.observed_evaluation_gap ?? 0) * 100).toFixed(1)} points
                  </strong>
                  .
                </p>
              </div>
              <dl className="space-y-1.5 text-sm">
                <Metric label="Original accuracy" value={pct(evaluation.original.accuracy)} />
                <Metric
                  label="Original 95% CI"
                  value={ci(evaluation.original.accuracy_ci95)}
                />
                <Metric label="Original macro-F1" value={pct(evaluation.original.macro_f1)} />
                <Metric label="Cleaned accuracy" value={pct(evaluation.cleaned.accuracy)} />
                <Metric label="Cleaned 95% CI" value={ci(evaluation.cleaned.accuracy_ci95)} />
                <Metric label="Cleaned macro-F1" value={pct(evaluation.cleaned.macro_f1)} />
                <Metric
                  label="Test samples (orig → cleaned)"
                  value={`${evaluation.original.test_samples} → ${evaluation.cleaned.test_samples}`}
                />
                <Metric label="Random seed" value={String(evaluation.seed)} />
              </dl>
            </div>
          ) : (
            <p className="text-sm text-muted">
              {evaluation.note ??
                "No test samples were implicated in strong leakage; nothing to compare."}{" "}
              (Original accuracy: {pct(evaluation.original.accuracy)} on{" "}
              {evaluation.original.test_samples} samples.)
            </p>
          )
        ) : (
          <p className="text-sm text-muted">
            Experiment not run: {evaluation?.reason ?? "disabled."}
          </p>
        )}
        {evaluation?.eligible && (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-muted hover:text-ink">
              Interpretation warnings (read before quoting these numbers)
            </summary>
            <ul className="mt-2 space-y-1 text-xs text-muted">
              {evaluation.warnings.map((w) => (
                <li key={w}>• {w}</li>
              ))}
            </ul>
          </details>
        )}
      </Card>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Split distribution">
          <SplitDistributionChart
            perSplitClass={inventory.per_split_class}
            classes={inventory.classes}
          />
        </Card>
        <Card title="Class distribution">
          <ClassDistributionChart perClass={inventory.per_class_total} />
        </Card>
        <Card title="Findings by severity">
          <SeverityChart counts={summary.severity_counts} />
        </Card>
      </div>

      {/* Inventory extras */}
      <Card title="Dataset inventory">
        <div className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <Metric label="Total samples" value={String(inventory.total_samples)} />
          <Metric label="Valid samples" value={String(inventory.total_valid_samples)} />
          <Metric label="Rejected files" value={String(inventory.rejected_count)} />
          <Metric
            label="Image formats"
            value={Object.entries(inventory.formats)
              .map(([f, n]) => `${f}: ${n}`)
              .join(", ") || "–"}
          />
          <Metric
            label="Dimensions (median)"
            value={`${inventory.dimensions.width?.median ?? "?"} × ${inventory.dimensions.height?.median ?? "?"}`}
          />
          <Metric
            label="Aspect ratio (min–max)"
            value={`${inventory.dimensions.aspect_ratio?.min ?? "?"} – ${inventory.dimensions.aspect_ratio?.max ?? "?"}`}
          />
          <Metric
            label="File size (median)"
            value={fmtBytes(inventory.dimensions.file_size_bytes?.median)}
          />
          <Metric label="Test fraction" value={pct(inventory.test_fraction)} />
          <Metric
            label="Missing class/split combos"
            value={String(inventory.missing_class_in_split.length)}
          />
        </div>
        {summary.embedding_backend && (
          <p className="mt-4 border-t border-edge/60 pt-3 text-xs text-muted">
            Similarity backend: <strong>{summary.embedding_backend.name}</strong> —{" "}
            {summary.embedding_backend.semantic_claim}
          </p>
        )}
      </Card>
    </div>
  );
}

function buildFixFirst(
  summary: Summary,
  onDrillDown: (f: Record<string, string>) => void,
) {
  const items: { key: string; title: string; detail: string; action: () => void }[] = [];
  const c = summary.counts;
  if (c.exact_cross_split > 0) {
    items.push({
      key: "exact",
      title: `Remove ${c.exact_cross_split} exact cross-split duplicate pair(s)`,
      detail:
        "Byte-identical images in both train and test directly reward memorisation. Highest priority.",
      action: () => onDrillDown({ kind: "exact_cross_split_leakage" }),
    });
  }
  if (c.conflicting_label > 0) {
    items.push({
      key: "conflict",
      title: `Resolve ${c.conflicting_label} conflicting-label duplicate(s)`,
      detail:
        "The same image appears under different classes; the correct label needs a human decision.",
      action: () => onDrillDown({ kind: "conflicting_label_duplicate" }),
    });
  }
  if (c.near_cross_split > 0) {
    items.push({
      key: "near",
      title: `Review ${c.near_cross_split} near-duplicate cross-split pair(s)`,
      detail: "Recompressed/rescaled variants across splits: verify, then repair the split.",
      action: () => onDrillDown({ kind: "near_duplicate_cross_split_leakage" }),
    });
  }
  if (c.corrupt > 0) {
    items.push({
      key: "corrupt",
      title: `Exclude ${c.corrupt} corrupt image(s)`,
      detail: "Unreadable files listed in the inventory; the repair manifest excludes them.",
      action: () => onDrillDown({}),
    });
  }
  if (c.semantic_overlap > 0) {
    items.push({
      key: "sem",
      title: `Triage ${c.semantic_overlap} possible overlap(s)`,
      detail:
        "Appearance-similarity candidates below duplicate confidence. Mark each confirmed or safe.",
      action: () => onDrillDown({ kind: "possible_semantic_overlap" }),
    });
  }
  return items.slice(0, 5);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-edge/40 pb-1">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function pct(v: number | undefined): string {
  return v === undefined ? "–" : `${(v * 100).toFixed(1)}%`;
}

function ci(v: { low: number; high: number } | null | undefined): string {
  return v ? `[${(v.low * 100).toFixed(1)}%, ${(v.high * 100).toFixed(1)}%]` : "n/a (small sample)";
}

function fmtBytes(v: number | undefined): string {
  if (!v) return "–";
  return v > 1048576 ? `${(v / 1048576).toFixed(1)} MiB` : `${(v / 1024).toFixed(0)} KiB`;
}
