"""ZIP safety: traversal, bombs, type confusion, corrupt tolerance."""
from __future__ import annotations

import zipfile

import pytest

from app.config import settings
from app.pipeline.ingest import (
    IngestError,
    classify_path,
    extract_dataset,
    inspect_archive,
    is_safe_member_name,
    sniff_format,
)


class TestPathSafety:
    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "train/../../escape.jpg",
            "/etc/passwd",
            "C:\\windows\\evil.jpg",
            "train/a\x00.jpg",
            "..\\..\\win.jpg",
        ],
    )
    def test_rejects_unsafe_names(self, name):
        assert not is_safe_member_name(name)

    def test_accepts_normal_names(self):
        assert is_safe_member_name("dataset/train/cat/img (1).jpg")

    def test_traversal_entry_never_extracted(self, tmp_path, make_zip, make_image):
        zip_path = make_zip(
            {
                "train/a/ok.png": make_image(1),
                "test/a/ok2.png": make_image(2),
            }
        )
        # Append a hostile member manually.
        with zipfile.ZipFile(zip_path, "a") as zf:
            zf.writestr("../../../evil.png", b"\x89PNG\r\n\x1a\nfake")
        out = tmp_path / "out"
        result = extract_dataset(zip_path, out)
        assert any("Unsafe path" in r.reason for r in result.rejected)
        # Nothing may exist outside the extraction root.
        escaped = tmp_path.parent / "evil.png"
        assert not escaped.exists()
        assert all(out in p.parents or p == out for p in out.rglob("*"))


class TestBombGuards:
    def test_rejects_not_a_zip(self, tmp_path):
        bad = tmp_path / "x.zip"
        bad.write_bytes(b"definitely not a zip")
        with pytest.raises(IngestError, match="not a valid ZIP"):
            inspect_archive(bad)

    def test_rejects_excessive_entry_count(self, tmp_path, monkeypatch, make_zip, make_image):
        monkeypatch.setattr(settings, "max_file_count", 3)
        zip_path = make_zip({f"train/a/{i}.png": make_image(i) for i in range(5)})
        with pytest.raises(IngestError, match="exceeding the limit"):
            inspect_archive(zip_path)

    def test_rejects_uncompressed_total(self, tmp_path, monkeypatch, make_zip, make_image):
        monkeypatch.setattr(settings, "max_uncompressed_bytes", 1000)
        zip_path = make_zip({"train/a/big.png": make_image(1, size=256)})
        with pytest.raises(IngestError, match="maximum uncompressed size"):
            inspect_archive(zip_path)

    def test_flags_high_compression_ratio(self, tmp_path, make_image, make_zip):
        zip_path = make_zip({"train/a/ok.png": make_image(1)})
        with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("train/a/bomb.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 5_000_000)
        accepted, rejected, _ = inspect_archive(zip_path)
        assert any("compression ratio" in r.reason for r in rejected)
        assert len(accepted) == 1


class TestTypeValidation:
    def test_sniffs_signatures(self):
        assert sniff_format(b"\xff\xd8\xff\xe1" + b"x" * 12) == "JPEG"
        assert sniff_format(b"\x89PNG\r\n\x1a\n" + b"x" * 8) == "PNG"
        assert sniff_format(b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 4) == "WEBP"
        assert sniff_format(b"GIF89a" + b"x" * 10) is None
        assert sniff_format(b"MZ\x90\x00" + b"x" * 12) is None

    def test_extension_lying_about_content_rejected(self, tmp_path, make_zip, make_image):
        zip_path = make_zip(
            {
                "train/a/real.png": make_image(1),
                "test/a/real2.png": make_image(2),
                "train/a/fake.png": b"MZ\x90\x00 this is a PE executable not an image",
            }
        )
        result = extract_dataset(zip_path, tmp_path / "out")
        assert len(result.files) == 2
        assert any("not a recognised" in r.reason for r in result.rejected)

    def test_unsupported_extension_rejected(self, tmp_path, make_zip, make_image):
        zip_path = make_zip(
            {"train/a/ok.png": make_image(1), "train/a/vid.mp4": b"\x00" * 100}
        )
        accepted, rejected, _ = inspect_archive(zip_path)
        assert any("Unsupported extension" in r.reason for r in rejected)


class TestLayoutParsing:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("train/cat/a.jpg", ("train", "cat")),
            ("dataset/train/cat/a.jpg", ("train", "cat")),
            ("VALID/dog/b.png", ("val", "dog")),
            ("wrapper/TEST/bird/nested/c.webp", ("test", "bird/nested")),
            ("images/a.jpg", None),
            ("train/naked.jpg", None),
        ],
    )
    def test_classify(self, path, expected):
        got = classify_path(path)
        if expected is None:
            assert got is None
        else:
            assert (got[0].value, got[1]) == expected

    def test_no_images_raises(self, tmp_path, make_zip):
        zip_path = make_zip({"readme.txt": b"hello"})
        with pytest.raises(IngestError, match="No supported images"):
            inspect_archive(zip_path)
