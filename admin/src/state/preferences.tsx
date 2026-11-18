import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  DEFAULT_ADMIN_PREFERENCES,
  normalizeAdminPreferences,
  type AdminPreferences,
} from "../lib/preferences";

const STORAGE_KEY = "cardtracker.admin.preferences.v1";

type PreferencesContextValue = {
  preferences: AdminPreferences;
  updatePreferences: (patch: Partial<AdminPreferences>) => void;
};

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

function readStored(): AdminPreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ADMIN_PREFERENCES;
    return normalizeAdminPreferences(JSON.parse(raw) as Partial<AdminPreferences>);
  } catch {
    return DEFAULT_ADMIN_PREFERENCES;
  }
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<AdminPreferences>(readStored);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  }, [preferences]);

  useEffect(() => {
    const root = document.documentElement;
    if (preferences.theme === "system") {
      root.removeAttribute("data-theme");
      root.style.colorScheme = "light dark";
    } else {
      root.setAttribute("data-theme", preferences.theme);
      root.style.colorScheme = preferences.theme;
    }
  }, [preferences.theme]);

  const updatePreferences = useCallback((patch: Partial<AdminPreferences>) => {
    setPreferences((current) => normalizeAdminPreferences({ ...current, ...patch }));
  }, []);

  const value = useMemo(
    () => ({ preferences, updatePreferences }),
    [preferences, updatePreferences],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext);
  if (!context) throw new Error("usePreferences must be used inside PreferencesProvider");
  return context;
}
