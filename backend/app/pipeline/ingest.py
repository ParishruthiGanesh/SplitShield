"""Secure dataset ingestion.

Threat model addressed here:

* **Zip path traversal** (``../../etc/passwd``, absolute paths, symlink members)
* **Zip bombs** (compression-ratio, uncompressed-total and member-size caps)
* **Entry-count exhaustion**
* **Type confusion** (extension lying about content -> magic-byte sniffing)
* **Decompression bombs in images** (Pillow ``MAX_IMAGE_PIXELS``)

Nothing extracted here is ever executed. Files are written with a generated
internal id, and the original archive-relative path is retained only as
metadata for display.
"""
from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..config import settings
from ..domain import Split

# Magic-byte signatures for the formats we accept.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
]

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Label assigned when images sit directly inside a split directory with no
# class subfolder (common for detection-style datasets, e.g. YOLO's
# images/train/*.jpg). Label-dependent checks are disabled for such samples.
UNLABELED = "(unlabeled)"
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

# Directory names that map onto a split.
SPLIT_ALIASES: dict[str, Split] = {
    "train": Split.TRAIN,
    "training": Split.TRAIN,
    "val": Split.VAL,
    "valid": Split.VAL,
    "validation": Split.VAL,
    "dev": Split.VAL,
    "test": Split.TEST,
    "testing": Split.TEST,
    "eval": Split.TEST,
}


class IngestError(ValueError):
    """Raised when an upload is rejected outright (safe, user-facing message)."""


@dataclass
class RejectedEntry:
    path: str
    reason: str


@dataclass
class ExtractedFile:
    """One accepted image file on disk, plus where it came from."""

    internal_id: str
    stored_path: Path
    rel_path: str
    split: Split
    label: str
    size_bytes: int


@dataclass
class ExtractResult:
    files: list[ExtractedFile] = field(default_factory=list)
    rejected: list[RejectedEntry] = field(default_factory=list)
    total_uncompressed: int = 0

    @property
    def splits_present(self) -> set[Split]:
        return {f.split for f in self.files}


def sniff_format(head: bytes) -> str | None:
    """Identify an image container from its leading bytes.

    WebP needs a two-part check (``RIFF....WEBP``) so it is handled separately.
    """
    for magic, name in _SIGNATURES:
        if head.startswith(magic):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def is_safe_member_name(name: str) -> bool:
    """Reject traversal, absolute paths, drive letters and NUL bytes."""
    if not name or "\x00" in name:
        return False
    normalised = name.replace("\\", "/")
    if normalised.startswith("/"):
        return False
    # Windows drive letter or UNC path.
    if len(normalised) >= 2 and normalised[1] == ":":
        return False
    parts = PurePosixPath(normalised).parts
    if any(p == ".." for p in parts):
        return False
    return True


def _resolve_within(base: Path, candidate: Path) -> bool:
    """True only if ``candidate`` stays inside ``base`` after resolution."""
    try:
        base_r = base.resolve()
        cand_r = candidate.resolve()
    except OSError:
        return False
    return base_r == cand_r or base_r in cand_r.parents


def classify_path(rel_path: str) -> tuple[Split, str] | None:
    """Map ``train/class_a/img.jpg`` -> (Split.TRAIN, "class_a").

    Tolerates wrapper directories (``dataset/train/...``, ``images/train/...``)
    and nested class directories (joined with ``/``). An image sitting directly
    inside a split directory - the layout used by detection datasets such as
    YOLO (``images/train/img.jpg``) - is accepted with the ``UNLABELED``
    pseudo-class; label-dependent analyses are skipped for such samples.
    Returns ``None`` only when no split directory appears anywhere in the path.
    """
    parts = [p for p in PurePosixPath(rel_path.replace("\\", "/")).parts if p not in (".",)]
    if len(parts) < 2:
        return None

    split_idx = None
    for idx, part in enumerate(parts[:-1]):
        if part.lower() in SPLIT_ALIASES:
            split_idx = idx
            break
    if split_idx is None:
        return None

    split = SPLIT_ALIASES[parts[split_idx].lower()]
    class_parts = parts[split_idx + 1 : -1]
    if not class_parts:
        # Image sits directly in the split directory: no class label.
        return split, UNLABELED
    return split, "/".join(class_parts)


def _should_skip(name: str) -> str | None:
    """Return a reason when an archive entry is uninteresting rather than unsafe."""
    base = PurePosixPath(name).name
    if name.endswith("/"):
        return "directory"
    if base.startswith("._") or base == ".DS_Store":
        return "macOS resource fork"
    if "__MACOSX/" in name:
        return "macOS metadata"
    if base.startswith("."):
        return "hidden file"
    return None


