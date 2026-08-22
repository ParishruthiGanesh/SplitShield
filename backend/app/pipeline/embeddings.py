"""Pluggable image-embedding providers for the similarity stage.

Two backends are implemented:

``TorchMobileNetProvider``
    MobileNetV3-Small penultimate features (ImageNet-pretrained). This is a
    genuine learned embedding and is preferred when available. It requires
    ``torch``/``torchvision`` *and* the ability to download pretrained weights.

``ClassicalDescriptorProvider``
    A fully offline, deterministic descriptor built from Pillow + NumPy only.
    It concatenates three L2-normalised blocks:

      1. **Structure** - 16x16 greyscale thumbnail, mean-centred. Captures
         coarse layout and survives rescaling and recompression.
      2. **Colour** - per-channel 32-bin histograms in HSV. Captures palette;
         partially invariant to brightness because V is histogram-equalised.
      3. **Gradient** - 8-bin orientation histogram over a 4x4 spatial grid,
         magnitude-weighted (a compact HOG). Captures edge structure and is
         robust to global brightness shifts.

    This is an *appearance* descriptor, not a semantic one. It is strong for
    the transformed-duplicate cases SplitShield targets (crops, rescales,
    recompression, brightness changes) and weak for true conceptual overlap
    between visually dissimilar images. The UI and report label the stage
    according to the active backend so no semantic claim is overstated.

Selection is via ``settings.embedding_backend``: ``auto`` (default) tries
torch and silently falls back; ``torch``/``classical`` force a backend;
``off`` disables the stage.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendInfo:
    """Description of the active backend, surfaced in the UI and report."""

    key: str
    name: str
    kind: str  # "learned" | "classical"
    dim: int
    description: str
    semantic_claim: str


class EmbeddingProvider(ABC):
    """Produces L2-normalised feature vectors for image files."""

    info: BackendInfo

    @abstractmethod
    def embed_paths(self, paths: list[Path]) -> np.ndarray:
        """Return an ``(n, dim)`` float32 array of L2-normalised embeddings.

        Rows for unreadable images are all zeros; callers must skip them.
        """

    @staticmethod
    def _l2(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


# --------------------------------------------------------------------------
# Classical descriptor (always available)
# --------------------------------------------------------------------------

_STRUCT_SIZE = 16
_CHROMA_SIZE = 8
_GRID = 4
_ORIENT_BINS = 8


class ClassicalDescriptorProvider(EmbeddingProvider):
    """Offline appearance descriptor; see module docstring for composition."""

    info = BackendInfo(
        key="classical",
        name="Classical appearance descriptor",
        kind="classical",
        dim=(
            _STRUCT_SIZE * _STRUCT_SIZE
            + 2 * _CHROMA_SIZE * _CHROMA_SIZE
            + _GRID * _GRID * _ORIENT_BINS
        ),
        description=(
            "Deterministic Pillow/NumPy descriptor: 16x16 contrast-normalised "
            "greyscale structure, an 8x8 illumination-invariant chromaticity map, "
            "and a 4x4 grid of 8-bin gradient-orientation histograms. Each block "
            "is L2-normalised so none dominates by scale."
        ),
        semantic_claim=(
            "Appearance similarity only. Detects rescaled, recompressed, cropped "
            "and brightness-shifted copies. It does NOT measure conceptual meaning, "
            "so matches are reported as 'possible overlap' requiring human review."
        ),
    )

    def _descriptor(self, path: Path) -> np.ndarray | None:
        try:
            with Image.open(path) as img:
                img.load()
                rgb = img.convert("RGB")
        except Exception:
            return None

        # --- Block 1: structure -------------------------------------
        grey = np.asarray(
            rgb.convert("L").resize((_STRUCT_SIZE, _STRUCT_SIZE), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        structure = grey.reshape(-1) / 255.0
        # Mean-centre and scale to unit variance: invariant to global
        # brightness offset and contrast gain.
        structure = structure - structure.mean()
        std = float(structure.std())
        if std > 1e-6:
            structure = structure / std

        # --- Block 2: chromaticity ----------------------------------
        # Normalised chromaticity r/(r+g+b), g/(r+g+b) is invariant to a global
        # intensity scale by construction, so a brightness change leaves it
        # essentially unmoved. Kept spatial (8x8) rather than a histogram: a
        # global colour histogram proved anti-discriminative in validation,
        # scoring unrelated images higher than brightness-shifted copies.
        small = np.asarray(
            rgb.resize((_CHROMA_SIZE, _CHROMA_SIZE), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        total = small.sum(axis=2, keepdims=True)
        total[total < 1e-6] = 1e-6
        chroma_map = (small / total)[:, :, :2]  # r and g fractions; b is dependent
        chroma = chroma_map.reshape(-1)
        chroma = chroma - chroma.mean()

        # --- Block 3: gradients -------------------------------------
        g = np.asarray(
            rgb.convert("L").resize((64, 64), Image.Resampling.BILINEAR), dtype=np.float32
        ) / 255.0
        gy, gx = np.gradient(g)
        magnitude = np.hypot(gx, gy)
        # Unsigned orientation in [0, pi) -> bin index.
        angle = np.mod(np.arctan2(gy, gx), np.pi)
        bin_idx = np.minimum((angle / np.pi * _ORIENT_BINS).astype(np.int32), _ORIENT_BINS - 1)

        cell = 64 // _GRID
        grad = np.zeros((_GRID, _GRID, _ORIENT_BINS), dtype=np.float32)
        for gy_i in range(_GRID):
            for gx_i in range(_GRID):
                ys = slice(gy_i * cell, (gy_i + 1) * cell)
                xs = slice(gx_i * cell, (gx_i + 1) * cell)
                grad[gy_i, gx_i] = np.bincount(
                    bin_idx[ys, xs].reshape(-1),
                    weights=magnitude[ys, xs].reshape(-1),
                    minlength=_ORIENT_BINS,
                ).astype(np.float32)
        gradient = grad.reshape(-1)

        # Normalise each block independently so no block dominates by scale.
        blocks = []
        for block in (structure, chroma, gradient):
            norm = float(np.linalg.norm(block))
            blocks.append(block / norm if norm > 0 else block)
        return np.concatenate(blocks).astype(np.float32)

    def embed_paths(self, paths: list[Path]) -> np.ndarray:
        out = np.zeros((len(paths), self.info.dim), dtype=np.float32)
        for i, path in enumerate(paths):
            desc = self._descriptor(path)
            if desc is not None and desc.shape[0] == self.info.dim:
                out[i] = desc
        return self._l2(out)


# --------------------------------------------------------------------------
# Torch backend (used automatically when torch + weights are available)
# --------------------------------------------------------------------------


class TorchMobileNetProvider(EmbeddingProvider):
    """MobileNetV3-Small ImageNet features (576-d) on CPU."""

    info = BackendInfo(
        key="torch_mobilenet_v3_small",
        name="MobileNetV3-Small (ImageNet)",
        kind="learned",
        dim=576,
        description=(
            "Penultimate global-pooled features from torchvision's "
            "MobileNetV3-Small with IMAGENET1K_V1 weights, CPU inference."
        ),
        semantic_claim=(
            "Learned visual features. Captures appearance and a degree of "
            "conceptual similarity, but matches still require human review."
        ),
    )

    def __init__(self, batch_size: int = 32) -> None:
        import torch  # noqa: PLC0415 - optional dependency
        from torchvision import transforms  # noqa: PLC0415
        from torchvision.models import (  # noqa: PLC0415
            MobileNet_V3_Small_Weights,
            mobilenet_v3_small,
        )

        self._torch = torch
        self.batch_size = batch_size
        weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
        model = mobilenet_v3_small(weights=weights)
        model.eval()
        self._model = torch.nn.Sequential(
            model.features, torch.nn.AdaptiveAvgPool2d(1), torch.nn.Flatten()
        )
        for param in self._model.parameters():
            param.requires_grad_(False)
        self._tf = transforms.Compose(
            [
                transforms.Resize(232),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

    def embed_paths(self, paths: list[Path]) -> np.ndarray:
        torch = self._torch
        out = np.zeros((len(paths), self.info.dim), dtype=np.float32)
        for start in range(0, len(paths), self.batch_size):
            chunk = paths[start : start + self.batch_size]
            tensors, positions = [], []
            for offset, path in enumerate(chunk):
                try:
                    with Image.open(path) as img:
                        img.load()
                        tensors.append(self._tf(img.convert("RGB")))
                    positions.append(start + offset)
                except Exception:
                    continue
            if not tensors:
                continue
            with torch.no_grad():
                feats = self._model(torch.stack(tensors)).cpu().numpy()
            out[positions] = feats.astype(np.float32)
        return self._l2(out)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def torch_backend_available() -> tuple[bool, str]:
    """Check whether the learned backend can actually run.

    Importing torch is not enough: the pretrained weights must be present in
    the torch hub cache or downloadable. We probe without raising.
    """
    try:
        import torch  # noqa: F401, PLC0415
        from torchvision.models import MobileNet_V3_Small_Weights  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - depends on environment
        return False, f"torch/torchvision not installed ({type(exc).__name__})"

    try:  # pragma: no cover - depends on environment
        from torch.hub import load_state_dict_from_url  # noqa: PLC0415

        load_state_dict_from_url(
            MobileNet_V3_Small_Weights.IMAGENET1K_V1.url, progress=False
        )
        return True, "available"
    except Exception as exc:  # pragma: no cover
        return False, f"pretrained weights unavailable ({type(exc).__name__})"


def get_provider(backend: str, batch_size: int = 32) -> tuple[EmbeddingProvider | None, str]:
    """Resolve a provider. Returns ``(provider, note)``; ``None`` disables the stage."""
    backend = (backend or "auto").lower()

    if backend == "off":
        return None, "Semantic stage disabled by configuration."

    if backend in ("torch", "auto"):
        ok, reason = torch_backend_available()
        if ok:  # pragma: no cover - environment dependent
            try:
                return TorchMobileNetProvider(batch_size=batch_size), "Learned backend active."
            except Exception as exc:
                reason = f"initialisation failed ({type(exc).__name__})"
        if backend == "torch":
            return None, f"Requested torch backend is unavailable: {reason}."
        logger.info("Falling back to classical descriptor: %s", reason)
        return (
            ClassicalDescriptorProvider(),
            f"Learned backend unavailable ({reason}); using classical descriptor.",
        )

    return ClassicalDescriptorProvider(), "Classical descriptor selected."
