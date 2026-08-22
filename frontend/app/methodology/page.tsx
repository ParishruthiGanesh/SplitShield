export const metadata = { title: "Methodology & limitations — SplitShield" };

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="mt-10">
      <h2 id={`${id}-h`} className="mb-3 text-xl font-semibold text-accent">
        {title}
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-muted [&_strong]:text-ink">
        {children}
      </div>
    </section>
  );
}

export default function MethodologyPage() {
  return (
    <div className="mx-auto max-w-3xl pt-12">
      <h1 className="text-3xl font-bold tracking-tight">Methodology & limitations</h1>
      <p className="mt-2 text-muted">
        Everything SplitShield reports is computed by the documented methods below.
        Nothing on the dashboard is estimated by a language model or hard-coded.
      </p>

      <Section id="exact" title="Exact duplicates — SHA-256">
        <p>
          Every valid image file is hashed with <strong>SHA-256</strong> over its raw
          bytes. Identical digests mean byte-identical files, so these findings are
          labeled <strong>“Confirmed exact duplicate”</strong> — the only confidence
          level SplitShield states without qualification. Pairs crossing train/test
          receive <strong>critical</strong> severity; identical files filed under
          different classes are flagged as <strong>conflicting-label duplicates</strong>.
        </p>
      </Section>

      <Section id="phash" title="Near duplicates — perceptual hashing (pHash)">
        <p>
          Each image is decoded, converted to greyscale, resized, and passed through a
          DCT-based perceptual hash (<code>imagehash.phash</code>, 64 bits). Pairs whose{" "}
          <strong>Hamming distance</strong> falls at or below the configured threshold
          (default 8) become candidates; at or below the strong threshold (default 4)
          they are labeled <strong>“Likely near duplicate”</strong>, otherwise{" "}
          <strong>“Requires human review.”</strong>
        </p>
        <p>
          pHash is robust to rescaling, recompression and moderate brightness changes,
          but <strong>not</strong> to aggressive crops, rotations or flips — a documented
          failure mode, partially covered by the embedding stage.
        </p>
      </Section>

      <Section id="embedding" title="Similarity search — image embeddings">
        <p>
          Each image is embedded into a normalized feature vector and compared by{" "}
          <strong>cosine similarity</strong> using top-k nearest-neighbour search (never
          an unbounded all-pairs sweep). Pairs above the threshold (default 0.90) are
          reported as <strong>“Possible semantic overlap — requires human review”</strong>{" "}
          and are never automatically treated as duplicates.
        </p>
        <p>
          The backend is selected at runtime and reported honestly in the UI and report:
          a learned <strong>MobileNetV3-Small (ImageNet)</strong> feature extractor when
          PyTorch and its pretrained weights are available, otherwise a{" "}
          <strong>classical appearance descriptor</strong> (contrast-normalised structure
          map, illumination-invariant chromaticity, gradient-orientation histograms).
          The classical descriptor measures <em>visual appearance</em>, not conceptual
          meaning — validated on transformed copies (rescale/recompress/crop/brightness
          ≥0.94 cosine) versus unrelated images (≤0.81 at the 99th percentile in our
          synthetic benchmark).
        </p>
      </Section>

      <Section id="score" title="Dataset Integrity Score">
        <p>
          The 0–100 score is a <strong>deterministic weighted formula</strong>, published
          in full in the report and in <code>METHODOLOGY.md</code>:
        </p>
        <pre className="overflow-x-auto rounded-lg border border-edge bg-raised p-3 text-xs">
{`score = clamp(100 − Σ weight_c · min(1, rate_c / saturation_c), 0, 100)
rate_c = distinct affected samples in category c ÷ total valid samples

weights: exact cross-split 35 · conflicting labels 25 · near-dup cross-split 20
         possible overlap 8 · corrupt 6 · same-split redundancy 5
         class imbalance 3 · split imbalance 3`}
        </pre>
        <p>
          Rates are normalized by dataset size, so ten leaked pairs cost a 100-image
          dataset far more than a 100,000-image one. Human review can exclude findings
          from the score recomputation but never edits the stored evidence.
        </p>
      </Section>

      <Section id="repair" title="Split repair rules">
        <p>
          Duplicate groups (connected components over exact + strong perceptual evidence,
          plus overlaps you confirm) are consolidated into a single split. Groups
          spanning train and test move <strong>out of test</strong> unless majority-test.
          Conflicting-label groups are excluded pending human labeling — pixels cannot
          tell us the correct class. Corrupt files are excluded. The output is a{" "}
          <strong>manifest</strong> (CSV/JSON) with a reason per row;{" "}
          <strong>original files are never modified or deleted</strong>.
        </p>
      </Section>

      <Section id="gap" title="Observed Evaluation Gap">
        <p>
          When the dataset has labeled train and test splits with at least 2 shared
          classes, ≥5 training samples per class and ≥10 test samples, SplitShield trains
          logistic regression on frozen embeddings of the original training split,
          evaluates on the original test split, then re-evaluates{" "}
          <strong>the same fitted model</strong> on the test subset with strong
          cross-split leakage quarantined. It reports both accuracies, macro-F1, sample
          counts, the random seed, and 95% bootstrap confidence intervals (1,000
          resamples when n ≥ 20).
        </p>
        <p>
          <strong>Interpretation guardrails:</strong> the gap is evidence of sensitivity
          to leakage, <em>not proof of causation</em>; removing samples changes the test
          population; small test sets are unstable; the diagnostic baseline is not a
          production model. When conditions are not met the experiment is disabled with
          an explicit reason — metrics are never invented.
        </p>
      </Section>

      <Section id="failure-modes" title="Known failure modes">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>Rotated, flipped or heavily cropped copies can evade both pHash and the classical descriptor.</li>
          <li>The classical descriptor cannot detect conceptual overlap between visually different images (e.g. two different photos of the same object).</li>
          <li>Thresholds trade recall against review noise; there is no universally correct setting.</li>
          <li>Same-scene frames (e.g. video stills) may be flagged as overlap even when a researcher considers them distinct — hence the human-review workflow.</li>
          <li>Extremely small classes make both the imbalance measures and the diagnostic classifier unstable.</li>
        </ul>
      </Section>

      <Section id="privacy" title="Privacy behaviour">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>No facial recognition or identity inference of any kind.</li>
          <li>Analysis is fully local to the server; no third-party service receives your images by default.</li>
          <li>Uploads live under random internal identifiers and are deleted after the configured retention window, or immediately via “Delete my audit”.</li>
          <li>Archives are validated by content signature, extracted with traversal/zip-bomb guards, and never executed.</li>
        </ul>
      </Section>

      <Section id="attribution" title="Attribution & comparison with existing tools">
        <p>
          SplitShield does <strong>not</strong> claim duplicate detection is novel.{" "}
          <strong>FiftyOne</strong> (Voxel51) offers rich dataset exploration with
          embedding-based duplicate views; <strong>CleanVision</strong> (Cleanlab) scans
          image folders for issues including exact/near duplicates;{" "}
          <strong>Cleanlab</strong> focuses on label-error detection. SplitShield&apos;s
          contribution is the <em>leakage-centric workflow on top</em>: split-aware
          severity, side-by-side evidence review, split repair that protects the test
          set, the Observed Evaluation Gap experiment, and a reproducible audit report.
        </p>
        <p>
          Built with FastAPI, Pillow, ImageHash, NumPy, scikit-learn, Next.js, Tailwind
          CSS and Recharts. Full license disclosures ship in{" "}
          <code>THIRD_PARTY_DISCLOSURES.md</code>.
        </p>
      </Section>
    </div>
  );
}
