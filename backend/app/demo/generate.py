"""Deterministic synthetic demo dataset with *known* planted defects.

Everything here is generated programmatically from a fixed seed, so the demo
carries no licensing risk and the ground truth is exact rather than guessed.

The dataset is deliberately *not* trivial: the majority of images are clean and
class-separable, so the diagnostic classifier has a real signal to learn and the
detector has a real chance to produce false positives.

Planted defects (see ``GROUND_TRUTH`` in the emitted manifest):

  1. exact_cross_split      - byte-identical train/test pairs
  2. recompressed_cross_split - same pixels re-encoded as lower-quality JPEG
  3. resized_cross_split    - downscaled then upscaled copy
  4. cropped_cross_split    - centre-cropped and rescaled copy
  5. brightened_cross_split - global brightness shift
  6. conflicting_label      - identical image filed under two different classes
  7. corrupt_file           - truncated JPEG that cannot be decoded
  8. class_imbalance        - one class deliberately under-represented
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

DEMO_SEED = 20260101
IMAGE_SIZE = 96

CLASSES = ("circles", "stripes", "blobs")

# Deliberate class imbalance: "blobs" is the minority class.
TRAIN_COUNTS = {"circles": 30, "stripes": 24, "blobs": 8}
VAL_COUNTS = {"circles": 6, "stripes": 5, "blobs": 3}
TEST_COUNTS = {"circles": 12, "stripes": 10, "blobs": 5}


@dataclass
class PlantedIssue:
    """One deliberately introduced defect, used to verify detector recall."""

    issue_type: str
    description: str
    files: list[str]
    expected_finding_kind: str
    expected_cross_split: bool = False
    expected_conflicting_label: bool = False
    detectable_by: list[str] = field(default_factory=list)


def _bg(rng: random.Random) -> tuple[int, int, int]:
    return (rng.randint(20, 90), rng.randint(20, 90), rng.randint(40, 120))


def _render_circles(rng: random.Random) -> Image.Image:
    img = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), _bg(rng))
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(3, 6)):
        r = rng.randint(10, 26)
        cx, cy = rng.randint(r, IMAGE_SIZE - r), rng.randint(r, IMAGE_SIZE - r)
        colour = (rng.randint(140, 255), rng.randint(60, 180), rng.randint(60, 180))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=(255, 255, 255))
    return img


def _render_stripes(rng: random.Random) -> Image.Image:
    # Angle, spacing, phase and a second accent colour all vary so that two
    # independently generated stripe images do not collide as near-duplicates.
    img = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), _bg(rng))
    draw = ImageDraw.Draw(img)
    width = rng.randint(4, 12)
    gap = rng.randint(width, width * 3)
    slope = rng.choice([-2.0, -1.0, -0.5, 0.5, 1.0, 2.0]) * rng.uniform(0.6, 1.4)
    colour = (rng.randint(60, 255), rng.randint(60, 255), rng.randint(60, 255))
    accent = (rng.randint(30, 220), rng.randint(30, 220), rng.randint(30, 220))
    offset = rng.randint(-IMAGE_SIZE, 0)
    for k, x in enumerate(range(offset, IMAGE_SIZE * 3, width + gap)):
        dx = int(slope * IMAGE_SIZE)
        draw.line(
            [(x, 0), (x - dx, IMAGE_SIZE)],
            fill=colour if k % 2 == 0 else accent,
            width=width,
        )
    return img


def _render_blobs(rng: random.Random) -> Image.Image:
    """Smooth low-frequency colour field - visually distinct from the other two."""
    seed = rng.randint(0, 10_000)
    local = np.random.RandomState(seed)
    yy, xx = np.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE] / IMAGE_SIZE
    field_ = np.zeros((IMAGE_SIZE, IMAGE_SIZE, 3), dtype=np.float32)
    for channel in range(3):
        acc = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.float32)
        for _ in range(3):
            fx, fy = local.uniform(1.0, 3.0, size=2)
            phase = local.uniform(0, 2 * math.pi)
            acc += np.sin(2 * math.pi * (fx * xx + fy * yy) + phase)
        acc = (acc - acc.min()) / max(1e-6, float(np.ptp(acc)))
        field_[:, :, channel] = acc
    return Image.fromarray((field_ * 255).astype(np.uint8))


RENDERERS = {"circles": _render_circles, "stripes": _render_stripes, "blobs": _render_blobs}


def _save(img: Image.Image, path: Path, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, **kwargs)


def generate_demo_dataset(root: Path) -> dict:
    """Generate the dataset under ``root`` and return the ground-truth manifest."""
    root = Path(root)
    rng = random.Random(DEMO_SEED)
    issues: list[PlantedIssue] = []

    # ---- 1. Clean base images ------------------------------------------
    originals: dict[str, list[tuple[str, Image.Image]]] = {c: [] for c in CLASSES}
    for split, counts in (("train", TRAIN_COUNTS), ("val", VAL_COUNTS), ("test", TEST_COUNTS)):
        for cls, n in counts.items():
            for i in range(n):
                img = RENDERERS[cls](rng)
                rel = f"{split}/{cls}/{cls}_{split}_{i:03d}.png"
                _save(img, root / rel)
                if split == "train":
                    originals[cls].append((rel, img))

    def take(cls: str, index: int) -> tuple[str, Image.Image]:
        return originals[cls][index]

    # ---- 2. Exact cross-split duplicates --------------------------------
    for n, (cls, idx) in enumerate([("circles", 0), ("stripes", 1), ("blobs", 2)]):
        src_rel, img = take(cls, idx)
        dst_rel = f"test/{cls}/leak_exact_{n:02d}.png"
        _save(img, root / dst_rel)
        issues.append(
            PlantedIssue(
                issue_type="exact_cross_split",
                description="Byte-identical copy of a training image placed in the test split.",
                files=[src_rel, dst_rel],
                expected_finding_kind="exact_cross_split_leakage",
                expected_cross_split=True,
                detectable_by=["sha256"],
            )
        )

    # ---- 3. Recompressed duplicates -------------------------------------
    for n, (cls, idx) in enumerate([("circles", 3), ("stripes", 4)]):
        src_rel, img = take(cls, idx)
        dst_rel = f"test/{cls}/leak_recompressed_{n:02d}.jpg"
        _save(img, root / dst_rel, format="JPEG", quality=45)
        issues.append(
            PlantedIssue(
                issue_type="recompressed_cross_split",
                description="Same pixels re-encoded as a low-quality JPEG (different bytes).",
                files=[src_rel, dst_rel],
                expected_finding_kind="near_duplicate_cross_split_leakage",
                expected_cross_split=True,
                detectable_by=["phash", "embedding"],
            )
        )

    # ---- 4. Resized duplicates ------------------------------------------
    for n, (cls, idx) in enumerate([("circles", 5), ("blobs", 3)]):
        src_rel, img = take(cls, idx)
        small = img.resize((IMAGE_SIZE // 2, IMAGE_SIZE // 2), Image.Resampling.BILINEAR)
        dst_rel = f"test/{cls}/leak_resized_{n:02d}.png"
        _save(small.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR), root / dst_rel)
        issues.append(
            PlantedIssue(
                issue_type="resized_cross_split",
                description="Training image downscaled 2x then upscaled back.",
                files=[src_rel, dst_rel],
                expected_finding_kind="near_duplicate_cross_split_leakage",
                expected_cross_split=True,
                detectable_by=["phash", "embedding"],
            )
        )

    # ---- 5. Cropped variants --------------------------------------------
    # DCT-based pHash is not crop-robust (documented limitation), so cropped
    # copies are expected to surface via the embedding stage as "possible
    # semantic overlap" rather than as pHash near-duplicates. A 92% centre
    # crop is used: measured cosine similarity ~0.94-0.97 against the source
    # versus ~0.81 at the 99th percentile of unrelated pairs.
    for n, (cls, idx) in enumerate([("circles", 7), ("blobs", 4)]):
        src_rel, img = take(cls, idx)
        pad = IMAGE_SIZE // 24  # 92% linear crop
        crop = img.crop((pad, pad, IMAGE_SIZE - pad, IMAGE_SIZE - pad)).resize(
            (IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR
        )
        dst_rel = f"test/{cls}/leak_cropped_{n:02d}.png"
        _save(crop, root / dst_rel)
        issues.append(
            PlantedIssue(
                issue_type="cropped_cross_split",
                description=(
                    "Centre crop (92%) of a training image, rescaled to full size. "
                    "pHash is not crop-robust, so detection is expected from the "
                    "embedding stage as possible overlap."
                ),
                files=[src_rel, dst_rel],
                expected_finding_kind="possible_semantic_overlap",
                expected_cross_split=True,
                detectable_by=["embedding"],
            )
        )

    # ---- 6. Brightness variants -----------------------------------------
    for n, (cls, idx) in enumerate([("stripes", 8), ("circles", 9)]):
        src_rel, img = take(cls, idx)
        bright = ImageEnhance.Brightness(img).enhance(1.3)
        dst_rel = f"test/{cls}/leak_brightened_{n:02d}.png"
        _save(bright, root / dst_rel)
        issues.append(
            PlantedIssue(
                issue_type="brightened_cross_split",
                description="Training image with a 1.3x global brightness gain.",
                files=[src_rel, dst_rel],
                expected_finding_kind="near_duplicate_cross_split_leakage",
                expected_cross_split=True,
                detectable_by=["phash", "embedding"],
            )
        )

    # ---- 7. Conflicting label -------------------------------------------
    src_rel, img = take("circles", 11)
    dst_rel = "train/stripes/conflict_same_image_as_circles.png"
    _save(img, root / dst_rel)
    issues.append(
        PlantedIssue(
            issue_type="conflicting_label",
            description="One identical image filed under two different classes in train.",
            files=[src_rel, dst_rel],
            expected_finding_kind="conflicting_label_duplicate",
            expected_conflicting_label=True,
            detectable_by=["sha256"],
        )
    )

    # ---- 8. Corrupt file --------------------------------------------------
    corrupt_rel = "train/blobs/corrupt_truncated.jpg"
    corrupt_path = root / corrupt_rel
    good = RENDERERS["blobs"](rng)
    _save(good, corrupt_path, format="JPEG", quality=90)
    data = corrupt_path.read_bytes()
    # Keep the JPEG signature (so it passes magic-byte sniffing) but truncate
    # the scan data so decoding must fail. This exercises the corrupt path.
    corrupt_path.write_bytes(data[: len(data) // 3])
    issues.append(
        PlantedIssue(
            issue_type="corrupt_file",
            description="Truncated JPEG: valid signature, undecodable scan data.",
            files=[corrupt_rel],
            expected_finding_kind="corrupt_sample",
            detectable_by=["decoder"],
        )
    )

    # ---- 9. Class imbalance ------------------------------------------------
    issues.append(
        PlantedIssue(
            issue_type="class_imbalance",
            description=(
                f"'blobs' is under-represented in train "
                f"({TRAIN_COUNTS['blobs']}) versus 'circles' ({TRAIN_COUNTS['circles']})."
            ),
            files=[],
            expected_finding_kind="class_imbalance",
            detectable_by=["inventory"],
        )
    )

    manifest = {
        "name": "SplitShield synthetic demo dataset",
        "seed": DEMO_SEED,
        "image_size": IMAGE_SIZE,
        "classes": list(CLASSES),
        "counts": {"train": TRAIN_COUNTS, "val": VAL_COUNTS, "test": TEST_COUNTS},
        "license": "Generated programmatically by SplitShield; no third-party imagery.",
        "planted_issues": [asdict(i) for i in issues],
        "planted_issue_count": len(issues),
    }
    (root / "GROUND_TRUTH.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def ground_truth_path(root: Path) -> Path:
    return Path(root) / "GROUND_TRUTH.json"
