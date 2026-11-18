import { StyleSheet, Text, View } from "react-native";

import { statusTone, titleCase } from "../lib/format";
import { useLocale } from "../state/locale";
import { colors, radii, spacing, type } from "../theme";

const STATUS_LABELS: Record<string, string> = {
  READY: "Ready",
  REQUESTED: "Requested",
  CONFIRMED: "Confirmed",
  QUOTED: "Quoted",
  ACCEPTED: "Accepted",
  CONVERTED: "Converted",
  CANCELLED: "Cancelled",
  EXPIRED: "Expired",
  DECLINED: "Declined",
};

export function StatusPill({ status }: { status: string }) {
  const { t } = useLocale();
  const tone = statusTone(status);
  const label = STATUS_LABELS[status] ?? t(titleCase(status));
  return (
    <View
      style={[
        styles.pill,
        tone === "success" && styles.success,
        tone === "accent" && styles.accent,
        tone === "danger" && styles.danger,
      ]}
    >
      <Text
        style={[
          styles.label,
          tone === "success" && styles.successLabel,
          tone === "accent" && styles.accentLabel,
          tone === "danger" && styles.dangerLabel,
        ]}
      >
        {t(label)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignSelf: "flex-start",
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
  },
  success: { backgroundColor: colors.successSoft },
  accent: { backgroundColor: colors.accentSoft },
  danger: { backgroundColor: colors.dangerSoft },
  label: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    fontWeight: "800",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  successLabel: { color: colors.success },
  accentLabel: { color: colors.accent },
  dangerLabel: { color: colors.danger },
});
