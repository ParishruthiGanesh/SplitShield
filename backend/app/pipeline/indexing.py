"""Per-sample indexing: cryptographic digest, perceptual hash and metadata.

A corrupt or unreadable file must never abort the job; it is recorded as a
``corrupt`` sample and reported as its own finding.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image, ImageFile, UnidentifiedImageError

from ..config import settings
from ..domain import Split
from .ingest import ALLOWED_FORMATS, ExtractedFile

# Refuse to build huge decompression bombs; Pillow raises above this.
Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
# A truncated JPEG should raise rather than silently yield a grey image.
ImageFile.LOAD_TRUNCATED_IMAGES = False


@dataclass
class SampleRecord:
    """One indexed dataset sample."""

    id: str
    split: Split
    label: str
    rel_path: str
    stored_path: Path
    sha256: str | None = None
    phash: str | None = None
    width: int | None = None
    height: int | None = None
    bytes: int = 0
    img_format: str | None = None
    corrupt: bool = False
    error: str | None = None

    @property
    def aspect_ratio(self) -> float | None:
        if self.width and self.height:
            return round(self.width / self.height, 4)
        return None


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Stream a SHA-256 digest so large files do not load into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def compute_phash(image: Image.Image, hash_size: int = 8) -> str:
    """Perceptual hash (DCT-based pHash) of an image.

    pHash is chosen over aHash/dHash because it is markedly more robust to
    JPEG recompression and small brightness shifts, which are the dominant
    real-world causes of "same photo, different bytes" leakage.
    """
    return str(imagehash.phash(image, hash_size=hash_size))


def hamming_distance(a: str, b: str) -> int:
    """Hamming distance between two hex-encoded perceptual hashes."""
    if len(a) != len(b):
        raise ValueError("Hash length mismatch")
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def phash_similarity(distance: int, bits: int) -> float:
    """Normalise a Hamming distance to a 0..1 similarity score."""
    if bits <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (distance / bits)))


def index_sample(item: ExtractedFile, hash_size: int = 8) -> SampleRecord:
    """Index one file, degrading gracefully to ``corrupt`` on any decode error."""
    record = SampleRecord(
        id=item.internal_id,
        split=item.split,
        label=item.label,
        rel_path=item.rel_path,
        stored_path=item.stored_path,
        bytes=item.size_bytes,
    )
    try:
        record.sha256 = sha256_file(item.stored_path)
    except OSError as exc:
        record.corrupt = True
        record.error = f"Unreadable file ({type(exc).__name__})"
        return record

    try:
        with Image.open(item.stored_path) as img:
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                record.corrupt = True
                record.error = f"Unsupported image format '{fmt or 'unknown'}'"
                return record
            record.img_format = fmt
            record.width, record.height = img.size
            # verify() invalidates the object, so re-open for pixel work.
            img.verify()

        with Image.open(item.stored_path) as img:
            img.load()
            rgb = img.convert("RGB")
            record.phash = compute_phash(rgb, hash_size=hash_size)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        record.corrupt = True
        record.phash = None
        detail = str(exc).strip()
        record.error = f"{type(exc).__name__}: {detail[:160]}" if detail else type(exc).__name__
    return record


def load_rgb_array(path: Path, size: tuple[int, int]) -> np.ndarray | None:
    """Load an image as a resized float32 RGB array in [0, 1]."""
    try:
        with Image.open(path) as img:
            img.load()
            rgb = img.convert("RGB").resize(size, Image.Resampling.BILINEAR)
            return np.asarray(rgb, dtype=np.float32) / 255.0
    except Exception:
        return None
