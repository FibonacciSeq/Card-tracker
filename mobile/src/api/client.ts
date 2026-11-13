import { API_BASE_URL } from "../lib/config";
import type {
  AccountCardRequest,
  AccountNotificationList,
  AccountReservation,
  AccountRestockAlert,
  CardRequest,
  CardRequestCreate,
  CustomerAccount,
  CustomerProfileUpdate,
  CustomerToken,
  Facets,
  OtpRequestResult,
  PushToken,
  PushTokenCreate,
  PushTokenList,
  Reservation,
  ReservationCreate,
  RestockAlert,
  RestockAlertCreate,
  Shop,
  StockItem,
  StockList,
  StockQuery,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(status: number, message: string, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  auth?: boolean;
};

let unauthorizedHandler: (() => void) | null = null;
let refreshHandler: (() => Promise<boolean>) | null = null;

/** Lets AuthProvider handle expired customer sessions without forcing a full sign-out. */
export function setAccountUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function setAccountRefreshHandler(handler: (() => Promise<boolean>) | null): void {
  refreshHandler = handler;
}

function bearer(token: string | null | undefined): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function detailFrom(payload: unknown, status: number): string {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string; loc?: (string | number)[] };
      if (first?.msg) {
        return first.loc ? `${first.loc.slice(1).join(".")}: ${first.msg}` : first.msg;
      }
    }
  }
  if (status === 403) return "This item belongs to a different device or session.";
  if (status === 404) return "That item is no longer available.";
  if (status === 429) return "Too many requests. Please wait a moment and try again.";
  if (status >= 500) return "The shop is having trouble right now. Please try again.";
  return `Request failed (${status}).`;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const entries = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return entries.length ? `?${entries.join("&")}` : "";
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const text = await response.text();
  const payload: unknown = text ? safeJson(text) : null;

  if (!response.ok) {
    if (options.auth && response.status === 401) {
      if (refreshHandler) {
        const refreshed = await refreshHandler();
        if (refreshed) {
          return request<T>(path, options);
        }
      }
      unauthorizedHandler?.();
    }
    throw new ApiError(response.status, detailFrom(payload, response.status), payload);
  }
  return payload as T;
}

export function getShops(query = "", signal?: AbortSignal): Promise<Shop[]> {
  return request<Shop[]>(`/v1/shops${queryString({ query, limit: 100 })}`, { signal });
}

export function getShop(slug: string, signal?: AbortSignal): Promise<Shop> {
  return request<Shop>(`/v1/shops/${encodeURIComponent(slug)}`, { signal });
}

export function getStock(
  slug: string,
  query: StockQuery = {},
  signal?: AbortSignal,
): Promise<StockList> {
  return request<StockList>(
    `/v1/shops/${encodeURIComponent(slug)}/stock${queryString({
      query: query.query,
      sort: query.sort ?? "relevance",
      available_only: query.availableOnly ? "true" : undefined,
      cursor: query.cursor,
      limit: query.limit ?? 40,
    })}`,
    { signal },
  );
}

export function getStockItem(
  slug: string,
  stockId: string,
  signal?: AbortSignal,
): Promise<StockItem> {
  return request<StockItem>(
    `/v1/shops/${encodeURIComponent(slug)}/stock/${encodeURIComponent(stockId)}`,
    { signal },
  );
}

export function getFacets(slug: string, signal?: AbortSignal): Promise<Facets> {
  return request<Facets>(`/v1/shops/${encodeURIComponent(slug)}/facets`, { signal });
}

export function createReservation(
  slug: string,
  payload: ReservationCreate,
  idempotencyKey: string,
  token?: string | null,
): Promise<Reservation> {
  return request<Reservation>(`/v1/shops/${encodeURIComponent(slug)}/reservations`, {
    method: "POST",
    body: payload,
    headers: { "Idempotency-Key": idempotencyKey, ...bearer(token) },
    auth: Boolean(token),
  });
}

export function getReservation(
  id: string,
  slug: string,
  token: string,
  signal?: AbortSignal,
): Promise<Reservation> {
  return request<Reservation>(`/v1/reservations/${encodeURIComponent(id)}`, {
    signal,
    headers: {
      "X-Shop-Slug": slug,
      "X-Reservation-Token": token,
    },
  });
}

