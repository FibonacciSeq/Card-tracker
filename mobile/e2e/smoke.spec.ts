import { expect, test } from "@playwright/test";

test("customers must sign in and the locale toggle is interactive", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Your card list, secured.")).toBeVisible();
  await expect(page.getByText("Shops on Card Tracker")).toHaveCount(0);
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();

  await page.getByRole("button", { name: /Srpski/i }).click();
  await expect(page.getByText("Vaša lista karata, zaštićena.")).toBeVisible();

  await page.getByRole("button", { name: /English/i }).click();
  await expect(page.getByText("Your card list, secured.")).toBeVisible();
});

test("a protected route redirects to the sign-in screen", async ({ page }) => {
  await page.goto("/account");

  await expect(page.getByText("Your card list, secured.")).toBeVisible();
});
