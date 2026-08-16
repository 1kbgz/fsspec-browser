import { expect, test } from "@playwright/test";

test.describe("preview paging", () => {
  test("loads the next table page from its continuation", async ({ page }) => {
    const previewOffsets = [];
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
      const offset = Number(url.searchParams.get("offset") || 0);
      previewOffsets.push(offset);
      const firstPage = offset === 0;
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
          continuation: firstPage ? { kind: "offset", value: 2 } : null,
          display_path: "memory:///people.csv",
          kind: "table",
          limit: 2,
          metadata: { rows: String(rows.length) },
          offset,
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
    expect(previewOffsets).toEqual([0, 2]);
  });
});
