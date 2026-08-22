# Deploying SplitShield to Render

This repo ships a `render.yaml` Blueprint that creates both services (FastAPI
backend + Next.js frontend) in one go.

## Steps

1. **Create an account** at https://render.com (sign in with GitHub).
2. Click **New → Blueprint**, and select the `SplitShield` repository.
   Pick the branch you want to deploy. Render reads `render.yaml` and shows
   two services: `splitshield-api` and `splitshield-web`.
3. Click **Apply**. Both services build and deploy (first build takes a few
   minutes; the frontend build is the slower one).
4. **Check the assigned URLs.** Open each service and note its public URL.
   If they are exactly `https://splitshield-api.onrender.com` and
   `https://splitshield-web.onrender.com`, you are done — skip step 5.
5. **If Render appended a suffix** (e.g. `splitshield-api-x7k2.onrender.com`),
   wire the real URLs together:
   - `splitshield-web` → Environment → set `NEXT_PUBLIC_API_URL` to the
     api service's actual URL → Save (this rebuilds the frontend).
   - `splitshield-api` → Environment → set `SPLITSHIELD_CORS_ORIGINS` to the
     web service's actual URL → Save.
6. Open the web URL, click **Try demonstration dataset**, and confirm an
   audit completes end to end.

## Smoke checklist after deploy

- `https://<api host>/api/health` returns a healthy JSON response.
- `https://<api host>/docs` serves the OpenAPI documentation.
- The demo dataset completes and the report page renders.
- Uploading a small ZIP works; "Delete this audit" removes it.

## Free-plan behaviour

- Services **sleep after ~15 minutes idle**; the next visit takes ~30-60 s to
  wake. For a judged demo, open the site once shortly before presenting.
- **512 MB RAM**: the blueprint caps uploads at 256 MiB. Large datasets can
  exhaust memory during analysis; use a paid instance (or run locally) for
  those.
- **Ephemeral disk**: uploads and results vanish on redeploy/restart. This is
  consistent with the app's own retention policy (audits auto-delete after
  `SPLITSHIELD_RETENTION_HOURS`, default 24 h).
- No secrets are required; every variable in `render.yaml` is safe to be
  public.
