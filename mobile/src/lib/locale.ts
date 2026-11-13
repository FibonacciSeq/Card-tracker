export const DEFAULT_LOCALE = "en" as const;
export const SUPPORTED_LOCALES = ["en", "sr"] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

export type TranslationKey =
  | "homeTitle"
  | "homeSubtitle"
  | "scanShopCode"
  | "specialOrders"
  | "restockAlerts"
  | "yourHolds"
  | "shopsOnCardTracker"
  | "loginTitle"
  | "loginSubtitle"
  | "signInTab"
  | "createAccountTab"
  | "resetPasswordTitle"
  | "resetPasswordBody"
  | "emailLabel"
  | "passwordLabel"
  | "currentPasswordLabel"
  | "newPasswordLabel"
  | "confirmPasswordLabel"
  | "verificationCodeLabel"
  | "signInAction"
  | "sendVerificationCode"
  | "sendResetCode"
  | "verifyAndCreate"
  | "saveNewPassword"
  | "forgotPassword"
  | "backToSignIn"
  | "sendNewCode"
  | "sendNewCodeIn"
  | "verificationSent"
  | "resetSent"
  | "passwordHint"
  | "passwordsDoNotMatch"
  | "loginPrivacy"
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
  | "languageHint"
  | "accountPasswordTitle"
  | "accountPasswordBody"
  | "setPassword"
  | "changePassword"
  | "savePassword"
  | "passwordUpdated"
  | "passwordSet";

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
  },
  sr: {
    homeTitle: "Pronađite kartu koju vam treba.",
    homeSubtitle: "Pregledajte lokalne prodavnice, rezervišite kartu i preuzmite je u prodavnici.",
    scanShopCode: "Skeniraj kod prodavnice",
    specialOrders: "Specijalni zahtevi",
    restockAlerts: "Obaveštenja o ponovnom dolasku",
    yourHolds: "Vaše rezervacije",
    shopsOnCardTracker: "Prodavnice na Card Tracker-u",
    loginTitle: "Vaša lista karata, zaštićena.",
    loginSubtitle:
      "Prijavite se da pregledate prodavnice, rezervišete karte i pratite specijalne zahteve.",
    signInTab: "Prijava",
    createAccountTab: "Novi nalog",
    resetPasswordTitle: "Resetujte lozinku",
    resetPasswordBody:
      "Poslaćemo vam šestocifreni kod. Unesite ga sa novom lozinkom.",
    emailLabel: "E-mail",
    passwordLabel: "Lozinka",
    currentPasswordLabel: "Trenutna lozinka",
    newPasswordLabel: "Nova lozinka",
    confirmPasswordLabel: "Potvrdite lozinku",
    verificationCodeLabel: "Šestocifreni kod",
    signInAction: "Prijavi se",
    sendVerificationCode: "Pošalji verifikacioni kod",
    sendResetCode: "Pošalji kod za reset",
    verifyAndCreate: "Potvrdi i otvori nalog",
    saveNewPassword: "Sačuvaj novu lozinku",
    forgotPassword: "Zaboravili ste lozinku?",
    backToSignIn: "Nazad na prijavu",
    sendNewCode: "Pošalji novi kod",
    sendNewCodeIn: "Pošalji novi kod za",
    verificationSent: "Poslali smo verifikacioni kod na",
    resetSent: "Poslali smo kod za reset na",
    passwordHint: "Koristite najmanje 8 karaktera.",
    passwordsDoNotMatch: "Lozinke se ne poklapaju.",
    loginPrivacy:
      "Vaša lozinka se čuva bezbedno. E-mail kodovi se koriste samo za verifikaciju novog naloga ili reset zaboravljene lozinke.",
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
    accountPasswordTitle: "Lozinka",
    accountPasswordBody: "Vaš nalog koristi lozinku za prijavu.",
    setPassword: "Postavi lozinku",
    changePassword: "Promeni lozinku",
    savePassword: "Sačuvaj lozinku",
    passwordUpdated: "Lozinka je promenjena. Ostali uređaji su odjavljeni.",
    passwordSet: "Lozinka je postavljena. Sada možete da se prijavite njom.",
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
