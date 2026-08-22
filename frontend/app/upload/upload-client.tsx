"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, defaultConfig, type AuditConfig, type Capabilities, ApiError } from "@/lib/api";

const FORMAT_HINT = `dataset.zip
├── train/
│   ├── class_a/  img001.jpg …
│   └── class_b/  img050.png …
├── val/          (optional)
│   └── class_a/  …
└── test/
    ├── class_a/  …
    └── class_b/  …`;

export default function UploadClient() {
  const router = useRouter();
  const search = useSearchParams();
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState<"upload" | "demo" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [config, setConfig] = useState<AuditConfig>(defaultConfig);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const demoAutostart = useRef(false);

  useEffect(() => {
    api.capabilities().then(setCaps).catch(() => setCaps(null));
  }, []);

  const startDemo = useCallback(async (cfg: AuditConfig) => {
    setBusy("demo");
    setError(null);
    try {
      const job = await api.createDemoAudit(cfg);
      router.push(`/audit/${job.job_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the analysis backend.");
      setBusy(null);
    }
  }, [router]);

  useEffect(() => {
    if (search.get("demo") === "1" && !demoAutostart.current) {
      demoAutostart.current = true;
      void startDemo(defaultConfig);
    }
  }, [search, startDemo]);

  const pickFile = (f: File | undefined | null) => {
    setError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".zip")) {
      setError("Please choose a .zip archive using the folder layout shown.");
      return;
    }
    if (caps && f.size > caps.limits.max_upload_bytes) {
      setError(
        `Archive is ${(f.size / 1048576).toFixed(0)} MiB; the limit is ${(caps.limits.max_upload_bytes / 1048576).toFixed(0)} MiB.`,
      );
      return;
    }
    setFile(f);
  };

  const startUpload = async () => {
    if (!file) return;
    setBusy("upload");
    setError(null);
    try {
      const job = await api.uploadAudit(file, config);
      router.push(`/audit/${job.job_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed — is the backend running?");
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl pt-12">
      <h1 className="text-3xl font-bold tracking-tight">Analyze a dataset</h1>
      <p className="mt-2 text-muted">
        Upload an image-classification dataset as a ZIP archive, or run the built-in
        demonstration dataset through the identical pipeline.
      </p>

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Choose or drop a dataset ZIP file"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          pickFile(e.dataTransfer.files?.[0]);
        }}
        className={`mt-8 cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition ${
          dragOver ? "border-accent bg-panel" : "border-edge bg-raised hover:border-accent-dim"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <p className="text-lg font-medium">
          {file ? file.name : "Drop your dataset ZIP here, or click to browse"}
        </p>
        <p className="mt-1 text-sm text-muted">
          {file
            ? `${(file.size / 1048576).toFixed(1)} MiB selected`
            : "JPG, PNG and WebP images · content-validated, safely extracted, never executed"}
        </p>
      </div>

      {/* Expected format */}
      <details className="mt-4 rounded-lg border border-edge bg-raised">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          Expected folder layout
        </summary>
        <pre className="overflow-x-auto border-t border-edge px-4 py-3 text-xs leading-relaxed text-muted">
          {FORMAT_HINT}
        </pre>
      </details>

      {/* Advanced settings */}
      <div className="mt-4 rounded-lg border border-edge bg-raised">
        <button
          type="button"
          aria-expanded={showAdvanced}
          onClick={() => setShowAdvanced((v) => !v)}
          className="w-full px-4 py-3 text-left text-sm font-medium"
        >
          Advanced settings {showAdvanced ? "▴" : "▾"}
        </button>
        {showAdvanced && caps && (
          <div className="space-y-5 border-t border-edge px-4 py-4 text-sm">
            <Toggle
              label="Exact duplicate detection (SHA-256)"
              hint="Byte-identical files. Fast and always safe to keep on."
              checked={config.enable_exact}
              onChange={(v) => setConfig({ ...config, enable_exact: v })}
            />
            <Toggle
              label="Near-duplicate detection (perceptual hash)"
              hint="Catches rescaled, recompressed and brightness-shifted copies."
              checked={config.enable_perceptual}
              onChange={(v) => setConfig({ ...config, enable_perceptual: v })}
            />
            <Slider
              label={`pHash distance threshold: ${config.phash_threshold ?? caps.defaults.phash_threshold}`}
              hint="Maximum Hamming distance (of 64 bits) to flag a pair. Higher finds more pairs but adds review noise."
              min={0}
              max={16}
              value={config.phash_threshold ?? caps.defaults.phash_threshold}
              onChange={(v) => setConfig({ ...config, phash_threshold: v })}
              disabled={!config.enable_perceptual}
            />
            <Toggle
              label="Similarity search (image embeddings)"
              hint={caps.embedding_backend?.semantic_claim ?? "Embedding backend unavailable."}
              checked={config.enable_semantic}
              onChange={(v) => setConfig({ ...config, enable_semantic: v })}
            />
            <Slider
              label={`Similarity threshold: ${(config.semantic_threshold ?? caps.defaults.semantic_threshold).toFixed(2)}`}
              hint="Cosine similarity above which a pair is flagged as possible overlap. Lower finds more, with more false positives."
              min={0.7}
              max={0.99}
              step={0.01}
              value={config.semantic_threshold ?? caps.defaults.semantic_threshold}
              onChange={(v) => setConfig({ ...config, semantic_threshold: v })}
              disabled={!config.enable_semantic}
            />
            <Toggle
              label="Evaluation-gap experiment"
              hint="Trains a diagnostic classifier on frozen embeddings and compares original vs leakage-quarantined test accuracy. Needs a labeled train and test split."
              checked={config.run_evaluation}
              onChange={(v) => setConfig({ ...config, run_evaluation: v })}
            />
          </div>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/50 bg-danger/10 px-4 py-3 text-sm text-danger"
        >
          {error}
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button
          type="button"
          disabled={!file || busy !== null}
          onClick={startUpload}
          className="rounded-lg bg-accent px-6 py-3 font-semibold text-bg transition enabled:hover:brightness-110 disabled:opacity-40"
        >
          {busy === "upload" ? "Uploading…" : "Start audit"}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => startDemo(config)}
          className="rounded-lg border border-edge bg-panel px-6 py-3 font-semibold transition enabled:hover:border-accent-dim disabled:opacity-40"
        >
          {busy === "demo" ? "Starting demo…" : "Run demonstration dataset"}
        </button>
        {caps && (
          <span className="text-xs text-muted">
            Limits: {(caps.limits.max_upload_bytes / 1048576).toFixed(0)} MiB upload ·{" "}
            {caps.limits.max_file_count.toLocaleString()} files · auto-delete after{" "}
            {caps.limits.retention_hours} h
          </span>
        )}
      </div>

      <p className="mt-6 text-xs leading-relaxed text-muted">
        Only upload datasets you are legally permitted to process. Archives are
        validated by file signature, extracted with traversal and size guards, and
        stored under random internal identifiers. Nothing you upload is executed,
        shared, or used for anything except this audit.
      </p>
    </div>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 accent-[var(--accent)]"
      />
      <span>
        <span className="font-medium">{label}</span>
        <span className="mt-0.5 block text-xs text-muted">{hint}</span>
      </span>
    </label>
  );
}

function Slider({
  label,
  hint,
  min,
  max,
  step = 1,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className={disabled ? "opacity-40" : ""}>
      <label className="block font-medium">{label}</label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-[var(--accent)]"
      />
      <p className="text-xs text-muted">{hint}</p>
    </div>
  );
}
