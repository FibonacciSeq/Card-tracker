import type { StockSort } from "../api/types";

export type AppearancePreference = "system" | "light" | "dark";
export type TimeFormatPreference = "auto" | "12h" | "24h";

export type MobilePreferences = {
  appearance: AppearancePreference;
  timeFormat: TimeFormatPreference;
  shopSortDefault: StockSort;
  shopAvailableOnlyDefault: boolean;
};

export const DEFAULT_MOBILE_PREFERENCES: MobilePreferences = {
  appearance: "system",
  timeFormat: "auto",
  shopSortDefault: "relevance",
  shopAvailableOnlyDefault: false,
};

export const APPEARANCE_OPTIONS: { value: AppearancePreference; labelKey: string }[] = [
  { value: "system", labelKey: "System" },
  { value: "light", labelKey: "Light" },
  { value: "dark", labelKey: "Dark" },
];

export const TIME_FORMAT_OPTIONS: { value: TimeFormatPreference; labelKey: string }[] = [
  { value: "auto", labelKey: "Automatic" },
  { value: "12h", labelKey: "12-hour" },
  { value: "24h", labelKey: "24-hour" },
];

export const SORT_OPTIONS: { value: StockSort; labelKey: string }[] = [
  { value: "relevance", labelKey: "Best match" },
  { value: "name", labelKey: "Name" },
  { value: "price_asc", labelKey: "Price ↑" },
  { value: "price_desc", labelKey: "Price ↓" },
  { value: "newest", labelKey: "Newest" },
];

function isAppearance(value: unknown): value is AppearancePreference {
  return value === "system" || value === "light" || value === "dark";
}

function isTimeFormat(value: unknown): value is TimeFormatPreference {
  return value === "auto" || value === "12h" || value === "24h";
}

function isSort(value: unknown): value is StockSort {
  return (
    value === "relevance" ||
    value === "name" ||
    value === "price_asc" ||
    value === "price_desc" ||
    value === "newest"
  );
}

export function normalizeMobilePreferences(
  value: Partial<MobilePreferences> | null | undefined,
): MobilePreferences {
  const raw = value ?? {};
  return {
    appearance: isAppearance(raw.appearance) ? raw.appearance : DEFAULT_MOBILE_PREFERENCES.appearance,
    timeFormat: isTimeFormat(raw.timeFormat) ? raw.timeFormat : DEFAULT_MOBILE_PREFERENCES.timeFormat,
    shopSortDefault: isSort(raw.shopSortDefault)
      ? raw.shopSortDefault
      : DEFAULT_MOBILE_PREFERENCES.shopSortDefault,
    shopAvailableOnlyDefault:
      typeof raw.shopAvailableOnlyDefault === "boolean"
        ? raw.shopAvailableOnlyDefault
        : DEFAULT_MOBILE_PREFERENCES.shopAvailableOnlyDefault,
  };
}
