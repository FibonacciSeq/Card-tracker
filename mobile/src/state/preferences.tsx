import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Appearance, Platform } from "react-native";

import {
  DEFAULT_MOBILE_PREFERENCES,
  normalizeMobilePreferences,
  type MobilePreferences,
} from "../lib/preferences";

const STORAGE_KEY = "cardtracker.preferences.v1";

type PreferencesContextValue = {
  preferences: MobilePreferences;
  hydrated: boolean;
  updatePreferences: (patch: Partial<MobilePreferences>) => void;
};

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<MobilePreferences>(DEFAULT_MOBILE_PREFERENCES);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (!active || !value) return;
        try {
          setPreferences(normalizeMobilePreferences(JSON.parse(value) as Partial<MobilePreferences>));
        } catch {
          setPreferences(DEFAULT_MOBILE_PREFERENCES);
        }
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
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)).catch(() => undefined);
  }, [hydrated, preferences]);

  useEffect(() => {
    if (!hydrated) return;
    if (Platform.OS === "web") return;
    const setColorScheme = (Appearance as { setColorScheme?: (scheme: "light" | "dark" | null) => void })
      .setColorScheme;
    if (typeof setColorScheme !== "function") return;
    if (preferences.appearance === "system") {
      setColorScheme(null);
    } else {
      setColorScheme(preferences.appearance);
    }
  }, [hydrated, preferences.appearance]);

  const updatePreferences = useCallback((patch: Partial<MobilePreferences>) => {
    setPreferences((current) => normalizeMobilePreferences({ ...current, ...patch }));
  }, []);

  const value = useMemo(
    () => ({ preferences, hydrated, updatePreferences }),
    [preferences, hydrated, updatePreferences],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext);
  if (!context) throw new Error("usePreferences must be used inside PreferencesProvider");
  return context;
}
