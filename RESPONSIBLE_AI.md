# Responsible AI & data handling

## What SplitShield is

A dataset-quality diagnostic for image-classification datasets: it finds
duplicate and near-duplicate images across train/val/test splits, helps a
human review the evidence, proposes a safer split, and measures the observed
difference in a diagnostic classifier's evaluation.

## What SplitShield deliberately does not do

* **No facial recognition** and no face detection of any kind.
* **No identity inference** — no attempt to determine who or what kind of
  person appears in an image.
* **No external transmission of images** — analysis is entirely local to the
  deployment; no third-party API receives uploaded data by default, and no
  such integration is enabled in this release.
* **No training on user data** — uploads are used only for the requesting
  audit and deleted afterwards.
* **No automatic dataset modification** — repair output is a manifest of
  proposals; original files are never altered or deleted.

## Careful claims policy

* Only byte-identical (SHA-256) matches are called **confirmed** duplicates.
* Perceptual and embedding matches are labeled *likely*, *possible* or
  *requires human review* — never silently treated as ground truth.
* The evaluation metric is named the **Observed Evaluation Gap** and every
  result ships with explicit warnings: it is evidence of sensitivity to
  leakage, **not proof of causation**; removing samples changes the test
  population; small samples are unstable.
* The Integrity Score is a documented deterministic formula, not a model
  output, and its full breakdown is always shown.
* When a capability is unavailable (e.g. learned embeddings without network
  access), the product states the fallback plainly rather than simulating.

## Data lifecycle

1. Upload → streamed to disk under a random name, size-capped.
2. Extraction → validated, re-signed, stored under generated internal IDs.
3. Analysis → metadata and findings in SQLite; images stay on local disk.
4. Retention → automatic sweep deletes all artefacts after
   `SPLITSHIELD_RETENTION_HOURS` (default 24 h).
5. Manual deletion → "Delete my audit" removes files and DB rows immediately.

## User obligations

Upload only datasets you are legally permitted to process. SplitShield is not
a tool for auditing scraped personal data, re-identifying individuals, or
laundering provenance of improperly obtained imagery.

## Failure modes users should know

* Transformed copies (rotation, flip, heavy crop) can evade detection: a
  clean report is *evidence*, not certification.
* Similarity thresholds trade recall against noise; review decisions matter.
* The diagnostic classifier is intentionally simple; production models may
  react differently to the same leakage.
