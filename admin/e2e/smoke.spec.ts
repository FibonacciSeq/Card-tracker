import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { E2E } from "./constants";

function nav(page: Page, name: string) {
  return page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });
}

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByTestId("login-slug").fill(E2E.slug);
  await page.getByTestId("login-email").fill(E2E.email);
  await page.getByTestId("login-password").fill(E2E.password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

type PublicStock = { items: Array<{ stock_id: string; available: number; card: { name: string } }> };

async function publicStock(request: APIRequestContext): Promise<PublicStock> {
  const response = await request.get(`${E2E.apiUrl}/v1/shops/${E2E.slug}/stock?limit=50`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as PublicStock;
}

test("rejects a wrong password and then signs in", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-slug").fill(E2E.slug);
  await page.getByTestId("login-email").fill(E2E.email);
  await page.getByTestId("login-password").fill("wrong-password");
  await page.getByTestId("login-submit").click();

  await expect(page.getByTestId("login-error")).toContainText("Invalid credentials");

  await page.getByTestId("login-password").fill(E2E.password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Waiting for you")).toBeVisible();
});

test("adjusts stock and records a sale", async ({ page, request }) => {
  const before = await publicStock(request);
  const target = before.items.find((item) => item.card.name === "Lightning Bolt");
  expect(target).toBeTruthy();
  const availableBefore = target!.available;

  await signIn(page);
  await nav(page, "Stock").click();
  await page.getByTestId("stock-search").fill("Lightning Bolt");

  const table = page.getByTestId("stock-table");
  // Wait for the debounced search so the row we act on is the card we checked.
  await expect(table.getByRole("row")).toHaveCount(2); // header + one card
  const row = table.getByRole("row", { name: /Lightning Bolt/ });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Manage" }).click();
  const editor = page.locator(".row-editor");
  await expect(editor).toBeVisible();

  await editor.getByRole("button", { name: "Add", exact: true }).click();
  await expect(editor.getByText("Added 1 to stock.")).toBeVisible();

  await page.getByRole("button", { name: "Refresh" }).click();

  const after = await publicStock(request);
  const updated = after.items.find((item) => item.stock_id === target!.stock_id);
  expect(updated?.available).toBe(availableBefore + 1);
});

test("confirms and completes a reservation, releasing the hold", async ({ page, request }) => {
  const stock = await publicStock(request);
  const item = stock.items.find((entry) => entry.available > 0);
  expect(item).toBeTruthy();

  const created = await request.post(`${E2E.apiUrl}/v1/shops/${E2E.slug}/reservations`, {
    data: {
      customer: { name: "E2E Customer", email: "e2e@example.com", phone: "+381600000000" },
      note: "Pickup on Saturday",
      items: [{ stock_id: item!.stock_id, quantity: 1 }],
    },
  });
  expect(created.ok()).toBeTruthy();
  const reservation = (await created.json()) as { public_ref: string };

  await signIn(page);
  await nav(page, "Reservations").click();
  await page.getByRole("tab", { name: "Requested" }).click();

  const row = page.getByRole("row", { name: new RegExp(reservation.public_ref) });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Open" }).click();

  const detail = page.getByTestId("reservation-detail");
  await expect(detail).toBeVisible();
  await expect(detail.getByText("e2e@example.com")).toBeVisible();
  await expect(detail.getByText("Pickup on Saturday")).toBeVisible();

  await detail.getByRole("button", { name: "Confirm request" }).click();
  await expect(detail.getByText("Confirmed")).toBeVisible();

  await detail.getByRole("button", { name: "Mark ready for pickup" }).click();
  await expect(detail.getByText("Ready", { exact: true })).toBeVisible();

  await detail.getByRole("button", { name: "Complete reservation" }).click();
  await expect(detail.getByText("This reservation is closed.")).toBeVisible();

  const after = await publicStock(request);
  const updated = after.items.find((entry) => entry.stock_id === item!.stock_id);
  expect(updated?.available).toBe(item!.available - 1);
});

test("saves shop settings", async ({ page }) => {
  await signIn(page);
  await nav(page, "Settings").click();

  const name = page.getByLabel("Display name");
  await expect(name).toBeVisible();
  await name.fill("Bolt Shop Deluxe");
  await page.getByLabel("Hold duration (hours)").fill("48");
  await page.getByRole("button", { name: "Save settings" }).click();

  await expect(page.getByText("Settings saved.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("Bolt Shop Deluxe");
  await expect(page.getByLabel("Hold duration (hours)")).toHaveValue("48");
});

test("exports the stock template and imports a checked change", async ({ page }) => {
  await signIn(page);
  await nav(page, "Stock").click();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export CSV" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/stock.*\.csv/);

  const csv =
    "card_name,set_code,collector_number,finish,condition,language,quantity,price,currency,is_online\n" +
    "Lightning Bolt,LEB,161,nonfoil,NM,en,7,1250.00,RSD,true\n";

  await page.getByTestId("import-toggle").click();
  await page.getByTestId("import-file").setInputFiles({
    name: "stock.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv, "utf-8"),
  });
  await page.getByTestId("import-check").click();

  const report = page.getByTestId("import-report");
  await expect(report).toContainText("Check only");
  await expect(report).toContainText("1 updated");
  await expect(page.getByTestId("import-apply")).toBeEnabled();

  await page.getByTestId("import-apply").click();
  await expect(report).toContainText("Import applied.");

  await page.getByTestId("stock-search").fill("Lightning Bolt");
  const table = page.getByTestId("stock-table");
  const row = table.getByRole("row", { name: /Lightning Bolt/ });
  await expect(row).toBeVisible();
  await expect(row.locator("dd").first()).toHaveText("7");
});
