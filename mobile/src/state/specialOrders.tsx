import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { CardRequest } from "../api/types";
import { readGuestToken, writeGuestToken } from "../lib/tokenStore";

const STORAGE_KEY = "cardtracker.card-requests.v1";
const TOKEN_PREFIX = "cardtracker.card-request-token.";

export type SavedCardRequest = Omit<CardRequest, "access_token"> & {
  shopSlug: string;
  shopName: string;
};

export type CardRequestMeta = {
  shopSlug: string;
  shopName: string;
};

type SpecialOrdersContextValue = {
  hydrated: boolean;
  requests: SavedCardRequest[];
  save: (request: CardRequest, meta: CardRequestMeta) => Promise<void>;
  update: (id: string, patch: Partial<SavedCardRequest>) => void;
  get: (id: string) => SavedCardRequest | undefined;
  getToken: (id: string) => Promise<string | null>;
};

const SpecialOrdersContext = createContext<SpecialOrdersContextValue | null>(null);

function tokenKey(id: string): string {
  return `${TOKEN_PREFIX}${id}`;
}

function parseRequests(value: string | null): SavedCardRequest[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as SavedCardRequest[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function SpecialOrdersProvider({ children }: { children: ReactNode }) {
  const [requests, setRequests] = useState<SavedCardRequest[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (active) setRequests(parseRequests(value));
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setHydrated(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(requests)).catch(() => undefined);
  }, [hydrated, requests]);

  const save = useCallback(async (request: CardRequest, meta: CardRequestMeta) => {
    const { access_token: accessToken, ...rest } = request;
    const saved: SavedCardRequest = { ...rest, ...meta };
    setRequests((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    if (accessToken) await writeGuestToken(tokenKey(saved.id), accessToken);
  }, []);

  const update = useCallback((id: string, patch: Partial<SavedCardRequest>) => {
    setRequests((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }, []);

  const get = useCallback(
    (id: string) => requests.find((request) => request.id === id),
    [requests],
  );

  const value = useMemo(
    () => ({
      hydrated,
      requests,
      save,
      update,
      get,
      getToken: (id: string) => readGuestToken(tokenKey(id)),
    }),
    [get, hydrated, requests, save, update],
  );

  return (
    <SpecialOrdersContext.Provider value={value}>{children}</SpecialOrdersContext.Provider>
  );
}

export function useSpecialOrders(): SpecialOrdersContextValue {
  const context = useContext(SpecialOrdersContext);
  if (!context) throw new Error("useSpecialOrders must be used inside SpecialOrdersProvider");
  return context;
}
