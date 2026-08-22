# Demo video script — 3:00 max

**Setup before recording:** stack running (`docker compose up` or local),
browser at `http://localhost:3000`, window at 1280×800, one audit pre-warmed
so the demo job completes fast (it takes ~5 s cold anyway).

---

**[0:00–0:20] Hook — the problem** *(landing page on screen)*

> "If your test set secretly contains copies of your training images, your
> accuracy is a lie. This is dataset leakage — it's common, it's invisible,
> and it makes results unreproducible. SplitShield finds it, helps you fix
> it, and measures what it was doing to your numbers."

**[0:20–0:35] Start the audit** *(click "Try demonstration dataset")*

> "I'll use the built-in demo: a synthetic dataset with planted problems —
> exact train/test duplicates, recompressed and cropped copies, one image
> filed under two different labels, a corrupt file. Watch the pipeline run:
> validation, hashing, perceptual analysis, similarity search, scoring —
> this is all computed live, nothing is canned."

**[0:35–1:05] Dashboard** *(analysis completes)*

> "Integrity Score 29 out of 100 — severe risk, and here's exactly why: the
> score is a documented weighted formula, no AI magic." *(open breakdown)*
> "Three exact cross-split leaks, seven near-duplicates, one conflicting
> label, one corrupt image. And this chart is the headline: our diagnostic
> classifier scores about 82% on the original test set, but about 79% once
> the nine leaked test samples are quarantined — that difference is the
> Observed Evaluation Gap, shown with bootstrap confidence intervals. Note
> the careful name: it's evidence of sensitivity, not a causal claim."

**[1:05–1:45] Evidence Explorer** *(click prioritized link)*

> "Every finding is a side-by-side pair: splits, labels, method, similarity.
> This one — byte-identical SHA-256 match, train versus test. Confirmed."
> *(click Confirm leakage)*
> "This near-duplicate is the same photo recompressed — pHash distance 2.
> And here's the same image labeled *circles* in one folder and *stripes* in
> another — the model literally can't learn the right answer. My review
> decisions persist and feed the repair and the report, but they never
> overwrite the algorithmic evidence."

**[1:45–2:20] Repair Studio** *(switch tab)*

> "SplitShield proposes a repair, and it never touches my files — it's a
> manifest. Duplicate groups get consolidated into one split, preferring to
> keep the test set clean; the conflicting-label group is excluded pending a
> human decision; every row has a reason. Before-and-after split counts,
> warnings when a class loses too much test data, export as CSV or JSON."
> *(click Export CSV manifest)*

**[2:20–2:45] Report** *(switch tab, open printable report)*

> "Finally, the audit report: dataset fingerprint, full score formula,
> findings with review status, the evaluation experiment with its seed,
> sample counts and bootstrap confidence intervals, package versions,
> limitations. Print to PDF, attach it to your paper or your PR."

**[2:45–3:00] Close** *(back to landing)*

> "Duplicate detection isn't new — FiftyOne and CleanVision do it well.
> SplitShield is the leakage workflow on top: detect, explain, repair,
> quantify, and export a reproducible audit. Everything runs locally, uploads
> auto-delete, and one click removes everything. SplitShield — trust your
> test set."

---

**Timing checkpoints:** 0:35 dashboard visible · 1:45 review recorded ·
2:20 manifest downloaded · 3:00 hard stop.
