import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { RestockAlert } from "../api/types";
import { readGuestToken, removeGuestToken, writeGuestToken } from "../lib/tokenStore";

const STORAGE_KEY = "cardtracker.restock-alerts.v1";
const TOKEN_PREFIX = "cardtracker.restock-token.";

export type SavedRestockAlert = Omit<
  RestockAlert,
  "manage_token" | "already_subscribed"
> & {
  shopSlug: string;
  shopName: string;
  cardName: string;
  stockId: string;
};

export type RestockAlertMeta = {
  shopSlug: string;
  shopName: string;
  cardName: string;
  stockId: string;
};

type RestockAlertsContextValue = {
  hydrated: boolean;
  alerts: SavedRestockAlert[];
  save: (alert: RestockAlert, meta: RestockAlertMeta) => Promise<void>;
  remove: (id: string) => Promise<void>;
  get: (id: string) => SavedRestockAlert | undefined;
  getToken: (id: string) => Promise<string | null>;
  findForVariant: (
    shopSlug: string,
    cardId: string,
    finish: string,
    condition: string,
    language: string,
  ) => SavedRestockAlert | undefined;
};

const RestockAlertsContext = createContext<RestockAlertsContextValue | null>(null);

function tokenKey(id: string): string {
  return `${TOKEN_PREFIX}${id}`;
}

function parseAlerts(value: string | null): SavedRestockAlert[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as SavedRestockAlert[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function RestockAlertsProvider({ children }: { children: ReactNode }) {
  const [alerts, setAlerts] = useState<SavedRestockAlert[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (active) setAlerts(parseAlerts(value));
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
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(alerts)).catch(() => undefined);
  }, [alerts, hydrated]);

  const save = useCallback(async (alert: RestockAlert, meta: RestockAlertMeta) => {
    const { manage_token: manageToken, already_subscribed: _alreadySubscribed, ...rest } = alert;
    const saved: SavedRestockAlert = { ...rest, ...meta };
    setAlerts((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    if (manageToken) await writeGuestToken(tokenKey(saved.id), manageToken);
  }, []);

  const remove = useCallback(async (id: string) => {
    setAlerts((current) => current.filter((item) => item.id !== id));
    await removeGuestToken(tokenKey(id));
  }, []);

  const get = useCallback(
    (id: string) => alerts.find((alert) => alert.id === id),
    [alerts],
  );

  const findForVariant = useCallback(
    (shopSlug: string, cardId: string, finish: string, condition: string, language: string) =>
      alerts.find(
        (alert) =>
          alert.shopSlug === shopSlug &&
          alert.card_id === cardId &&
          alert.finish === finish &&
          alert.condition === condition &&
          alert.language === language,
      ),
    [alerts],
  );

  const value = useMemo(
    () => ({
      hydrated,
      alerts,
      save,
      remove,
      get,
      getToken: (id: string) => readGuestToken(tokenKey(id)),
      findForVariant,
    }),
    [alerts, findForVariant, get, hydrated, remove, save],
  );

  return (
    <RestockAlertsContext.Provider value={value}>{children}</RestockAlertsContext.Provider>
  );
}

export function useRestockAlerts(): RestockAlertsContextValue {
  const context = useContext(RestockAlertsContext);
  if (!context) throw new Error("useRestockAlerts must be used inside RestockAlertsProvider");
  return context;
}
