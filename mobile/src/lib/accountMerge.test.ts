import { describe, expect, it } from "vitest";

import type {
  AccountCardRequest,
  AccountReservation,
  AccountRestockAlert,
  SavedReservation,
} from "../api/types";
import type { SavedCardRequest } from "../state/specialOrders";
import type { SavedRestockAlert } from "../state/restockAlerts";
import {
  accountAlertToItem,
  accountRequestToSaved,
  guestAlertToItem,
  mergeCardRequests,
  mergeReservations,
  mergeRestockAlerts,
  readShop,
} from "./accountMerge";

function money(amount: number) {
  return { amount_minor: amount, currency: "RSD" };
}

function reservation(id: string, created_at: string): AccountReservation {
  return {
    id,
    public_ref: id,
    status: "REQUESTED",
    expires_at: created_at,
    created_at,
    total: money(100),
    lines: [],
    shop: { slug: "bolt", name: "Bolt" },
  } as unknown as AccountReservation;
}

function cardRequest(id: string, created_at: string): AccountCardRequest {
  return {
    id,
    public_ref: id,
    status: "QUOTED",
    created_at,
    shop: { slug: "bolt", name: "Bolt" },
    access_token: "secret",
  } as unknown as AccountCardRequest;
}

function guestRequest(id: string, created_at: string): SavedCardRequest {
  return {
    id,
    public_ref: id,
    status: "REQUESTED",
    created_at,
    shopSlug: "guest",
    shopName: "Guest",
  } as unknown as SavedCardRequest;
}

function accountAlert(id: string, created_at: string, stock_id: string | null = "s1"): AccountRestockAlert {
  return {
    id,
    card_id: "c1",
    stock_id,
    card_name: "Bolt",
    set_code: "LEB",
    collector_number: "161",
    finish: "nonfoil",
    condition: "NM",
    language: "en",
    email: "a@example.com",
    shop: { slug: "bolt", name: "Bolt" },
    created_at,
    notified_at: null,
  } as unknown as AccountRestockAlert;
}

function guestAlert(id: string, created_at: string): SavedRestockAlert {
  return {
    id,
    card_id: "c1",
    stockId: "s2",
    card_name: "Guest Bolt",
    set_code: "LEB",
    collector_number: "161",
    finish: "foil",
    condition: "LP",
    language: "en",
    email: "g@example.com",
    created_at,
    notified_at: null,
    shopSlug: "guest",
    shopName: "Guest",
  } as unknown as SavedRestockAlert;
}

describe("account merge helpers", () => {
  it("reads shop metadata defensively", () => {
    expect(readShop(null)).toEqual({ slug: "", name: "Shop" });
    expect(readShop("bad")).toEqual({ slug: "", name: "Shop" });
    expect(readShop({})).toEqual({ slug: "", name: "Shop" });
    expect(readShop({ slug: 1, name: 2 })).toEqual({ slug: "", name: "Shop" });
    expect(readShop({ slug: "bolt", name: "Bolt" })).toEqual({ slug: "bolt", name: "Bolt" });
  });

  it("merges reservations newest first with account rows winning", () => {
    const merged = mergeReservations(
      [reservation("same", "2026-10-29T10:00:00Z"), reservation("new", "2026-10-30T10:00:00Z")],
      [
        reservation("same", "2026-01-01T00:00:00Z"),
        reservation("old", "2026-01-02T00:00:00Z"),
      ] as unknown as SavedReservation[],
    );
    expect(merged.map((row) => row.id)).toEqual(["new", "same", "old"]);
    expect(merged[1].created_at).toBe("2026-10-29T10:00:00Z");
  });

  it("converts and merges card requests", () => {
    const saved = accountRequestToSaved(cardRequest("a", "2026-10-29T10:00:00Z"));
    expect(saved.shopSlug).toBe("bolt");
    expect("access_token" in saved).toBe(false);

    const merged = mergeCardRequests(
      [cardRequest("same", "2026-10-29T10:00:00Z"), cardRequest("new", "2026-10-30T10:00:00Z")],
      [guestRequest("same", "2026-01-01T00:00:00Z"), guestRequest("old", "2026-01-02T00:00:00Z")],
    );
    expect(merged.map((row) => row.id)).toEqual(["new", "same", "old"]);
  });

  it("converts account and guest alerts", () => {
    expect(accountAlertToItem(accountAlert("a", "2026-10-29T10:00:00Z"))).toMatchObject({
      source: "account",
      shopSlug: "bolt",
      stockId: "s1",
    });
    expect(accountAlertToItem(accountAlert("b", "2026-10-29T10:00:00Z", null)).stockId).toBeNull();
    expect(guestAlertToItem(guestAlert("g", "2026-10-29T10:00:00Z"))).toMatchObject({
      source: "guest",
      shopSlug: "guest",
      stockId: "s2",
    });
  });

  it("merges alerts newest first with account rows winning", () => {
    const merged = mergeRestockAlerts(
      [accountAlert("same", "2026-10-29T10:00:00Z"), accountAlert("new", "2026-10-30T10:00:00Z")],
      [guestAlert("same", "2026-01-01T00:00:00Z"), guestAlert("old", "2026-01-02T00:00:00Z")],
    );
    expect(merged.map((row) => row.id)).toEqual(["new", "same", "old"]);
    expect(merged[1].source).toBe("account");
  });
});
