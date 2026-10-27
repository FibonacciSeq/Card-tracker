import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "./client";
import type {
  CompleteIn,
  Dashboard,
  StaffReservation,
  ReservationSummary,
  SettingsUpdate,
  StaffShop,
  StaffStock,
  StaffStockList,
  StatusUpdate,
  StockAdjust,
  StockSell,
  StockUpdate,
} from "./types";

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  stock: (query: string, onlyOnline: boolean) => ["stock", query, onlyOnline] as const,
  reservations: (status: string) => ["reservations", status] as const,
  reservation: (id: string) => ["reservation", id] as const,
  settings: ["settings"] as const,
};

export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: () => request<Dashboard>("/v1/staff/dashboard"),
  });
}

export function useStock(query: string, onlyOnline: boolean) {
  return useQuery({
    queryKey: queryKeys.stock(query, onlyOnline),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ limit: "200" });
      if (query.trim()) params.set("query", query.trim());
      if (onlyOnline) params.set("only_online", "true");
      return request<StaffStockList>(`/v1/staff/stock?${params.toString()}`, { signal });
    },
  });
}

export function useUpdateStock() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: StockUpdate }) =>
      request<StaffStock>(`/v1/staff/stock/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => refreshStock(client),
  });
}

export function useAdjustStock() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, delta, reason }: { id: string; delta: number; reason?: string }) =>
      request<StaffStock>(`/v1/staff/stock/${id}/adjust`, {
        method: "POST",
        body: { delta, reason: reason ?? "manual adjustment" } satisfies StockAdjust,
      }),
    onSuccess: () => refreshStock(client),
  });
}

export function useSellStock() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, quantity, reason }: { id: string; quantity: number; reason?: string }) =>
      request<StaffStock>(`/v1/staff/stock/${id}/sell`, {
        method: "POST",
        body: { quantity, reason: reason ?? "in-store sale" } satisfies StockSell,
      }),
    onSuccess: () => refreshStock(client),
  });
}

export function useReservations(status: string) {
  return useQuery({
    queryKey: queryKeys.reservations(status),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ limit: "200" });
      if (status !== "ALL") params.set("status", status);
      return request<ReservationSummary[]>(`/v1/staff/reservations?${params.toString()}`, { signal });
    },
  });
}

export function useReservation(id: string | null) {
  return useQuery({
    queryKey: queryKeys.reservation(id ?? "none"),
    enabled: id !== null,
    queryFn: () => request<StaffReservation>(`/v1/staff/reservations/${id}`),
  });
}

export function useUpdateReservationStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: StatusUpdate["status"]; reason?: string }) =>
      request<StaffReservation>(`/v1/staff/reservations/${id}/status`, {
        method: "POST",
        body: { status, ...(reason ? { reason } : {}) } satisfies StatusUpdate,
      }),
    onSuccess: () => refreshReservations(client),
  });
}

export function useCompleteReservation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CompleteIn }) =>
      request<StaffReservation>(`/v1/staff/reservations/${id}/complete`, { method: "POST", body }),
    onSuccess: () => refreshReservations(client),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => request<StaffShop>("/v1/staff/settings"),
  });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: SettingsUpdate) =>
      request<StaffShop>("/v1/staff/settings", { method: "PATCH", body: patch }),
    onSuccess: (shop) => {
      client.setQueryData(queryKeys.settings, shop);
      client.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

function refreshStock(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ["stock"] });
  client.invalidateQueries({ queryKey: queryKeys.dashboard });
}

function refreshReservations(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ["reservations"] });
  client.invalidateQueries({ queryKey: ["reservation"] });
  client.invalidateQueries({ queryKey: queryKeys.dashboard });
  client.invalidateQueries({ queryKey: ["stock"] });
}
