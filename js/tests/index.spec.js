import { expect, test } from "@playwright/test";

// Serves one previewable file whose first page continues with `continuation`, then
// opens it, scrolls to load the second page, and returns the preview request queries.
const pageThroughPreview = async (page, continuation) => {
  const previewQueries = [];
  await page.route("**/api/config", async (route) => {
    await route.fulfill({
      json: {
        active: true,
        display_root: "memory://",
        root_path: "/",
        root_url: "memory://",
      },
    });
  });
  await page.route("**/api/list?**", async (route) => {
    await route.fulfill({
      json: {
        display_path: "memory://",
        entries: [
          {
            display_path: "memory:///people.csv",
            metadata: {},
            name: "people.csv",
            path: "/people.csv",
            previewable: true,
            size: 42,
            type: "file",
          },
        ],
        has_more: false,
        next_offset: null,
        path: "/",
      },
    });
  });
  await page.route("**/api/preview?**", async (route) => {
    const url = new URL(route.request().url());
    url.searchParams.delete("path");
    previewQueries.push(url.searchParams.toString());
    const firstPage = previewQueries.length === 1;
    const rows = firstPage
      ? [
          { name: "ada", score: 2 },
          { name: "grace", score: 3 },
        ]
      : [{ name: "lin", score: 4 }];
    await route.fulfill({
      json: {
        columns: ["name", "score"],
        content: JSON.stringify(rows),
        continuation: firstPage ? continuation : null,
        display_path: "memory:///people.csv",
        kind: "table",
        limit: 2,
        metadata: { rows: String(rows.length) },
        offset: 0,
        path: "/people.csv",
        rows,
        size: 42,
        truncated: firstPage,
      },
    });
  });

  await page.goto("/dist/");
  const row = page.locator('[data-item-path="people.csv"]');
  await expect(row).toBeVisible();
  await row.dblclick();
  await expect(page.locator("#preview-body tbody tr")).toHaveCount(2);

  await page.locator("#preview-body").dispatchEvent("scroll");

  await expect(page.locator("#preview-body tbody tr")).toHaveCount(3);
  await expect(page.locator("#preview-body tbody tr").last()).toContainText(
    "lin",
  );
  return previewQueries;
};

test.describe("preview paging", () => {
  test("loads the next table page from its continuation", async ({ page }) => {
    const queries = await pageThroughPreview(page, {
      kind: "offset",
      value: 2,
    });
    expect(queries).toEqual(["", "offset=2"]);
  });

  test("passes token continuations back unchanged", async ({ page }) => {
    const queries = await pageThroughPreview(page, {
      kind: "token",
      value: "17",
    });
    expect(queries).toEqual(["", "token=17"]);
  });
});