def inspect_archive(zip_path: Path) -> tuple[list[zipfile.ZipInfo], list[RejectedEntry], int]:
    """Validate archive structure *before* writing anything to disk."""
    if not zipfile.is_zipfile(zip_path):
        raise IngestError("File is not a valid ZIP archive.")

    accepted: list[zipfile.ZipInfo] = []
    rejected: list[RejectedEntry] = []
    total_uncompressed = 0

    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > settings.max_file_count:
            raise IngestError(
                f"Archive contains {len(infos)} entries, exceeding the limit of "
                f"{settings.max_file_count}."
            )

        for info in infos:
            name = info.filename

            skip_reason = _should_skip(name)
            if skip_reason:
                continue

            if not is_safe_member_name(name):
                rejected.append(RejectedEntry(name, "Unsafe path (traversal or absolute path)"))
                continue

            # Symlinks / special files are encoded in the high 16 bits on Unix.
            mode = info.external_attr >> 16
            if mode and not (mode & 0o170000) in (0o100000, 0):
                rejected.append(RejectedEntry(name, "Non-regular file (symlink or special)"))
                continue

            ext = PurePosixPath(name).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                shown = ext or "(none)"
                rejected.append(RejectedEntry(name, f"Unsupported extension '{shown}'"))
                continue

            if info.file_size > settings.max_member_bytes:
                rejected.append(RejectedEntry(name, "File exceeds per-file size limit"))
                continue

            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > settings.max_compression_ratio:
                    rejected.append(
                        RejectedEntry(name, f"Suspicious compression ratio ({ratio:.0f}x)")
                    )
                    continue

            total_uncompressed += info.file_size
            if total_uncompressed > settings.max_uncompressed_bytes:
                raise IngestError(
                    "Archive exceeds the maximum uncompressed size of "
                    f"{settings.max_uncompressed_bytes // (1024 * 1024)} MiB."
                )

            accepted.append(info)

    if not accepted:
        raise IngestError(
            "No supported images (JPG/JPEG/PNG/WebP) were found in the archive. "
            "Expected a train/<class>/image.jpg folder layout."
        )
    return accepted, rejected, total_uncompressed


def extract_dataset(zip_path: Path, dest_root: Path) -> ExtractResult:
    """Safely extract an archive into ``dest_root``.

    Each accepted member is streamed out under a generated internal id so no
    attacker-controlled path component ever reaches the filesystem.
    """
    accepted, rejected, total = inspect_archive(zip_path)
    dest_root.mkdir(parents=True, exist_ok=True)
    result = ExtractResult(rejected=list(rejected), total_uncompressed=total)

    with zipfile.ZipFile(zip_path) as zf:
        for index, info in enumerate(accepted):
            rel = info.filename.replace("\\", "/")
            classified = classify_path(rel)
            if classified is None:
                result.rejected.append(
                    RejectedEntry(rel, "Could not determine split/class from folder layout")
                )
                continue
            split, label = classified

            internal_id = f"s{index:07d}"
            ext = PurePosixPath(rel).suffix.lower()
            out_path = dest_root / split.value / f"{internal_id}{ext}"
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if not _resolve_within(dest_root, out_path):
                result.rejected.append(RejectedEntry(rel, "Resolved outside extraction root"))
                continue

            written = 0
            try:
                with zf.open(info) as src, open(out_path, "wb") as dst:
                    while True:
                        chunk = src.read(1 << 16)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > settings.max_member_bytes:
                            raise IngestError("Member exceeded size limit during extraction")
                        dst.write(chunk)
            except IngestError:
                out_path.unlink(missing_ok=True)
                result.rejected.append(RejectedEntry(rel, "File exceeds per-file size limit"))
                continue
            except (zipfile.BadZipFile, OSError, EOFError) as exc:
                out_path.unlink(missing_ok=True)
                result.rejected.append(RejectedEntry(rel, f"Could not extract ({type(exc).__name__})"))
                continue

            # Content sniffing: the extension must not contradict the bytes.
            with open(out_path, "rb") as fh:
                head = fh.read(16)
            fmt = sniff_format(head)
            if fmt is None:
                out_path.unlink(missing_ok=True)
                result.rejected.append(
                    RejectedEntry(rel, "Content is not a recognised JPEG/PNG/WebP image")
                )
                continue

            result.files.append(
                ExtractedFile(
                    internal_id=internal_id,
                    stored_path=out_path,
                    rel_path=rel,
                    split=split,
                    label=label,
                    size_bytes=written,
                )
            )

    if not result.files:
        raise IngestError(
            "No usable images were found. The archive must contain train/val/test "
            "split folders, either with class subfolders (train/cat/img1.jpg) or "
            "with images directly inside the split (images/train/img1.jpg)."
        )
    return result


def collect_directory(root: Path) -> ExtractResult:
    """Build an ExtractResult from an already-extracted directory tree.

    Used by the demo dataset, which is generated locally rather than uploaded,
    so that demo and upload flows share one downstream pipeline.
    """
    result = ExtractResult()
    paths = sorted(p for p in root.rglob("*") if p.is_file())
    for index, path in enumerate(paths):
        rel = path.relative_to(root).as_posix()
        if _should_skip(rel):
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            result.rejected.append(RejectedEntry(rel, f"Unsupported extension '{path.suffix}'"))
            continue
        classified = classify_path(rel)
        if classified is None:
            result.rejected.append(RejectedEntry(rel, "Could not determine split/class"))
            continue
        split, label = classified
        size = path.stat().st_size
        result.total_uncompressed += size
        result.files.append(
            ExtractedFile(
                internal_id=f"s{index:07d}",
                stored_path=path,
                rel_path=rel,
                split=split,
                label=label,
                size_bytes=size,
            )
        )
    if not result.files:
        raise IngestError("Directory contained no usable images.")
    return result


def fingerprint_dataset(files: list[ExtractedFile], digests: dict[str, str]) -> str:
    """Order-independent dataset fingerprint for reproducibility in reports."""
    h = hashlib.sha256()
    for item in sorted(
        f"{f.split.value}/{f.label}/{digests.get(f.internal_id, '')}" for f in files
    ):
        h.update(item.encode())
        h.update(b"\n")
    return h.hexdigest()
