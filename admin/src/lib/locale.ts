export const DEFAULT_LOCALE = "en" as const;
export const SUPPORTED_LOCALES = ["en"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];
export type TranslationKey = string;
export type TranslationParams = Record<string, string | number>;

/** English-only build: translations removed, keys/English text are returned as-is. */
export const translationMap: Record<AppLocale, Record<TranslationKey, string>> = {
  en: {
    english: "English",
    language: "Language",
    "Skip to content": "Skip to content",
    "Shop admin": "Shop admin",
    Main: "Main",
    Dashboard: "Dashboard",
    Notifications: "Notifications",
    Stock: "Stock",
    Reservations: "Reservations",
    "Special orders": "Special orders",
    Team: "Team",
    Activity: "Activity",
    Settings: "Settings",
    "Sign out": "Sign out",
    "One unread notification": "One unread notification",
    "{count} unread notifications": "{count} unread notifications",
  },
};

export function normalizeLocale(_value: string | null | undefined): AppLocale {
  return DEFAULT_LOCALE;
}

export function getText(
  _locale: AppLocale,
  key: TranslationKey,
  params?: TranslationParams,
): string {
  const template = translationMap.en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));
}
