import { StyleSheet, Text, View } from "react-native";

import { statusTone, titleCase } from "../lib/format";
import { colors, radii, spacing, type } from "../theme";

export function StatusPill({ status }: { status: string }) {
  const tone = statusTone(status);
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
        {titleCase(status)}
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
