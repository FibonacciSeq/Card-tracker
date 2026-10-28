import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Money } from "../api/types";
import { formatMoney } from "../lib/format";
import { colors, radii, shadow, spacing, type } from "../theme";

export function CartBar({
  count,
  total,
  bottomInset,
  onPress,
}: {
  count: number;
  total: Money | null;
  bottomInset: number;
  onPress: () => void;
}) {
  return (
    <View style={[styles.wrap, { paddingBottom: bottomInset + spacing.sm }]}>
      <Pressable
        accessibilityLabel={`Review your hold, ${count} cards`}
        accessibilityRole="button"
        onPress={onPress}
        style={({ pressed }) => [styles.bar, pressed && styles.pressed]}
      >
        <View style={styles.left}>
          <View style={styles.count}>
            <Text style={styles.countText}>{count}</Text>
          </View>
          <View>
            <Text style={styles.label}>Review your hold</Text>
            <Text style={styles.total}>{formatMoney(total)}</Text>
          </View>
        </View>
        <Ionicons name="arrow-forward" size={20} color={colors.white} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    backgroundColor: colors.background,
  },
  bar: {
    minHeight: 60,
    borderRadius: radii.lg,
    backgroundColor: colors.ink,
    paddingHorizontal: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    ...shadow.card,
  },
  pressed: { opacity: 0.88 },
  left: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  count: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  countText: {
    color: colors.white,
    fontSize: type.small,
    fontWeight: "900",
  },
  label: {
    color: colors.white,
    fontSize: type.small,
    fontWeight: "700",
  },
  total: {
    color: colors.white,
    fontSize: type.body,
    fontWeight: "900",
  },
});
