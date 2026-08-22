"""SQLite persistence layer.

Plain ``sqlite3`` is used deliberately: the prototype needs durable job state
and paginated finding queries, not an ORM. The access functions below are the
only place SQL lives, so swapping the backing store later is contained.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import settings

_local = threading.local()
_write_lock = threading.Lock()

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    source TEXT NOT NULL,
    dataset_name TEXT,
    config_json TEXT NOT NULL,
    summary_json TEXT,
    eval_json TEXT,
    repair_json TEXT,
    fingerprint TEXT,
    storage_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS samples (
    job_id TEXT NOT NULL,
    id TEXT NOT NULL,
    split TEXT NOT NULL,
    label TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    sha256 TEXT,
    phash TEXT,
    width INTEGER,
    height INTEGER,
    bytes INTEGER,
    img_format TEXT,
    corrupt INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (job_id, id)
);
CREATE INDEX IF NOT EXISTS idx_samples_job ON samples(job_id);
CREATE INDEX IF NOT EXISTS idx_samples_sha ON samples(job_id, sha256);

CREATE TABLE IF NOT EXISTS findings (
    job_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence_label TEXT NOT NULL,
    method TEXT NOT NULL,
    sample_a TEXT NOT NULL,
    sample_b TEXT NOT NULL,
    split_a TEXT NOT NULL,
    split_b TEXT NOT NULL,
    class_a TEXT NOT NULL,
    class_b TEXT NOT NULL,
    distance REAL,
    similarity REAL,
    cross_split INTEGER NOT NULL DEFAULT 0,
    conflicting_label INTEGER NOT NULL DEFAULT 0,
    group_id TEXT,
    detail_json TEXT,
    PRIMARY KEY (job_id, id)
);
CREATE INDEX IF NOT EXISTS idx_findings_job ON findings(job_id);
CREATE INDEX IF NOT EXISTS idx_findings_sev ON findings(job_id, severity);

CREATE TABLE IF NOT EXISTS reviews (
    job_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, finding_id)
);

CREATE TABLE IF NOT EXISTS dataset_issues (
    job_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail_json TEXT,
    PRIMARY KEY (job_id, id)
);
CREATE INDEX IF NOT EXISTS idx_issues_job ON dataset_issues(job_id);
"""


def _connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    """Return a thread-local connection to the *current* database path.

    Keyed by path so that worker threads pick up a repointed ``data_dir``
    (tests repoint it per-test; production never changes it).
    """
    path = str(settings.db_path)
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "conn_path", None) != path:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = _connect()
        _local.conn = conn
        _local.conn_path = path
    return conn


def reset_connection() -> None:
    """Drop the thread-local connection (used by tests that repoint data_dir)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None
    _local.conn_path = None


@contextmanager
def write_tx() -> Iterator[sqlite3.Connection]:
    """Serialised write transaction (SQLite single-writer)."""
    conn = get_conn()
    with _write_lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    conn = get_conn()
    with _write_lock:
        conn.executescript(SCHEMA)
        conn.commit()


def jdump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def jload(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
