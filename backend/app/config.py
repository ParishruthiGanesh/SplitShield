"""Application configuration.

All values are overridable via environment variables (prefix ``SPLITSHIELD_``)
or a local ``.env`` file. No secrets are required to run SplitShield locally.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    return Path(os.environ.get("SPLITSHIELD_DATA_DIR", "/tmp/splitshield-data"))


class Settings(BaseSettings):
    """Runtime settings for the SplitShield backend."""

    model_config = SettingsConfigDict(
        env_prefix="SPLITSHIELD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server -------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Storage ------------------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir)

    # --- Upload safety limits ----------------------------------------
    # Maximum size of the uploaded archive itself.
    max_upload_bytes: int = 512 * 1024 * 1024  # 512 MiB
    # Maximum total uncompressed size (zip-bomb guard).
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    # Maximum number of entries inside the archive.
    max_file_count: int = 50_000
    # Maximum size of any single member file.
    max_member_bytes: int = 64 * 1024 * 1024  # 64 MiB
    # Guard against absurd compression ratios (zip bomb).
    max_compression_ratio: float = 200.0
    # Largest image (pixels) we will decode.
    max_image_pixels: int = 64_000_000

    # --- Retention ----------------------------------------------------
    retention_hours: int = 24
    retention_sweep_seconds: int = 900

    # --- Analysis defaults (user-overridable per job) -----------------
    phash_size: int = 8
    phash_threshold: int = 8           # Hamming distance <= threshold => candidate
    phash_strong_threshold: int = 4    # <= this => "likely near duplicate"
    semantic_threshold: float = 0.90   # cosine similarity
    semantic_top_k: int = 10
    enable_semantic_default: bool = True

    # --- Evaluation experiment ---------------------------------------
    random_seed: int = 1337
    eval_min_samples_per_class: int = 5
    eval_min_classes: int = 2
    eval_min_test_samples: int = 10
    eval_bootstrap_iterations: int = 1000
    eval_min_bootstrap_samples: int = 20

    # --- Embeddings ---------------------------------------------------
    # "auto" tries torch/MobileNetV3 then falls back to the classical descriptor.
    embedding_backend: str = "auto"  # auto | torch | classical | off
    embedding_batch_size: int = 32

    # --- Jobs ---------------------------------------------------------
    max_concurrent_jobs: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def extract_dir(self) -> Path:
        return self.data_dir / "extracted"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "splitshield.db"


settings = Settings()


def ensure_dirs() -> None:
    """Create the data directories if they do not yet exist."""
    for d in (settings.data_dir, settings.uploads_dir, settings.extract_dir):
        d.mkdir(parents=True, exist_ok=True)
