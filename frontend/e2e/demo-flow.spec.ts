/**
 * Full user journey against the real stack:
 * open app -> run demo dataset -> watch analysis -> inspect dashboard ->
 * open Evidence Explorer -> review a finding -> repair studio -> report links.
 */
import { expect, test } from "@playwright/test";

test("demo dataset end-to-end journey", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  // --- Landing page -----------------------------------------------------
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "hidden leakage",
  );
  await expect(page.getByRole("link", { name: "Analyze a dataset" })).toBeVisible();

  // --- Start the demo ---------------------------------------------------
  await page.getByRole("link", { name: "Try demonstration dataset" }).click();
  await page.waitForURL(/\/audit\/job_/, { timeout: 30_000 });

  // --- Analysis completes and dashboard renders --------------------------
  await expect(page.getByText("Dataset Integrity Score")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText(/\/ 100/)).toBeVisible();
  await expect(page.getByText("Exact cross-split leaks")).toBeVisible();
  // Demo has planted issues, so the fix-first section must exist.
  await expect(page.getByText("What should I fix first?")).toBeVisible();
  // Charts are SVG elements produced from real data.
  await expect(page.locator(".recharts-surface").first()).toBeVisible();

  // --- Evidence Explorer -------------------------------------------------
  await page.getByRole("tab", { name: "Evidence Explorer" }).click();
  await expect(page.getByText(/finding\(s\)/)).toBeVisible({ timeout: 15_000 });
  const firstCard = page.locator("article").first();
  await expect(firstCard).toBeVisible();
  // Both evidence images load from the API.
  const images = firstCard.locator("img");
  await expect(images).toHaveCount(2);

  // --- Review a finding ---------------------------------------------------
  const confirmButton = firstCard.getByRole("button", { name: "Confirm leakage" });
  await confirmButton.click();
  await expect(
    page.locator("article").first().getByRole("button", { name: /✓ Confirm leakage/ }),
  ).toBeVisible({ timeout: 10_000 });

  // --- Repair Studio ------------------------------------------------------
  await page.getByRole("tab", { name: "Repair Studio" }).click();
  await expect(page.getByText("Nothing is modified in place.")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText(/Split counts — before → after/)).toBeVisible();
  const csvLink = page.getByRole("link", { name: "Export CSV manifest" });
  await expect(csvLink).toHaveAttribute("href", /repair\.csv/);

  // Manifest is actually downloadable and well-formed.
  const href = await csvLink.getAttribute("href");
  const resp = await page.request.get(href!);
  expect(resp.ok()).toBeTruthy();
  const csv = await resp.text();
  expect(csv.split("\n")[0]).toContain("proposed_split");

  // --- Report -------------------------------------------------------------
  await page.getByRole("tab", { name: "Report" }).click();
  await expect(page.getByRole("link", { name: "Open printable report" })).toBeVisible();
  const reportHref = await page
    .getByRole("link", { name: "Download JSON report" })
    .getAttribute("href");
  const reportResp = await page.request.get(reportHref!);
  expect(reportResp.ok()).toBeTruthy();
  const report = (await reportResp.json()) as {
    findings: unknown[];
    audit: { dataset_fingerprint_sha256: string };
  };
  expect(report.findings.length).toBeGreaterThan(5);
  expect(report.audit.dataset_fingerprint_sha256).toMatch(/^[0-9a-f]{64}$/);

  // --- No console-breaking errors ------------------------------------------
  const fatal = consoleErrors.filter(
    (e) => !e.includes("favicon") && !e.includes("404"),
  );
  expect(fatal).toEqual([]);
});
