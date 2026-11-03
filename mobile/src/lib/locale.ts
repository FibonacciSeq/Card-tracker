export const DEFAULT_LOCALE = "en" as const;
export const SUPPORTED_LOCALES = ["en", "sr"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export type TranslationKey =
  | "homeTitle"
  | "homeSubtitle"
  | "signInToSync"
  | "scanShopCode"
  | "specialOrders"
  | "restockAlerts"
  | "yourHolds"
  | "shopsOnCardTracker"
  | "optionalAccount"
  | "accountHeroTitle"
  | "accountHeroBody"
  | "emailMeCode"
  | "verifyAndSignIn"
  | "language"
  | "english"
  | "serbian"
  | "signedIn"
  | "signedInBody"
  | "holds"
  | "requests"
  | "alerts"
  | "turnOnPush"
  | "pushInfo"
  | "deviceNeedsNativePush"
  | "languageHint";

export const translationMap: Record<AppLocale, Record<TranslationKey, string>> = {
  en: {
    homeTitle: "Find the card you need.",
    homeSubtitle: "Browse local card shops, put a card on hold, and collect it in store.",
    signInToSync: "Sign in to sync your list",
    scanShopCode: "Scan a shop code",
    specialOrders: "Special orders",
    restockAlerts: "Restock alerts",
    yourHolds: "Your holds",
    shopsOnCardTracker: "Shops on Card Tracker",
    optionalAccount: "OPTIONAL ACCOUNT",
    accountHeroTitle: "Keep your card list with you.",
    accountHeroBody:
      "Sign in with a one-time email code to see your holds, restock alerts, and special orders on another device. Guest checkout still works without an account.",
    emailMeCode: "Email me a sign-in code",
    verifyAndSignIn: "Verify and sign in",
    language: "Language",
    english: "English",
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
  },
  sr: {
    homeTitle: "Pronađite kartu koju vam treba.",
    homeSubtitle: "Pregledajte lokalne prodavnice, rezervišite kartu i preuzmite je u prodavnici.",
    signInToSync: "Prijavite se da sinhronizujete listu",
    scanShopCode: "Skeniraj kod prodavnice",
    specialOrders: "Specijalni zahtevi",
    restockAlerts: "Obaveštenja o ponovnom dolasku",
    yourHolds: "Vaše rezervacije",
    shopsOnCardTracker: "Prodavnice na Card Tracker-u",
    optionalAccount: "OPCIONI NALOG",
    accountHeroTitle: "Zadržite svoju listu karata sa sobom.",
    accountHeroBody:
      "Prijavite se jednim e-mail kodom da vidite svoje rezervacije, obaveštenja i specijalne zahteve na drugom uređaju. Gostovska kupovina i dalje radi bez naloga.",
    emailMeCode: "Pošalji mi kod za prijavu",
    verifyAndSignIn: "Potvrdi i prijavi se",
    language: "Jezik",
    english: "English",
    serbian: "Srpski",
    signedIn: "PRIJAVLJENI STE",
    signedInBody: "Vaše rezervacije, obaveštenja i specijalni zahtevi prate ovaj verifikovani e-mail.",
    holds: "Rezervacije",
    requests: "Zahtevi",
    alerts: "Obaveštenja",
    turnOnPush: "Omogući obaveštenja",
    pushInfo:
      "Primite obaveštenje kada je rezervacija spremna, kada je specijalni zahtev ponuđen ili kada se karta vrati na lager.",
    deviceNeedsNativePush:
      "Obaveštenja zahtevaju fizički iOS ili Android uređaj. Web pregled i emulatori ne mogu da registruju native token.",
    languageHint: "Izaberite željeni jezik za aplikaciju.",
  },
};

export function normalizeLocale(value: string | null | undefined): AppLocale {
  const candidate = (value ?? DEFAULT_LOCALE).toLowerCase();
  return SUPPORTED_LOCALES.includes(candidate as AppLocale)
    ? (candidate as AppLocale)
    : DEFAULT_LOCALE;
}

export function getText(locale: AppLocale, key: TranslationKey): string {
  return translationMap[locale][key] ?? translationMap[DEFAULT_LOCALE][key] ?? key;
}
