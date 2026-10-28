import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Shop } from "../api/types";
import { colors, radii, shadow, spacing, type } from "../theme";

export function ShopCard({ shop, onPress }: { shop: Shop; onPress: () => void }) {
  const name = shop.brand_name || shop.name;
  return (
    <Pressable
      accessibilityHint="Opens this shop's storefront"
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
          <Ionicons name="location-outline" size={13} color={colors.inkMuted} />
          <Text numberOfLines={1} style={styles.meta}>
            {shop.timezone.replace(/_/g, " ")}
          </Text>
        </View>
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
});
