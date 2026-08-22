"""API flow: health, demo job lifecycle, reviews, repair, exports, deletion."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import jobs as jobs_mod
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _wait_complete(client, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/audits/{job_id}").json()
        if status["status"] in ("complete", "failed"):
            return status
        time.sleep(0.5)
    raise TimeoutError("job did not finish")


@pytest.fixture()
def demo_job(client):
    resp = client.post("/api/audits/demo", json={})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    status = _wait_complete(client, job_id)
    assert status["status"] == "complete", status
    return job_id


class TestHealth:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_capabilities_honest(self, client):
        caps = client.get("/api/capabilities").json()
        assert caps["video_support"] is False
        assert caps["limits"]["retention_hours"] > 0


class TestJobFlow:
    def test_unknown_job_404(self, client):
        assert client.get("/api/audits/job_nope").status_code == 404

    def test_upload_rejects_non_zip(self, client):
        resp = client.post(
            "/api/audits/upload",
            files={"file": ("data.tar", b"not a zip", "application/x-tar")},
        )
        assert resp.status_code == 415

    def test_upload_rejects_empty(self, client):
        resp = client.post(
            "/api/audits/upload", files={"file": ("d.zip", b"", "application/zip")}
        )
        assert resp.status_code == 422

    def test_upload_invalid_zip_fails_job_gracefully(self, client):
        resp = client.post(
            "/api/audits/upload",
            files={"file": ("d.zip", b"PK\x03\x04 garbage truncated", "application/zip")},
        )
        assert resp.status_code == 202
        status = _wait_complete(client, resp.json()["job_id"])
        assert status["status"] == "failed"
        assert "ZIP" in status["error"] or "images" in status["error"]

    def test_upload_real_zip_completes(self, client, make_zip, make_image):
        zip_path = make_zip(
            {
                **{f"train/a/t{i}.png": make_image(i) for i in range(6)},
                **{f"train/b/u{i}.png": make_image(100 + i) for i in range(6)},
                **{f"test/a/x{i}.png": make_image(200 + i) for i in range(3)},
                **{f"test/b/y{i}.png": make_image(300 + i) for i in range(3)},
                "test/a/leak.png": make_image(0),  # exact dup of train/a/t0
            }
        )
        with open(zip_path, "rb") as fh:
            resp = client.post(
                "/api/audits/upload", files={"file": ("ds.zip", fh, "application/zip")}
            )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        status = _wait_complete(client, job_id)
        assert status["status"] == "complete"
        summary = client.get(f"/api/audits/{job_id}/summary").json()
        assert summary["counts"]["exact_cross_split"] >= 1
        assert summary["inventory"]["total_samples"] == 19


class TestDemoResults:
    def test_summary_has_real_values(self, client, demo_job):
        summary = client.get(f"/api/audits/{demo_job}/summary").json()
        assert summary["counts"]["exact_cross_split"] == 3
        assert summary["counts"]["conflicting_label"] == 1
        assert summary["counts"]["corrupt"] == 1
        assert 0 <= summary["integrity"]["score"] <= 100
        assert summary["integrity"]["components"]

    def test_findings_pagination_and_filters(self, client, demo_job):
        page = client.get(
            f"/api/audits/{demo_job}/findings", params={"page_size": 5}
        ).json()
        assert page["total"] >= 10
        assert len(page["items"]) == 5

        crit = client.get(
            f"/api/audits/{demo_job}/findings", params={"severity": "critical"}
        ).json()
        assert all(i["severity"] == "critical" for i in crit["items"])

        cross = client.get(
            f"/api/audits/{demo_job}/findings", params={"split_pair": "train-test"}
        ).json()
        assert all(
            sorted((i["split_a"], i["split_b"])) == ["test", "train"] for i in cross["items"]
        )

    def test_images_served(self, client, demo_job):
        page = client.get(f"/api/audits/{demo_job}/findings").json()
        sid = page["items"][0]["sample_a"]["id"]
        resp = client.get(f"/api/audits/{demo_job}/images/{sid}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/")

    def test_image_path_injection_404(self, client, demo_job):
        assert client.get(f"/api/audits/{demo_job}/images/..%2F..%2Fetc").status_code == 404


class TestReviewPersistence:
    def test_review_roundtrip(self, client, demo_job):
        finding = client.get(f"/api/audits/{demo_job}/findings").json()["items"][0]
        fid = finding["id"]
        resp = client.patch(
            f"/api/audits/{demo_job}/findings/{fid}/review",
            json={"decision": "confirmed", "note": "checked by hand"},
        )
        assert resp.status_code == 200
        got = client.get(f"/api/audits/{demo_job}/findings").json()["items"][0]
        assert got["review"] == {"decision": "confirmed", "note": "checked by hand"}

        # Reset to unreviewed deletes the row.
        client.patch(
            f"/api/audits/{demo_job}/findings/{fid}/review", json={"decision": "unreviewed"}
        )
        got = client.get(f"/api/audits/{demo_job}/findings").json()["items"][0]
        assert got["review"]["decision"] == "unreviewed"

    def test_review_unknown_finding_404(self, client, demo_job):
        resp = client.patch(
            f"/api/audits/{demo_job}/findings/f_9999_9999/review",
            json={"decision": "safe"},
        )
        assert resp.status_code == 404

    def test_review_affects_repair_not_evidence(self, client, demo_job):
        crit = client.get(
            f"/api/audits/{demo_job}/findings", params={"severity": "critical"}
        ).json()["items"]
        target = next(f for f in crit if f["kind"] == "exact_cross_split_leakage")
        before = client.get(f"/api/audits/{demo_job}/repair").json()

        client.patch(
            f"/api/audits/{demo_job}/findings/{target['id']}/review",
            json={"decision": "safe"},
        )
        after = client.post(f"/api/audits/{demo_job}/repair", json={}).json()
        assert after["moves"] <= before["moves"]

        # Evidence unchanged: the finding still exists with original values.
        still = client.get(
            f"/api/audits/{demo_job}/findings", params={"severity": "critical"}
        ).json()["items"]
        assert any(f["id"] == target["id"] for f in still)


class TestExports:
    def test_findings_csv(self, client, demo_job):
        resp = client.get(f"/api/audits/{demo_job}/findings.csv")
        assert resp.status_code == 200
        lines = resp.text.strip().splitlines()
        assert lines[0].startswith("finding_id,kind,severity")
        assert len(lines) > 5

    def test_repair_exports(self, client, demo_job):
        csv_resp = client.get(f"/api/audits/{demo_job}/repair.csv")
        assert csv_resp.status_code == 200
        assert "proposed_split" in csv_resp.text.splitlines()[0]
        json_resp = client.get(f"/api/audits/{demo_job}/repair.json")
        assert json_resp.status_code == 200
        assert "entries" in json_resp.json()

    def test_report_json_complete(self, client, demo_job):
        report = client.get(f"/api/audits/{demo_job}/report.json").json()
        for key in ("audit", "configuration", "environment", "summary",
                    "evaluation", "repair_plan", "findings", "limitations"):
            assert key in report, key
        assert report["audit"]["dataset_fingerprint_sha256"]
        assert report["environment"]["package_versions"]["numpy"]

    def test_report_html_renders(self, client, demo_job):
        resp = client.get(f"/api/audits/{demo_job}/report.html")
        assert resp.status_code == 200
        assert "<title>SplitShield audit report" in resp.text
        assert "Integrity Score" in resp.text


class TestDeletion:
    def test_delete_removes_everything(self, client, demo_job):
        job = jobs_mod.get_job(demo_job)
        storage = job["storage_path"]
        assert storage

        resp = client.delete(f"/api/audits/{demo_job}")
        assert resp.status_code == 200

        assert client.get(f"/api/audits/{demo_job}").status_code == 404
        assert client.get(f"/api/audits/{demo_job}/summary").status_code == 404

        from pathlib import Path

        assert not Path(storage).exists()

    def test_delete_unknown_404(self, client):
        assert client.delete("/api/audits/job_missing").status_code == 404
