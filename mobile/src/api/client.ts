import { API_BASE_URL } from "../lib/config";
import type {
  Facets,
  Reservation,
  ReservationCreate,
  Shop,
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
};

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
  if (status === 403) return "This reservation belongs to a different device or session.";
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

export function getFacets(slug: string, signal?: AbortSignal): Promise<Facets> {
  return request<Facets>(`/v1/shops/${encodeURIComponent(slug)}/facets`, { signal });
}

export function createReservation(
  slug: string,
  payload: ReservationCreate,
  idempotencyKey: string,
): Promise<Reservation> {
  return request<Reservation>(`/v1/shops/${encodeURIComponent(slug)}/reservations`, {
    method: "POST",
    body: payload,
    headers: { "Idempotency-Key": idempotencyKey },
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
