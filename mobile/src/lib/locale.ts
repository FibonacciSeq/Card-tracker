export const DEFAULT_LOCALE = "en" as const;
export const SUPPORTED_LOCALES = ["en"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export type TranslationKey = string;
export type TranslationParams = Record<string, string | number>;

/** English-only build: translations removed, English strings are returned. */
export const translationMap: Record<AppLocale, Record<TranslationKey, string>> = {
  en: {
    homeTitle: "Find the card you need.",
    homeSubtitle: "Browse local card shops, put a card on hold, and collect it in store.",
    scanShopCode: "Scan a shop code",
    specialOrders: "Special orders",
    restockAlerts: "Restock alerts",
    yourHolds: "Your holds",
    shopsOnCardTracker: "Shops on Card Tracker",
    loginTitle: "Your card list, secured.",
    loginSubtitle:
      "Sign in to browse shops, place holds, and follow your special orders.",
    signInTab: "Sign in",
    createAccountTab: "Create account",
    resetPasswordTitle: "Reset your password",
    resetPasswordBody:
      "We will email a six-digit code. Enter it with a new password.",
    emailLabel: "Email",
    passwordLabel: "Password",
    currentPasswordLabel: "Current password",
    newPasswordLabel: "New password",
    confirmPasswordLabel: "Confirm password",
    verificationCodeLabel: "6-digit code",
    signInAction: "Sign in",
    sendVerificationCode: "Send verification code",
    sendResetCode: "Send reset code",
    verifyAndCreate: "Verify and create account",
    saveNewPassword: "Save new password",
    forgotPassword: "Forgot password?",
    backToSignIn: "Back to sign in",
    sendNewCode: "Send a new code",
    sendNewCodeIn: "Send a new code in",
    verificationSent: "We sent a verification code to",
    resetSent: "We sent a reset code to",
    passwordHint: "Use at least 8 characters.",
    passwordsDoNotMatch: "Passwords do not match.",
    loginPrivacy:
      "We store your password securely. Email codes are only used to verify a new account or reset a forgotten password.",
    language: "Language",
    english: "English",
    russian: "Русский",
    spanish: "Español",
    french: "Français",
    german: "Deutsch",
    serbian: "Srpski",
    signedIn: "SIGNED IN",
    signedInBody:
      "Your holds, alerts, and special orders follow this verified email.",
    holds: "Holds",
    requests: "Requests",
    alerts: "Alerts",
    turnOnPush: "Enable push notifications",
    pushInfo:
      "Get a notification when a hold is ready, a special order is quoted, or a card is back in stock.",
    deviceNeedsNativePush:
      "Push notifications need a physical iOS or Android device. The web preview and simulators cannot register a native token.",
    languageHint: "Choose your preferred language for the app.",
    accountPasswordTitle: "Password",
    accountPasswordBody: "Your account uses a password to sign in.",
    setPassword: "Set a password",
    changePassword: "Change password",
    savePassword: "Save password",
    passwordUpdated: "Password updated. Other devices were signed out.",
    passwordSet: "Password set. You can now sign in with it.",
    appPreferences: "App preferences",
    appPreferencesHint: "Saved on this device and applied across the app.",
    appearance: "Appearance",
    appearanceHint: "Choose light, dark, or follow your system.",
    system: "System",
    light: "Light",
    dark: "Dark",
    timeFormat: "Time format",
    timeFormatHint: "How times are shown in dates and details.",
    automatic: "Automatic",
    hour12: "12-hour",
    hour24: "24-hour",
    catalogDefaults: "Shop catalog defaults",
    catalogDefaultsHint: "Used when you open a shop.",
    defaultSort: "Default sort",
    sortRelevance: "Best match",
    sortName: "Name",
    sortPriceAsc: "Price ↑",
    sortPriceDesc: "Price ↓",
    sortNewest: "Newest",
    defaultAvailableOnly: "Show only available cards by default",
  },
};

export function normalizeLocale(_value: string | null | undefined): AppLocale {
  return DEFAULT_LOCALE;
}

export function getText(locale: AppLocale, key: TranslationKey, params?: TranslationParams): string {
  const template = translationMap.en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));
}
