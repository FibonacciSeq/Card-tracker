import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { SavedCardRequest } from "../state/specialOrders";
import { formatMoney, formatRemaining } from "../lib/format";
import { colors, radii, spacing, type } from "../theme";
import { StatusPill } from "./StatusPill";

export function RequestCard({
  request,
  onPress,
}: {
  request: SavedCardRequest;
  onPress: () => void;
}) {
  const price = request.quote_price ?? request.target_price;
  const quoteActive = request.status === "QUOTED" && request.quote_expires_at;

  return (
    <Pressable
      accessibilityHint="Opens the special-order details"
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.top}>
        <View style={styles.titleWrap}>
          <Text style={styles.shop}>{request.shopName}</Text>
          <Text numberOfLines={1} style={styles.name}>
            {request.requested_name}
          </Text>
          <Text style={styles.ref}>#{request.public_ref}</Text>
        </View>
        <StatusPill status={request.status} />
      </View>

      <View style={styles.bottom}>
        <View style={styles.meta}>
          <Ionicons
            name={quoteActive ? "time-outline" : "albums-outline"}
            size={14}
            color={colors.inkMuted}
          />
          <Text style={styles.metaText}>
            {quoteActive
              ? `Quote ${formatRemaining(request.quote_expires_at ?? "")}`
              : `Qty ${request.quantity}`}
          </Text>
        </View>
        {price ? <Text style={styles.price}>{formatMoney(price)}</Text> : null}
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
  shop: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  name: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
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
    gap: spacing.sm,
  },
  meta: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { color: colors.inkMuted, fontSize: type.small },
  price: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
});
