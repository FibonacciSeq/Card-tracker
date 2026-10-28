import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { StockItem } from "../api/types";
import { formatMoney, titleCase } from "../lib/format";
import { colors, radii, shadow, spacing, type } from "../theme";

type StockCardProps = {
  item: StockItem;
  quantity: number;
  onAdd: () => void;
  onIncrease: () => void;
  onDecrease: () => void;
};

export function StockCard({ item, quantity, onAdd, onIncrease, onDecrease }: StockCardProps) {
  const soldOut = item.available <= 0;
  return (
    <View style={styles.card}>
      <View style={styles.imageWrap}>
        {item.card.image_small ? (
          <Image
            source={{ uri: item.card.image_small }}
            style={styles.image}
            contentFit="cover"
            transition={120}
          />
        ) : (
          <View style={styles.imageFallback}>
            <Ionicons name="albums-outline" size={24} color={colors.inkMuted} />
          </View>
        )}
      </View>
      <View style={styles.body}>
        <View style={styles.titleRow}>
          <Text numberOfLines={2} style={styles.name}>
            {item.card.name}
          </Text>
          <Text style={styles.price}>{formatMoney(item.price)}</Text>
        </View>
        <Text style={styles.setLine}>
          {item.card.set_code.toUpperCase()} · #{item.card.collector_number} · {item.card.rarity}
        </Text>
        <View style={styles.badgeRow}>
          <Text style={styles.badge}>{titleCase(item.finish)}</Text>
          <Text style={styles.badge}>{item.condition}</Text>
          <Text style={styles.badge}>{item.language.toUpperCase()}</Text>
        </View>
        <View style={styles.bottomRow}>
          <Text style={[styles.available, soldOut && styles.soldOut]}>
            {soldOut ? "Sold out" : `${item.available} available`}
          </Text>
          {soldOut ? (
            <View style={styles.unavailable}>
              <Text style={styles.unavailableText}>No holds</Text>
            </View>
          ) : quantity > 0 ? (
            <View style={styles.stepper}>
              <Pressable
                accessibilityLabel={`Remove one ${item.card.name}`}
                accessibilityRole="button"
                hitSlop={6}
                onPress={onDecrease}
                style={styles.stepButton}
              >
                <Ionicons name="remove" size={16} color={colors.primary} />
              </Pressable>
              <Text style={styles.quantity}>{quantity}</Text>
              <Pressable
                accessibilityLabel={`Add another ${item.card.name}`}
                accessibilityRole="button"
                disabled={quantity >= item.available}
                hitSlop={6}
                onPress={onIncrease}
                style={[styles.stepButton, quantity >= item.available && styles.stepDisabled]}
              >
                <Ionicons name="add" size={16} color={colors.primary} />
              </Pressable>
            </View>
          ) : (
            <Pressable
              accessibilityLabel={`Add ${item.card.name} to your hold`}
              accessibilityRole="button"
              onPress={onAdd}
              style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
            >
              <Ionicons name="add" size={16} color={colors.white} />
              <Text style={styles.addLabel}>Add</Text>
            </Pressable>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    ...shadow.card,
  },
  imageWrap: {
    width: 76,
    height: 104,
    borderRadius: radii.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceMuted,
  },
  image: { width: "100%", height: "100%" },
  imageFallback: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  body: { flex: 1, gap: 3 },
  titleRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  name: {
    flex: 1,
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "800",
    lineHeight: 20,
  },
  price: {
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "900",
  },
  setLine: {
    color: colors.inkMuted,
    fontSize: type.tiny,
  },
  badgeRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 2,
  },
  badge: {
    backgroundColor: colors.surfaceMuted,
    color: colors.inkMuted,
    fontSize: 10,
    fontWeight: "800",
    borderRadius: radii.pill,
    paddingHorizontal: 7,
    paddingVertical: 2,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  bottomRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: "auto",
    paddingTop: spacing.sm,
  },
  available: {
    color: colors.success,
    fontSize: type.small,
    fontWeight: "700",
  },
  soldOut: { color: colors.inkMuted },
  addButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    backgroundColor: colors.primary,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  addLabel: {
    color: colors.white,
    fontSize: type.small,
    fontWeight: "800",
  },
  pressed: { opacity: 0.8 },
  stepper: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.pill,
    backgroundColor: colors.background,
    overflow: "hidden",
  },
  stepButton: {
    width: 32,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
  },
  stepDisabled: { opacity: 0.35 },
  quantity: {
    minWidth: 22,
    textAlign: "center",
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "800",
  },
  unavailable: {
    borderRadius: radii.pill,
    backgroundColor: colors.surfaceMuted,
    paddingHorizontal: spacing.md,
    paddingVertical: 7,
  },
  unavailableText: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    fontWeight: "700",
  },
});
