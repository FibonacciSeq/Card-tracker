import type {
  AccountCardRequest,
  AccountReservation,
  AccountRestockAlert,
  Money,
  SavedReservation,
} from "../api/types";
import type { SavedCardRequest } from "../state/specialOrders";
import type { SavedRestockAlert } from "../state/restockAlerts";

export type ReservationListItem = {
  id: string;
  public_ref: string;
  status: string;
  expires_at: string;
  created_at: string;
  total: Money;
  shop: unknown;
};

export type AlertListItem = {
  id: string;
  shopSlug: string;
  shopName: string;
  cardName: string;
  stockId: string | null;
  finish: string;
  condition: string;
  language: string;
  email: string;
  createdAt: string;
  source: "account" | "guest";
};

type ShopMeta = { slug: string; name: string };

export function readShop(shop: unknown): ShopMeta {
  if (typeof shop !== "object" || shop === null) return { slug: "", name: "Shop" };
  const value = shop as { slug?: unknown; name?: unknown };
  return {
    slug: typeof value.slug === "string" ? value.slug : "",
    name: typeof value.name === "string" ? value.name : "Shop",
  };
}

function newestFirst<T>(rows: T[], getDate: (row: T) => string): T[] {
  return rows.sort(
    (left, right) => new Date(getDate(right)).getTime() - new Date(getDate(left)).getTime(),
  );
}

export function mergeReservations(
  accountRows: AccountReservation[],
  guestRows: SavedReservation[],
): ReservationListItem[] {
  const byId = new Map<string, ReservationListItem>();
  for (const row of guestRows) byId.set(row.id, row);
  for (const row of accountRows) byId.set(row.id, row);
  return newestFirst([...byId.values()], (row) => row.created_at);
}

export function accountRequestToSaved(row: AccountCardRequest): SavedCardRequest {
  const shop = readShop(row.shop);
  const { shop: _shop, access_token: _accessToken, ...rest } = row;
  return { ...rest, shopSlug: shop.slug, shopName: shop.name };
}

export function mergeCardRequests(
  accountRows: AccountCardRequest[],
  guestRows: SavedCardRequest[],
): SavedCardRequest[] {
  const byId = new Map<string, SavedCardRequest>();
  for (const row of guestRows) byId.set(row.id, row);
  for (const row of accountRows) byId.set(row.id, accountRequestToSaved(row));
  return newestFirst([...byId.values()], (row) => row.created_at);
}

export function accountAlertToItem(row: AccountRestockAlert): AlertListItem {
  const shop = readShop(row.shop);
  return {
    id: row.id,
    shopSlug: shop.slug,
    shopName: shop.name,
    cardName: row.card_name,
    stockId: row.stock_id ?? null,
    finish: row.finish,
    condition: row.condition,
    language: row.language,
    email: row.email,
    createdAt: row.created_at,
    source: "account",
  };
}

export function guestAlertToItem(row: SavedRestockAlert): AlertListItem {
  return {
    id: row.id,
    shopSlug: row.shopSlug,
    shopName: row.shopName,
    cardName: row.cardName,
    stockId: row.stockId,
    finish: row.finish,
    condition: row.condition,
    language: row.language,
    email: row.email,
    createdAt: row.created_at,
    source: "guest",
  };
}

export function mergeRestockAlerts(
  accountRows: AccountRestockAlert[],
  guestRows: SavedRestockAlert[],
): AlertListItem[] {
  const byId = new Map<string, AlertListItem>();
  for (const row of guestRows) byId.set(row.id, guestAlertToItem(row));
  for (const row of accountRows) byId.set(row.id, accountAlertToItem(row));
  return newestFirst([...byId.values()], (row) => row.createdAt);
}
