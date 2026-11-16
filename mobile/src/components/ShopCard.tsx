import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { ShopSearch } from "../api/types";
import { formatMoney } from "../lib/format";
import { formatDistanceKm } from "../lib/geo";
import { colors, radii, shadow, spacing, type } from "../theme";

export function ShopCard({ shop, onPress }: { shop: ShopSearch; onPress: () => void }) {
  const name = shop.brand_name || shop.name;
  const distance = shop.distance_km == null ? "" : formatDistanceKm(shop.distance_km);
  const matchingVariants = shop.product_variant_count ?? 0;
  const available = shop.product_available ?? 0;
  const hasProduct = matchingVariants > 0;
  const soldOut = available <= 0;
  const statusText = soldOut
    ? "Out of stock"
    : `${available} in stock${matchingVariants > 1 ? ` · ${matchingVariants} variants` : ""}`;
  const priceText = shop.product_from_price ? formatMoney(shop.product_from_price) : null;
  return (
    <Pressable
      accessibilityHint="Opens this shop's storefront"
      accessibilityLabel={
        hasProduct
          ? `${name}, ${soldOut ? "out of stock" : `${available} in stock`}`
          : name
      }
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.logo}>
        {shop.logo_url ? (
          <Image source={{ uri: shop.logo_url }} style={styles.logoImage} contentFit="cover" />
        ) : (
          <Text style={styles.logoLetter}>{name.slice(0, 1).toUpperCase()}</Text>
        )}
      </View>
      <View style={styles.body}>
        <Text numberOfLines={1} style={styles.name}>
          {name}
        </Text>
        <Text style={styles.slug}>@{shop.slug}</Text>
        <View style={styles.metaRow}>
          <Ionicons name="time-outline" size={13} color={colors.inkMuted} />
          <Text style={styles.meta}>{shop.hold_hours}h holds</Text>
          <Ionicons
            name={distance ? "navigate-outline" : "location-outline"}
            size={13}
            color={colors.inkMuted}
          />
          <Text numberOfLines={1} style={styles.meta}>
            {distance ? `${distance} away` : shop.timezone.replace(/_/g, " ")}
          </Text>
        </View>
        {hasProduct ? (
          <View style={styles.productRow}>
            <View style={[styles.stockPill, soldOut ? styles.outOfStockPill : styles.inStockPill]}>
              <Ionicons
                name={soldOut ? "close-circle" : "checkmark-circle"}
                size={12}
                color={soldOut ? colors.danger : colors.success}
              />
              <Text style={[styles.stockLabel, soldOut ? styles.outOfStockLabel : styles.inStockLabel]}>
                {statusText}
              </Text>
            </View>
            {priceText ? (
              <Text style={styles.priceLabel}>{soldOut ? priceText : `from ${priceText}`}</Text>
            ) : null}
          </View>
        ) : null}
      </View>
      <Ionicons name="chevron-forward" size={20} color={colors.inkMuted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    ...shadow.card,
  },
  pressed: {
    opacity: 0.82,
  },
  logo: {
    width: 54,
    height: 54,
    borderRadius: 16,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  logoImage: {
    width: "100%",
    height: "100%",
  },
  logoLetter: {
    color: colors.primary,
    fontSize: 24,
    fontWeight: "900",
  },
  body: {
    flex: 1,
    gap: 2,
  },
  name: {
    color: colors.ink,
    fontSize: type.heading,
    fontWeight: "800",
  },
  slug: {
    color: colors.primary,
    fontSize: type.small,
    fontWeight: "700",
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 3,
  },
  meta: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    marginRight: spacing.sm,
  },
  productRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  stockPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  inStockPill: { backgroundColor: colors.successSoft },
  outOfStockPill: { backgroundColor: colors.dangerSoft },
  stockLabel: {
    fontSize: type.tiny,
    fontWeight: "800",
  },
  inStockLabel: { color: colors.success },
  outOfStockLabel: { color: colors.danger },
  priceLabel: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    fontWeight: "700",
  },
});
