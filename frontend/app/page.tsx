import Link from "next/link";

const STEPS = [
  {
    n: "1",
    title: "Upload",
    body: "Drop a ZIP with train/val/test folders. Files are validated by content signature, extracted safely, and never executed.",
  },
  {
    n: "2",
    title: "Inspect",
    body: "SHA-256 exact matching, perceptual hashing and appearance-embedding search surface duplicate and near-duplicate pairs, ranked by severity with side-by-side evidence.",
  },
  {
    n: "3",
    title: "Repair & verify",
    body: "Export a repaired split manifest, then measure the Observed Evaluation Gap: how a diagnostic classifier's test accuracy changes once leaked samples are quarantined.",
  },
];

const DIFFERENTIATORS = [
  {
    title: "Not another duplicate finder",
    body: "Duplicate detection itself isn't new — FiftyOne, CleanVision and Cleanlab all do it well. SplitShield's focus is the workflow after detection: explaining evidence, repairing splits, and quantifying what the leakage is associated with.",
  },
  {
    title: "Quantified, carefully",
    body: "The Observed Evaluation Gap re-scores the same trained model on a leakage-quarantined test subset, with bootstrap confidence intervals. It is reported as evidence of sensitivity — not as causal proof.",
  },
  {
    title: "Reproducible audits",
    body: "Every report carries the dataset fingerprint, analysis configuration, package versions and random seed, plus full CSV/JSON exports of findings and repair manifests.",
  },
];

export default function LandingPage() {
  return (
    <div>
      <section className="pt-20 pb-14 text-center">
        <p className="mb-4 inline-block rounded-full border border-edge bg-panel px-4 py-1 text-xs uppercase tracking-widest text-accent">
          Dataset integrity auditing
        </p>
        <h1 className="mx-auto max-w-3xl text-5xl font-bold tracking-tight">
          Detect, repair, and quantify hidden leakage in computer-vision datasets
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-muted">
          Duplicate and near-duplicate images that cross your train/test boundary
          quietly inflate reported accuracy. SplitShield finds them, shows you the
          evidence, proposes a safer split, and measures the observed difference.
        </p>
        <div className="mt-10 flex justify-center gap-4">
          <Link
            href="/upload"
            className="rounded-lg bg-accent px-6 py-3 font-semibold text-bg transition hover:brightness-110"
          >
            Analyze a dataset
          </Link>
          <Link
            href="/upload?demo=1"
            className="rounded-lg border border-edge bg-panel px-6 py-3 font-semibold text-ink transition hover:border-accent-dim"
          >
            Try demonstration dataset
          </Link>
        </div>
        <p className="mt-6 text-xs text-muted">
          Analysis runs entirely on this server. Uploads are never shared, never used
          for training, and are deleted automatically after the retention window — or
          instantly with one click.
        </p>
      </section>

      <section aria-labelledby="steps-heading" className="py-12">
        <h2 id="steps-heading" className="sr-only">
          How it works
        </h2>
        <div className="grid gap-6 md:grid-cols-3">
          {STEPS.map((s) => (
            <div
              key={s.n}
              className="rounded-xl border border-edge bg-raised p-6"
            >
              <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-full border border-accent-dim text-accent font-bold">
                {s.n}
              </div>
              <h3 className="mb-2 font-semibold text-ink">{s.title}</h3>
              <p className="text-sm leading-relaxed text-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="diff-heading" className="py-12">
        <h2 id="diff-heading" className="mb-6 text-2xl font-semibold">
          How SplitShield differs
        </h2>
        <div className="grid gap-6 md:grid-cols-3">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} className="rounded-xl border border-edge bg-raised p-6">
              <h3 className="mb-2 font-semibold text-accent">{d.title}</h3>
              <p className="text-sm leading-relaxed text-muted">{d.body}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 text-sm text-muted">
          Full method details, scoring formula, and known failure modes are on the{" "}
          <Link href="/methodology" className="text-accent underline-offset-2 hover:underline">
            methodology page
          </Link>
          .
        </p>
      </section>

      <section
        aria-labelledby="privacy-heading"
        className="my-12 rounded-xl border border-edge bg-panel p-8"
      >
        <h2 id="privacy-heading" className="mb-3 text-xl font-semibold">
          Privacy commitments
        </h2>
        <ul className="grid gap-2 text-sm text-muted md:grid-cols-2">
          <li>• No facial recognition or identity inference — ever.</li>
          <li>• No external services receive your images by default.</li>
          <li>• Configurable retention; deletion is one click and immediate.</li>
          <li>• Internal storage uses random identifiers, never your file paths.</li>
          <li>• Uploaded archives are content-validated and never executed.</li>
          <li>• Only audit datasets you are legally permitted to process.</li>
        </ul>
      </section>
    </div>
  );
}
