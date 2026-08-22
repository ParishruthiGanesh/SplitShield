"use client";

import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { api, type Finding, type FindingsPage } from "@/lib/api";
import { SeverityBadge, SplitBadge, kindLabel } from "./ui";

const PAGE_SIZE = 12;

const KIND_OPTIONS = [
  ["", "All kinds"],
  ["exact_cross_split_leakage", "Exact cross-split leakage"],
  ["near_duplicate_cross_split_leakage", "Near-duplicate cross-split"],
  ["possible_semantic_overlap", "Possible semantic overlap"],
  ["conflicting_label_duplicate", "Conflicting-label duplicate"],
  ["same_split_redundancy", "Same-split redundancy"],
] as const;

const REVIEW_ACTIONS = [
  ["confirmed", "Confirm leakage", "border-danger/50 text-danger hover:bg-danger/10"],
  ["safe", "Mark safe / expected", "border-ok/50 text-ok hover:bg-ok/10"],
  ["uncertain", "Uncertain", "border-warn/50 text-warn hover:bg-warn/10"],
] as const;

export default function EvidenceExplorer({
  jobId,
  initialFilter,
  onReviewChanged,
}: {
  jobId: string;
  initialFilter: Record<string, string>;
  onReviewChanged: () => void;
}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<FindingsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Record<string, string>>(initialFilter);
  const [sort, setSort] = useState<"severity" | "similarity">("severity");
  const [zoomed, setZoomed] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        page,
        page_size: PAGE_SIZE,
        sort,
      };
      for (const [k, v] of Object.entries(filters)) if (v) params[k] = v;
      setData(await api.findings(jobId, params));
    } finally {
      setLoading(false);
    }
  }, [jobId, page, filters, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setFilters(initialFilter);
    setPage(1);
  }, [initialFilter]);

  const setFilter = (key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  };

  const review = async (
    finding: Finding,
    decision: string,
    note?: string,
    toggle = true,
  ) => {
    const next =
      toggle && finding.review.decision === decision ? "unreviewed" : decision;
    await api.review(jobId, finding.id, next, note);
    await load();
    onReviewChanged();
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-edge bg-raised p-4 text-sm">
        <Filter label="Severity">
          <select
            value={filters.severity ?? ""}
            onChange={(e) => setFilter("severity", e.target.value)}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            <option value="">All</option>
            {["critical", "high", "medium", "low"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Kind">
          <select
            value={filters.kind ?? ""}
            onChange={(e) => setFilter("kind", e.target.value)}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            {KIND_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Split pair">
          <select
            value={filters.split_pair ?? ""}
            onChange={(e) => setFilter("split_pair", e.target.value)}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            <option value="">All</option>
            <option value="train-test">train ↔ test</option>
            <option value="train-val">train ↔ val</option>
            <option value="test-val">val ↔ test</option>
          </select>
        </Filter>
        <Filter label="Method">
          <select
            value={filters.method ?? ""}
            onChange={(e) => setFilter("method", e.target.value)}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            <option value="">All</option>
            <option value="sha256">SHA-256</option>
            <option value="phash">pHash</option>
            <option value="embedding">Embedding</option>
          </select>
        </Filter>
        <Filter label="Review status">
          <select
            value={filters.review ?? ""}
            onChange={(e) => setFilter("review", e.target.value)}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            <option value="">All</option>
            <option value="unreviewed">Unreviewed</option>
            <option value="confirmed">Confirmed</option>
            <option value="safe">Safe</option>
            <option value="uncertain">Uncertain</option>
          </select>
        </Filter>
        <Filter label="Sort by">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as "severity" | "similarity")}
            className="rounded border border-edge bg-panel px-2 py-1.5"
          >
            <option value="severity">Severity</option>
            <option value="similarity">Similarity</option>
          </select>
        </Filter>
        <span className="ml-auto text-muted">
          {data ? `${data.total} finding(s)` : "…"}
        </span>
      </div>

      {/* Cards */}
      {loading && !data ? (
        <p className="py-16 text-center text-muted animate-pulse-soft">Loading evidence…</p>
      ) : data && data.items.length === 0 ? (
        <p className="py-16 text-center text-muted">No findings match these filters.</p>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {data?.items.map((f) => (
            <FindingCard
              key={f.id}
              jobId={jobId}
              finding={f}
              onReview={review}
              onZoom={setZoomed}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      <div className="mt-6 flex items-center justify-center gap-3 text-sm">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
          className="rounded border border-edge px-3 py-1.5 disabled:opacity-40"
        >
          ← Prev
        </button>
        <span className="text-muted">
          Page {page} of {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
          className="rounded border border-edge px-3 py-1.5 disabled:opacity-40"
        >
          Next →
        </button>
      </div>

      {/* Zoom overlay */}
      {zoomed && (
        <button
          type="button"
          aria-label="Close zoomed image"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-8"
          onClick={() => setZoomed(null)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={zoomed}
            alt="Zoomed evidence"
            className="max-h-full max-w-full rounded-lg object-contain"
          />
        </button>
      )}
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  );
}

function FindingCard({
  jobId,
  finding: f,
  onReview,
  onZoom,
}: {
  jobId: string;
  finding: Finding;
  onReview: (
    f: Finding,
    decision: string,
    note?: string,
    toggle?: boolean,
  ) => Promise<void>;
  onZoom: (url: string) => void;
}) {
  const [note, setNote] = useState(f.review.note ?? "");
  const [showNote, setShowNote] = useState(false);

  return (
    <article className="rounded-xl border border-edge bg-raised p-4">
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <SeverityBadge severity={f.severity} />
        <span className="text-sm font-medium">{f.confidence_label}</span>
        <span className="ml-auto text-xs text-muted">
          {f.method} · similarity {(f.similarity * 100).toFixed(1)}%
        </span>
      </header>

      <div className="grid grid-cols-2 gap-3">
        {([["A", f.sample_a, f.split_a, f.class_a], ["B", f.sample_b, f.split_b, f.class_b]] as const).map(
          ([tag, sample, split, cls]) => (
            <figure key={tag}>
              <button
                type="button"
                onClick={() => onZoom(api.imageUrl(jobId, sample.id))}
                className="block w-full overflow-hidden rounded-lg border border-edge bg-panel"
                aria-label={`Zoom sample ${tag}`}
              >
                <Image
                  src={api.imageUrl(jobId, sample.id)}
                  alt={`Sample ${tag}: ${split}/${cls}`}
                  width={300}
                  height={300}
                  unoptimized
                  className="aspect-square w-full object-contain transition hover:scale-[1.03]"
                />
              </button>
              <figcaption className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                <SplitBadge split={split} />
                <span
                  className={`rounded px-1.5 py-0.5 font-medium ${
                    f.conflicting_label ? "bg-danger/20 text-danger" : "bg-panel text-muted"
                  }`}
                >
                  {cls}
                </span>
                <span className="text-muted">
                  {sample.width ?? "?"}×{sample.height ?? "?"}
                </span>
              </figcaption>
            </figure>
          ),
        )}
      </div>

      <p className="mt-3 text-xs text-muted">
        {kindLabel(f.kind)}
        {f.detail.corroborated_by_multiple_methods &&
          ` · corroborated by ${f.detail.methods?.join(" + ")}`}
        {f.group_id && ` · group ${f.group_id}`}
        {f.method === "phash" && ` · Hamming distance ${f.distance}`}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {REVIEW_ACTIONS.map(([decision, label, cls]) => (
          <button
            key={decision}
            type="button"
            aria-pressed={f.review.decision === decision}
            onClick={() => void onReview(f, decision, note || undefined)}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${cls} ${
              f.review.decision === decision ? "ring-1 ring-current" : "opacity-80"
            }`}
          >
            {f.review.decision === decision ? `✓ ${label}` : label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setShowNote((v) => !v)}
          className="rounded-lg border border-edge px-2.5 py-1 text-xs text-muted hover:text-ink"
        >
          {showNote ? "Hide note" : f.review.note ? "Edit note" : "Add note"}
        </button>
      </div>

      {showNote && (
        <div className="mt-2 flex gap-2">
          <input
            type="text"
            value={note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional reviewer note…"
            className="flex-1 rounded border border-edge bg-panel px-2 py-1.5 text-xs"
          />
          <button
            type="button"
            onClick={() =>
              void onReview(
                f,
                f.review.decision === "unreviewed" ? "uncertain" : f.review.decision,
                note,
                false,
              ).then(() => setShowNote(false))
            }
            className="rounded border border-accent-dim px-3 py-1.5 text-xs text-accent"
          >
            Save
          </button>
        </div>
      )}
    </article>
  );
}
