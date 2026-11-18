import {
  SUPPORTED_LOCALES,
  type AppLocale,
  type TranslationKey,
} from "../lib/locale";
import { useLocale } from "../state/locale";

const LANGUAGE_LABELS: Record<AppLocale, TranslationKey> = {
  en: "english",
  ru: "russian",
  es: "spanish",
  fr: "french",
  de: "german",
  sr: "serbian",
};

/** Lets a shop owner or staff member switch the admin language at any time. */
export function LanguagePicker() {
  const { locale, setLocale, t } = useLocale();

  return (
    <label className="field field--inline language-picker">
      <span>{t("language")}</span>
      <select
        value={locale}
        onChange={(event) => setLocale(event.target.value as AppLocale)}
        aria-label={t("language")}
        data-testid="admin-language-picker"
      >
        {SUPPORTED_LOCALES.map((option) => (
          <option key={option} value={option}>
            {t(LANGUAGE_LABELS[option])}
          </option>
        ))}
      </select>
    </label>
  );
}