export function cancelReservation(
  id: string,
  slug: string,
  token: string,
): Promise<Reservation> {
  return request<Reservation>(`/v1/reservations/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    headers: {
      "X-Shop-Slug": slug,
      "X-Reservation-Token": token,
    },
  });
}

export function createRestockAlert(
  slug: string,
  payload: RestockAlertCreate,
  token?: string | null,
): Promise<RestockAlert> {
  return request<RestockAlert>(`/v1/shops/${encodeURIComponent(slug)}/restock-alerts`, {
    method: "POST",
    body: payload,
    headers: bearer(token),
    auth: Boolean(token),
  });
}

export function unsubscribeRestockAlert(
  slug: string,
  alertId: string,
  token: string,
): Promise<void> {
  return request<void>(
    `/v1/shops/${encodeURIComponent(slug)}/restock-alerts/${encodeURIComponent(alertId)}/unsubscribe?token=${encodeURIComponent(token)}`,
    { method: "POST" },
  );
}

export function createCardRequest(
  slug: string,
  payload: CardRequestCreate,
  token?: string | null,
): Promise<CardRequest> {
  return request<CardRequest>(`/v1/shops/${encodeURIComponent(slug)}/card-requests`, {
    method: "POST",
    body: payload,
    headers: bearer(token),
    auth: Boolean(token),
  });
}

export function getCardRequest(
  id: string,
  slug: string,
  token: string,
  signal?: AbortSignal,
): Promise<CardRequest> {
  return request<CardRequest>(`/v1/card-requests/${encodeURIComponent(id)}`, {
    signal,
    headers: {
      "X-Shop-Slug": slug,
      "X-Card-Request-Token": token,
    },
  });
}

export function acceptCardRequest(
  id: string,
  slug: string,
  token: string,
): Promise<CardRequest> {
  return request<CardRequest>(`/v1/card-requests/${encodeURIComponent(id)}/accept`, {
    method: "POST",
    headers: {
      "X-Shop-Slug": slug,
      "X-Card-Request-Token": token,
    },
  });
}

export function cancelCardRequest(
  id: string,
  slug: string,
  token: string,
): Promise<CardRequest> {
  return request<CardRequest>(`/v1/card-requests/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    headers: {
      "X-Shop-Slug": slug,
      "X-Card-Request-Token": token,
    },
  });
}

export function loginCustomer(email: string, password: string): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function requestSignupCode(email: string): Promise<OtpRequestResult> {
  return request<OtpRequestResult>("/v1/auth/signup/request", {
    method: "POST",
    body: { email },
  });
}

export function verifySignup(
  email: string,
  code: string,
  password: string,
): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/auth/signup/verify", {
    method: "POST",
    body: { email, code, password },
  });
}

export function requestPasswordReset(email: string): Promise<OtpRequestResult> {
  return request<OtpRequestResult>("/v1/auth/password/reset/request", {
    method: "POST",
    body: { email },
  });
}

export function verifyPasswordReset(
  email: string,
  code: string,
  password: string,
): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/auth/password/reset/verify", {
    method: "POST",
    body: { email, code, password },
  });
}

export function changeCustomerPassword(
  token: string,
  currentPassword: string | null,
  newPassword: string,
): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/me/password", {
    method: "POST",
    body: {
      current_password: currentPassword,
      new_password: newPassword,
    },
    headers: bearer(token),
    auth: true,
  });
}

export function refreshCustomerToken(refreshToken: string): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export function logoutCustomerSession(
  token: string,
  refreshToken?: string | null,
): Promise<void> {
  return request<void>("/v1/auth/logout", {
    method: "POST",
    body: refreshToken ? { refresh_token: refreshToken } : undefined,
    headers: bearer(token),
    auth: true,
  });
}

export function revokeAllCustomerSessions(token: string): Promise<void> {
  return request<void>("/v1/me/sessions/revoke-all", {
    method: "POST",
    headers: bearer(token),
    auth: true,
  });
}

export function getMe(token: string): Promise<CustomerAccount> {
  return request<CustomerAccount>("/v1/me", {
    headers: bearer(token),
    auth: true,
  });
}

