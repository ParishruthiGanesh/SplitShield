"""Shared fixtures. Each test session gets an isolated data directory."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app import db  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point all storage at a per-test temp dir and reset DB connections."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture()
def make_image(tmp_path):
    """Factory producing deterministic structured PNG/JPEG images."""
    import numpy as np
    from PIL import Image

    def _make(seed: int = 0, size: int = 96):
        rng = np.random.RandomState(seed)
        x, y = np.meshgrid(np.linspace(0, 1, size), np.linspace(0, 1, size))
        img = np.stack(
            [np.sin(6 * x + rng.rand() * 3), np.cos(5 * y + rng.rand() * 3), x * y], -1
        )
        img = (img - img.min()) / (img.max() - img.min())
        for _ in range(5):
            cx, cy, r = rng.randint(8, size - 8, 3)
            mask = ((np.arange(size)[:, None] - cy) ** 2 + (np.arange(size)[None, :] - cx) ** 2) < r * 2
            img[mask] = rng.rand(3)
        return Image.fromarray((img * 255).astype("uint8"))

    return _make


@pytest.fixture()
def make_zip(tmp_path):
    """Factory that builds a dataset ZIP from {archive_path: PIL.Image|bytes}."""
    import io
    import zipfile

    def _make(entries: dict, name: str = "ds.zip") -> Path:
        zip_path = tmp_path / name
        with zipfile.ZipFile(zip_path, "w") as zf:
            for arcname, content in entries.items():
                if isinstance(content, bytes):
                    zf.writestr(arcname, content)
                else:
                    buf = io.BytesIO()
                    fmt = "JPEG" if arcname.lower().endswith((".jpg", ".jpeg")) else "PNG"
                    content.save(buf, format=fmt)
                    zf.writestr(arcname, buf.getvalue())
        return zip_path

    return _make
