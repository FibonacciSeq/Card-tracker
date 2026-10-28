import { useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { getReservation, getShop, getShops, getStock } from "./client";
import type { StockSort } from "./types";

export const queryKeys = {
  shops: (search: string) => ["shops", search] as const,
  shop: (slug: string) => ["shop", slug] as const,
  stock: (slug: string, search: string, sort: StockSort, availableOnly: boolean) =>
    ["stock", slug, search, sort, availableOnly] as const,
  reservation: (id: string) => ["reservation", id] as const,
};

export function useShops(search: string) {
  return useQuery({
    queryKey: queryKeys.shops(search),
    queryFn: ({ signal }) => getShops(search, signal),
    staleTime: 30_000,
  });
}

export function useShop(slug: string) {
  return useQuery({
    queryKey: queryKeys.shop(slug),
    queryFn: ({ signal }) => getShop(slug, signal),
    enabled: Boolean(slug),
    staleTime: 60_000,
  });
}

export function useStock(
  slug: string,
  search: string,
  sort: StockSort,
  availableOnly: boolean,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.stock(slug, search, sort, availableOnly),
    queryFn: ({ pageParam, signal }) =>
      getStock(slug, { query: search, sort, availableOnly, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(slug),
    staleTime: 15_000,
  });
}

export function useGuestReservation(
  id: string,
  slug: string,
  token: string | null,
) {
  return useQuery({
    queryKey: [...queryKeys.reservation(id), token],
    queryFn: ({ signal }) => getReservation(id, slug, token ?? "", signal),
    enabled: Boolean(id && slug && token),
    retry: (count, error) => {
      const status = (error as { status?: number }).status;
      return status !== 403 && count < 1;
    },
  });
}

export function useDebouncedValue<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [delay, value]);
  return debounced;
}
