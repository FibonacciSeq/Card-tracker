import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { SavedReservation } from "../api/types";
import { formatMoney, formatRemaining } from "../lib/format";
import { colors, radii, spacing, type } from "../theme";
import { StatusPill } from "./StatusPill";

export function HoldCard({
  reservation,
  onPress,
}: {
  reservation: SavedReservation;
  onPress: () => void;
}) {
  const shop = reservation.shop as { name?: string; slug?: string };
  return (
    <Pressable
      accessibilityHint="Opens the reservation details"
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.top}>
        <View style={styles.titleWrap}>
          <Text style={styles.shop}>{String(shop.name ?? shop.slug ?? "Shop")}</Text>
          <Text style={styles.ref}>#{reservation.public_ref}</Text>
        </View>
        <StatusPill status={reservation.status} />
      </View>
      <View style={styles.bottom}>
        <View style={styles.meta}>
          <Ionicons name="time-outline" size={14} color={colors.inkMuted} />
          <Text style={styles.metaText}>{formatRemaining(reservation.expires_at)}</Text>
        </View>
        <Text style={styles.total}>{formatMoney(reservation.total)}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    gap: spacing.md,
  },
  pressed: { opacity: 0.82 },
  top: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  titleWrap: { flex: 1, gap: 2 },
  shop: {
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "800",
  },
  ref: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  bottom: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  meta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  metaText: {
    color: colors.inkMuted,
    fontSize: type.small,
  },
  total: {
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "800",
  },
});