export function updateMe(
  token: string,
  payload: CustomerProfileUpdate,
): Promise<CustomerAccount> {
  return request<CustomerAccount>("/v1/me", {
    method: "PATCH",
    body: payload,
    headers: bearer(token),
    auth: true,
  });
}

export function deleteMe(token: string): Promise<void> {
  return request<void>("/v1/me", {
    method: "DELETE",
    headers: bearer(token),
    auth: true,
  });
}

export function requestEmailChange(token: string, email: string): Promise<OtpRequestResult> {
  return request<OtpRequestResult>("/v1/me/email", {
    method: "POST",
    body: { email },
    headers: bearer(token),
    auth: true,
  });
}

export function verifyEmailChange(
  token: string,
  email: string,
  code: string,
): Promise<CustomerToken> {
  return request<CustomerToken>("/v1/me/email/verify", {
    method: "POST",
    body: { email, code },
    headers: bearer(token),
    auth: true,
  });
}

export function registerPushToken(
  token: string,
  payload: PushTokenCreate,
): Promise<PushToken> {
  return request<PushToken>("/v1/me/push-tokens", {
    method: "POST",
    body: payload,
    headers: bearer(token),
    auth: true,
  });
}

export function unregisterPushToken(token: string, deviceToken: string): Promise<void> {
  return request<void>(`/v1/me/push-tokens/${encodeURIComponent(deviceToken)}`, {
    method: "DELETE",
    headers: bearer(token),
    auth: true,
  });
}

export function getMyPushTokens(token: string): Promise<PushTokenList> {
  return request<PushTokenList>("/v1/me/push-tokens", {
    headers: bearer(token),
    auth: true,
  });
}

export function getMyNotifications(
  token: string,
  cursor?: string | null,
): Promise<AccountNotificationList> {
  return request<AccountNotificationList>(
    `/v1/me/notifications${queryString({ cursor, limit: 50 })}`,
    {
      headers: bearer(token),
      auth: true,
    },
  );
}

export function getMyReservations(token: string): Promise<{ items: AccountReservation[] }> {
  return request<{ items: AccountReservation[] }>("/v1/me/reservations", {
    headers: bearer(token),
    auth: true,
  });
}

export function getMyReservation(id: string, token: string): Promise<Reservation> {
  return request<Reservation>(`/v1/me/reservations/${encodeURIComponent(id)}`, {
    headers: bearer(token),
    auth: true,
  });
}

export function cancelMyReservation(id: string, token: string): Promise<Reservation> {
  return request<Reservation>(
    `/v1/me/reservations/${encodeURIComponent(id)}/cancel`,
    {
      method: "POST",
      headers: bearer(token),
      auth: true,
    },
  );
}

export function getMyCardRequests(token: string): Promise<{ items: AccountCardRequest[] }> {
  return request<{ items: AccountCardRequest[] }>("/v1/me/card-requests", {
    headers: bearer(token),
    auth: true,
  });
}

export function getMyCardRequest(id: string, token: string): Promise<AccountCardRequest> {
  return request<AccountCardRequest>(`/v1/me/card-requests/${encodeURIComponent(id)}`, {
    headers: bearer(token),
    auth: true,
  });
}

export function acceptMyCardRequest(id: string, token: string): Promise<AccountCardRequest> {
  return request<AccountCardRequest>(
    `/v1/me/card-requests/${encodeURIComponent(id)}/accept`,
    {
      method: "POST",
      headers: bearer(token),
      auth: true,
    },
  );
}

export function cancelMyCardRequest(id: string, token: string): Promise<AccountCardRequest> {
  return request<AccountCardRequest>(
    `/v1/me/card-requests/${encodeURIComponent(id)}/cancel`,
    {
      method: "POST",
      headers: bearer(token),
      auth: true,
    },
  );
}

export function getMyRestockAlerts(token: string): Promise<{ items: AccountRestockAlert[] }> {
  return request<{ items: AccountRestockAlert[] }>("/v1/me/restock-alerts", {
    headers: bearer(token),
    auth: true,
  });
}

export function deleteMyRestockAlert(id: string, token: string): Promise<void> {
  return request<void>(`/v1/me/restock-alerts/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: bearer(token),
    auth: true,
  });
}
