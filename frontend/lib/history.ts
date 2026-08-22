/**
 * Per-browser audit history, kept in localStorage.
 *
 * Deliberately client-side only: the server never exposes a cross-user list
 * of audits, so each visitor sees exactly the audits they started on this
 * device and nothing else. Entries can outlive the audits they point to
 * (retention deletes server data after the configured window); the UI labels
 * those as expired when the link no longer resolves.
 */

export interface HistoryEntry {
  jobId: string;
  name: string;
  source: "upload" | "demo";
  createdAt: string; // ISO timestamp
}

const KEY = "splitshield.audit.history.v1";
const MAX_ENTRIES = 20;

function safeRead(): HistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is HistoryEntry =>
        typeof e === "object" && e !== null &&
        typeof (e as HistoryEntry).jobId === "string" &&
        typeof (e as HistoryEntry).name === "string" &&
        typeof (e as HistoryEntry).createdAt === "string",
    );
  } catch {
    return [];
  }
}

function safeWrite(entries: HistoryEntry[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // Storage unavailable (private mode, blocked) - history is best-effort.
  }
}

export function listHistory(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  return safeRead();
}

export function addHistory(entry: HistoryEntry): void {
  if (typeof window === "undefined") return;
  const rest = safeRead().filter((e) => e.jobId !== entry.jobId);
  safeWrite([entry, ...rest]);
}

export function removeHistory(jobId: string): void {
  if (typeof window === "undefined") return;
  safeWrite(safeRead().filter((e) => e.jobId !== jobId));
}
