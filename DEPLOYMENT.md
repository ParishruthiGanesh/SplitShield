# Deployment guide

## Option A — Docker Compose (recommended)

```bash
git clone <repo> && cd splitshield
docker compose up --build -d
```

* Frontend: `http://<host>:3000`
* API + OpenAPI docs: `http://<host>:8000/docs`
* Health checks are baked into both images (`/api/health`, `/`), and
  `docker compose ps` shows container health.
* Uploaded data lives in the `splitshield-data` named volume.

For a public host, set the browser-reachable API origin at build time:

```bash
docker compose build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com frontend
```

and put both services behind TLS (Caddy/nginx/Traefik). Restrict
`SPLITSHIELD_CORS_ORIGINS` to the real frontend origin.

## Option B — bare processes

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
SPLITSHIELD_DATA_DIR=/var/lib/splitshield \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend
cd frontend && npm ci && NEXT_PUBLIC_API_URL=https://api.example.com npm run build
npm run start -- --port 3000
```

Run both under systemd or a supervisor; point a reverse proxy at them.

## Production environment variables

| Variable | Recommended production value |
| --- | --- |
| `SPLITSHIELD_DATA_DIR` | persistent volume, e.g. `/var/lib/splitshield` |
| `SPLITSHIELD_CORS_ORIGINS` | exact frontend origin(s), no wildcards |
| `SPLITSHIELD_RETENTION_HOURS` | as short as your users tolerate (e.g. 4) |
| `SPLITSHIELD_MAX_UPLOAD_BYTES` | size your disk for `N concurrent × limit` |
| `SPLITSHIELD_MAX_CONCURRENT_JOBS` | ≤ CPU cores − 1 |
| `NEXT_PUBLIC_API_URL` | public API origin (build-time for the frontend) |

No secrets are required. If you add any (e.g. object-storage credentials
later), supply them via environment variables — never commit them.

## Health checks

* Liveness/readiness: `GET /api/health` → `{"status":"ok"}` (also verifies
  SQLite connectivity).
* Honest capability probe: `GET /api/capabilities` reports the active
  embedding backend, limits and defaults — useful for smoke tests after
  deploy.

## Public demo checklist

* [ ] No registration required — the landing page's "Try demonstration
      dataset" button must work anonymously.
* [ ] Per-audit isolation: audits are addressed by unguessable job IDs and
      images are only served through the owning audit's endpoint. For a
      hostile-multi-tenant deployment, add session-scoped audit listing
      (IDs are never enumerable via the API).
* [ ] Resource limits visibly labeled: the upload page displays the active
      size/count/retention limits pulled from `/api/capabilities`.
* [ ] Optional-ML degradation: with `SPLITSHIELD_EMBEDDING_BACKEND=off` (or
      torch unavailable) the app still runs exact + perceptual analysis and
      says so; the evaluation experiment reports exactly why it is skipped.
* [ ] Deletion works end-to-end ("Delete my audit" → 404 afterwards).

## Verification status in this repository

`docker compose config` validates. Full image builds and the containerised
smoke test could **not** be completed in the authoring environment because
its egress policy blocks Docker Hub blob downloads (`python:3.11-slim` /
`node:22-slim` pulls fail with 403). The Dockerfiles mirror the exact
commands used by the verified bare-process setup; run
`docker compose up --build` in a normal environment and check
`http://localhost:8000/api/health` before announcing a deployment. Do not
claim the app is deployed until the public URL has been tested.
