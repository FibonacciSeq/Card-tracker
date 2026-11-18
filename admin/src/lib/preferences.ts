export type ThemePreference = "system" | "light" | "dark";
export type TimeFormatPreference = "auto" | "12h" | "24h";

export type StockViewPreference = "active" | "archived";

export type AdminPreferences = {
  theme: ThemePreference;
  timeFormat: TimeFormatPreference;
  stockDefaultView: StockViewPreference;
  stockOnlyOnline: boolean;
  reservationsDefaultStatus: string;
  requestsDefaultStatus: string;
  activityDefaultFilter: string;
};

export const DEFAULT_ADMIN_PREFERENCES: AdminPreferences = {
  theme: "system",
  timeFormat: "auto",
  stockDefaultView: "active",
  stockOnlyOnline: false,
  reservationsDefaultStatus: "ALL",
  requestsDefaultStatus: "ALL",
  activityDefaultFilter: "",
};

export const THEME_OPTIONS: { value: ThemePreference; labelKey: string }[] = [
  { value: "system", labelKey: "System" },
  { value: "light", labelKey: "Light" },
  { value: "dark", labelKey: "Dark" },
];

export const TIME_FORMAT_OPTIONS: { value: TimeFormatPreference; labelKey: string }[] = [
  { value: "auto", labelKey: "Automatic" },
  { value: "12h", labelKey: "12-hour" },
  { value: "24h", labelKey: "24-hour" },
];

function isTheme(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function isTimeFormat(value: unknown): value is TimeFormatPreference {
  return value === "auto" || value === "12h" || value === "24h";
}

function isStockView(value: unknown): value is StockViewPreference {
  return value === "active" || value === "archived";
}

export function normalizeAdminPreferences(
  value: Partial<AdminPreferences> | null | undefined,
): AdminPreferences {
  const raw = value ?? {};
  return {
    theme: isTheme(raw.theme) ? raw.theme : DEFAULT_ADMIN_PREFERENCES.theme,
    timeFormat: isTimeFormat(raw.timeFormat) ? raw.timeFormat : DEFAULT_ADMIN_PREFERENCES.timeFormat,
    stockDefaultView: isStockView(raw.stockDefaultView)
      ? raw.stockDefaultView
      : DEFAULT_ADMIN_PREFERENCES.stockDefaultView,
    stockOnlyOnline:
      typeof raw.stockOnlyOnline === "boolean"
        ? raw.stockOnlyOnline
        : DEFAULT_ADMIN_PREFERENCES.stockOnlyOnline,
    reservationsDefaultStatus:
      typeof raw.reservationsDefaultStatus === "string" && raw.reservationsDefaultStatus
        ? raw.reservationsDefaultStatus
        : DEFAULT_ADMIN_PREFERENCES.reservationsDefaultStatus,
    requestsDefaultStatus:
      typeof raw.requestsDefaultStatus === "string" && raw.requestsDefaultStatus
        ? raw.requestsDefaultStatus
        : DEFAULT_ADMIN_PREFERENCES.requestsDefaultStatus,
    activityDefaultFilter:
      typeof raw.activityDefaultFilter === "string"
        ? raw.activityDefaultFilter
        : DEFAULT_ADMIN_PREFERENCES.activityDefaultFilter,
  };
}
