# BUILD_STATUS

Live status of the SplitShield hackathon build. Every ✅ Verified item lists
the exact command used and its observed result in the build environment
(Linux, Python 3.11.15, Node 22.22.2, 4 CPU, no GPU, restricted egress).

## Completed & verified

| Item | Verification command | Result |
| --- | --- | --- |
| Backend unit/integration tests | `backend/.venv/bin/python -m pytest tests/ -q` | **84 passed** in ~10 s |
| ZIP traversal/zip-bomb/type-confusion guards | `pytest tests/test_ingest.py` | 20 passed (hostile members rejected, nothing escapes extraction root) |
| Exact + perceptual detection, classification | `pytest tests/test_detection.py` | 15 passed |
| Integrity Score determinism & normalisation | `pytest tests/test_scoring_repair.py` | 13 passed |
| Repair rules (test-set protection, conflict exclusion, review effects) | same file | included above |
| Evaluation gap eligibility, determinism, quarantine | `pytest tests/test_evaluation.py` | 9 passed |
| API job flow, reviews, exports, deletion | `pytest tests/test_api.py` | 20 passed |
| Demo ground-truth recovery | `pytest tests/test_demo_ground_truth.py` | 7 passed — **13/13 planted pairs recovered** with expected-or-stronger evidence; byte-identical regeneration |
| Frontend type check (strict) | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | 0 errors, 0 warnings |
| Frontend production build | `npm run build` | ✓ all routes compile (Next.js 15, Turbopack) |
| E2E browser journey (open app → demo → dashboard → review pair → repair export → report JSON) | `npx playwright test` | **1 passed** (~4 s), no console-breaking errors |
| Backend health check | `curl localhost:8000/api/health` | `{"status":"ok","version":"0.1.0"}` |
| Real upload path (ZIP with planted leak) | `pytest tests/test_api.py::TestJobFlow::test_upload_real_zip_completes` | completes; exact cross-split leak found |
| Demo runs through the identical upload pipeline | `POST /api/audits/demo` | score 29.1/100, 3 exact leaks, 7 near-dups, 1 conflict, 1 corrupt — all computed live |
| Observed Evaluation Gap on demo | dashboard / `GET .../summary` | orig acc 0.816 [CI 0.684–0.921] → cleaned 0.793, gap 0.023, 9 quarantined, seed 1337 |
| All exports | `curl` findings.csv / repair.csv / repair.json / report.json / report.html | all HTTP 200 with real content |
| Deletion removes DB rows + disk artefacts | `DELETE /api/audits/{id}`, then status + `ls` | 404 afterwards; storage dir gone |
| Retention sweep | background task (unit-covered via `sweep_expired`) | expired jobs purged |
| Responsive layout, no horizontal scroll | Playwright viewport probe 1366×900 & 390×844 | `body overflow-x = 0px` on both |
| Browser console clean | Playwright console capture | only a favicon 404, fixed by adding `app/icon.svg` |
| `docker compose config` | `docker compose config --quiet` | valid |

## Honest limitations / not verified here

| Item | Status | Why |
| --- | --- | --- |
| Docker image build & containerised smoke test | ⚠️ **Not verifiable in this environment** | egress policy blocks Docker Hub blob downloads (`python:3.11-slim` pull → 403). Dockerfiles mirror the verified bare-process commands; run `docker compose up --build` on a normal network and check `/api/health`. |
| Learned embedding backend (MobileNetV3) | ⚠️ Implemented, auto-detected, **not exercisable here** | pytorch.org and huggingface.co blocked, so pretrained weights cannot download. The validated classical descriptor is active and disclosed in UI/report; `SPLITSHIELD_EMBEDDING_BACKEND=torch` will engage the learned path where torch + weights exist. |
| Video (MP4 frame sampling) | ❌ Not implemented | out of MVP scope; pipeline sample abstraction is video-ready. Never claimed in UI (`/api/capabilities` reports `video_support: false`). |
| Public deployment | ❌ Not deployed | no hosting target in this environment. `DEPLOYMENT.md` covers the procedure; do not claim deployment until a public URL is tested. |

## Pending / nice-to-have (not blocking)

- FAISS backend for very large datasets (pure-sklearn k-NN is the active path)
- Repaired-ZIP download (manifest export chosen deliberately; documented)
- Multi-user session scoping for hostile-multi-tenant public demos

## How to reproduce the full verification

```bash
# 1. backend deps + tests
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q                      # expect: 84 passed

# 2. frontend checks + build
cd ../frontend && npm ci
npx tsc --noEmit && npm run lint && npm run build

# 3. run the stack
cd ../backend && .venv/bin/uvicorn app.main:app --port 8000 &
cd ../frontend && npm run start -- --port 3000 &

# 4. E2E + smoke
cd ../frontend && npx playwright test                     # expect: 1 passed
curl -s localhost:8000/api/health                         # {"status":"ok",...}
```

## Update 2026-08-22 — detection-style (unlabeled) dataset support

- [x] `classify_path` accepts images directly inside split folders (YOLO layout,
  `images/train/*.jpg`), assigning the `(unlabeled)` pseudo-class.
- [x] Conflicting-label logic never fires when either side is unlabeled
  (`labels_conflict` in `classify.py`).
- [x] Evaluation experiment disables with an explicit reason for unlabeled datasets.
- [x] Upload page documents both accepted layouts.
- [x] Verified: 89 backend tests pass; E2E YOLO-layout ZIP through the real API
  detects a planted cross-split exact duplicate, disables eval with reason,
  generates repair manifest and HTML/JSON reports.

## Update 2026-08-22 — Render deployment blueprint

- [x] `render.yaml` Blueprint: backend (Python native runtime, uvicorn on
  $PORT, health check on /api/health) + frontend (Node runtime, Next.js).
- [x] `docs/DEPLOY_RENDER.md` click-by-click guide with post-deploy URL
  wiring and free-plan limitations.
- [ ] NOT yet verified live: the blueprint has not been deployed to a real
  Render account from this environment. First deploy should follow the smoke
  checklist in docs/DEPLOY_RENDER.md before the URL is shared publicly.

## Update 2026-08-22 — per-device audit history

- [x] "Recent audits on this device" on the Analyze page: entries recorded in
  the visitor's localStorage when an audit is created (upload or demo), with
  source badge, timestamp and remove button (`frontend/lib/history.ts`).
- [x] Privacy-preserving by design: no server-side cross-user audit listing
  exists; history lives only in each visitor's own browser. Expired audits
  resolve to the existing "Audit not found" page.
- [x] Verified: tsc --noEmit clean, next build passes.
- Live deployment verified by the user on Render:
  https://splitshield-web.onrender.com (demo dataset ran end to end, report
  rendered).
