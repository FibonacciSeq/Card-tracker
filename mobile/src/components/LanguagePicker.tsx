import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { SUPPORTED_LOCALES, type AppLocale, type TranslationKey } from "../lib/locale";
import { useLocale } from "../state/locale";
import { colors, radii, spacing, type } from "../theme";

const LANGUAGE_LABELS: Record<AppLocale, TranslationKey> = {
  en: "english",
  ru: "russian",
  es: "spanish",
  fr: "french",
  de: "german",
  sr: "serbian",
};

/** Lets a customer or shop owner switch the app language at any time. */
export function LanguagePicker() {
  const { locale, setLocale, t } = useLocale();

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Ionicons name="language-outline" size={18} color={colors.primary} />
        <Text style={styles.label}>{t("language")}</Text>
      </View>
      <Text style={styles.hint}>{t("languageHint")}</Text>
      <View style={styles.row}>
        {SUPPORTED_LOCALES.map((option) => {
          const active = locale === option;
          return (
            <Pressable
              key={option}
              accessibilityRole="button"
              accessibilityState={{ selected: active }}
              onPress={() => setLocale(option)}
              style={({ pressed }) => [
                styles.button,
                active && styles.buttonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text style={[styles.buttonText, active && styles.buttonTextActive]}>
                {t(LANGUAGE_LABELS[option])}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    gap: spacing.sm,
  },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  label: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  hint: { color: colors.inkMuted, fontSize: type.small, lineHeight: 18 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  button: {
    minWidth: 96,
    flexGrow: 1,
    minHeight: 40,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
    paddingHorizontal: spacing.sm,
  },
  buttonActive: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  buttonText: { color: colors.ink, fontSize: type.small, fontWeight: "700" },
  buttonTextActive: { color: colors.primary },
  pressed: { opacity: 0.7 },
});
