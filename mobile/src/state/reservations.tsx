import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { Reservation, SavedReservation } from "../api/types";

const STORAGE_KEY = "cardtracker.reservations.v1";
const TOKEN_PREFIX = "cardtracker.reservation-token.";

type ReservationsContextValue = {
  hydrated: boolean;
  reservations: SavedReservation[];
  save: (reservation: Reservation, token: string) => Promise<void>;
  update: (id: string, patch: Partial<SavedReservation>) => void;
  get: (id: string) => SavedReservation | undefined;
  getToken: (id: string) => Promise<string | null>;
};

const ReservationsContext = createContext<ReservationsContextValue | null>(null);

function tokenKey(id: string): string {
  return `${TOKEN_PREFIX}${id}`;
}

async function writeToken(id: string, token: string): Promise<void> {
  if (Platform.OS === "web") {
    await AsyncStorage.setItem(tokenKey(id), token);
    return;
  }
  await SecureStore.setItemAsync(tokenKey(id), token);
}

async function readToken(id: string): Promise<string | null> {
  if (Platform.OS === "web") return AsyncStorage.getItem(tokenKey(id));
  return SecureStore.getItemAsync(tokenKey(id));
}

function parseReservations(value: string | null): SavedReservation[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as SavedReservation[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function ReservationsProvider({ children }: { children: ReactNode }) {
  const [reservations, setReservations] = useState<SavedReservation[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (active) setReservations(parseReservations(value));
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
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(reservations)).catch(() => undefined);
  }, [hydrated, reservations]);

  const save = useCallback(async (reservation: Reservation, token: string) => {
    const { access_token: _accessToken, ...saved } = reservation;
    setReservations((current) => [
      saved,
      ...current.filter((item) => item.id !== saved.id),
    ]);
    if (token) await writeToken(saved.id, token);
  }, []);

  const update = useCallback((id: string, patch: Partial<SavedReservation>) => {
    setReservations((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }, []);

  const get = useCallback(
    (id: string) => reservations.find((reservation) => reservation.id === id),
    [reservations],
  );

  const value = useMemo(
    () => ({
      hydrated,
      reservations,
      save,
      update,
      get,
      getToken: readToken,
    }),
    [get, hydrated, reservations, save, update],
  );

  return <ReservationsContext.Provider value={value}>{children}</ReservationsContext.Provider>;
}

export function useReservations(): ReservationsContextValue {
  const context = useContext(ReservationsContext);
  if (!context) throw new Error("useReservations must be used inside ReservationsProvider");
  return context;
}
