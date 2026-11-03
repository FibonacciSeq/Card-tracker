import { expect, test } from "@playwright/test";

test("home page renders and locale toggle is interactive", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Find the card you need.")).toBeVisible();
  await expect(page.getByText("Shops on Card Tracker")).toBeVisible();

  await page.getByRole("button", { name: /Sign in to sync your list/i }).click();
  await expect(page.getByText("OPTIONAL ACCOUNT")).toBeVisible();

  await page.getByRole("button", { name: /Srpski/i }).click();
  await expect(page.getByText("OPCIONI NALOG")).toBeVisible();

  await page.getByRole("button", { name: /English/i }).click();
  await expect(page.getByText("OPTIONAL ACCOUNT")).toBeVisible();
});
