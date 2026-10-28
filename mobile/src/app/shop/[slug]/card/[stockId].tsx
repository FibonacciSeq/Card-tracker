import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useShop, useStockItem } from "../../../../api/queries";
import type { StockItem } from "../../../../api/types";
import { CartBar } from "../../../../components/CartBar";
import { EmptyState } from "../../../../components/EmptyState";
import { LoadingState } from "../../../../components/LoadingState";
import { formatDateTime, formatMoney, titleCase } from "../../../../lib/format";
import { shopPath } from "../../../../lib/config";
import { useCart } from "../../../../state/cart";
import { colors, radii, shadow, spacing, type } from "../../../../theme";

export default function CardDetailScreen() {
  const { slug, stockId } = useLocalSearchParams<{ slug: string; stockId: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const cart = useCart();

  const shopQuery = useShop(slug);
  const itemQuery = useStockItem(slug, stockId);
  const item = itemQuery.data;
  const shop = shopQuery.data;
  const shopName = shop?.brand_name || shop?.name || "Shop";

  const quantity =
    cart.linesFor(slug).find((line) => line.stockId === stockId)?.quantity ?? 0;
  const cartCount = cart.countFor(slug);
  const cartTotal = cart.totalFor(slug);

  if (itemQuery.isLoading) {
    return (
      <View style={styles.screen}>
        <Stack.Screen options={{ title: "Card" }} />
        <LoadingState label="Looking up this card…" />
      </View>
    );
  }

  if (itemQuery.isError || !item) {
    const notFound = (itemQuery.error as { status?: number } | null)?.status === 404;
    return (
      <View style={styles.screen}>
        <Stack.Screen options={{ title: "Card" }} />
        <EmptyState
          icon="albums-outline"
          title={notFound ? "Card not listed" : "Could not load this card"}
          body={
            notFound
              ? "The shop may have sold or removed this variant. Scan the code again if it just went back on the shelf."
              : "Check your connection and try again."
          }
          actionLabel={notFound ? `Browse ${shopName}` : "Try again"}
          onAction={() => {
            if (notFound) router.replace(shopPath(slug));
            else void itemQuery.refetch();
          }}
        />
      </View>
    );
  }

  const soldOut = item.available <= 0;

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: item.card.name }} />
      <ScrollView
        contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
        refreshControl={
          <RefreshControl
            refreshing={itemQuery.isRefetching}
            onRefresh={() => {
              void itemQuery.refetch();
              void shopQuery.refetch();
            }}
            tintColor={colors.primary}
          />
        }
      >
        <CardHero item={item} shopName={shopName} />

        <View style={styles.body}>
          <View style={styles.priceRow}>
            <View>
              <Text style={styles.kicker}>PRICE</Text>
              <Text style={styles.price}>{formatMoney(item.price)}</Text>
            </View>
            <View style={[styles.stockPill, soldOut && styles.stockPillOff]}>
              <Ionicons
                name={soldOut ? "close-circle-outline" : "checkmark-circle-outline"}
                size={15}
                color={soldOut ? colors.inkMuted : colors.success}
              />
              <Text style={[styles.stockText, soldOut && styles.stockTextOff]}>
                {soldOut ? "Sold out" : `${item.available} available`}
              </Text>
            </View>
          </View>

          <View style={styles.addPanel}>
            <Text style={styles.addTitle}>Put it on hold</Text>
            <Text style={styles.addBody}>
              {soldOut
                ? "This variant is not on the shelf right now."
                : `Reserve it now and collect it at ${shopName}. The shop keeps it aside for ${shop?.hold_hours ?? 24} hours.`}
            </Text>

            {soldOut ? (
              <View style={styles.soldOutBox}>
                <Ionicons name="information-circle-outline" size={18} color={colors.inkMuted} />
                <Text style={styles.soldOutText}>
                  Ask the shop when this variant is coming back.
                </Text>
              </View>
            ) : quantity > 0 ? (
              <View style={styles.stepperRow}>
                <View style={styles.stepper}>
                  <Pressable
                    accessibilityLabel={`Remove one ${item.card.name}`}
                    accessibilityRole="button"
                    hitSlop={6}
                    onPress={() => cart.setQuantity(slug, item.stock_id, quantity - 1)}
                    style={styles.stepButton}
                  >
                    <Ionicons name="remove" size={18} color={colors.primary} />
                  </Pressable>
                  <Text style={styles.quantity}>{quantity}</Text>
                  <Pressable
                    accessibilityLabel={`Add another ${item.card.name}`}
                    accessibilityRole="button"
                    disabled={quantity >= item.available}
                    hitSlop={6}
                    onPress={() => cart.setQuantity(slug, item.stock_id, quantity + 1)}
                    style={[
                      styles.stepButton,
                      quantity >= item.available && styles.stepDisabled,
                    ]}
                  >
                    <Ionicons name="add" size={18} color={colors.primary} />
                  </Pressable>
                </View>
                <Text style={styles.stepHint}>
                  {quantity >= item.available
                    ? "That is every copy this shop has listed."
                    : "In your hold"}
                </Text>
              </View>
            ) : (
              <Pressable
                accessibilityLabel={`Add ${item.card.name} to your hold`}
                accessibilityRole="button"
                onPress={() => cart.add(slug, item)}
                style={({ pressed }) => [styles.addButton, pressed && styles.pressed]}
              >
                <Ionicons name="add" size={18} color={colors.white} />
                <Text style={styles.addLabel}>Add to hold</Text>
              </Pressable>
            )}
          </View>

          <Details item={item} />

          <Pressable
            accessibilityLabel={`See everything at ${shopName}`}
            accessibilityRole="link"
            onPress={() => router.push(shopPath(slug))}
            style={({ pressed }) => [styles.shopLink, pressed && styles.pressed]}
          >
            <Ionicons name="storefront-outline" size={18} color={colors.primary} />
            <View style={styles.shopLinkText}>
              <Text style={styles.shopLinkTitle}>See everything at {shopName}</Text>
              <Text style={styles.shopLinkBody}>@{slug}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.inkMuted} />
          </Pressable>
        </View>
      </ScrollView>

      {cartCount > 0 ? (
        <CartBar
          count={cartCount}
          total={cartTotal}
          bottomInset={insets.bottom}
          onPress={() => router.push(`/shop/${slug}/cart`)}
        />
      ) : null}
    </View>
  );
}

function CardHero({ item, shopName }: { item: StockItem; shopName: string }) {
  const image =
    item.card.image_large ?? item.card.image_normal ?? item.card.image_small ?? null;
  return (
    <View style={styles.hero}>
      <View style={styles.imageWrap}>
        {image ? (
          <Image source={{ uri: image }} style={styles.image} contentFit="contain" transition={150} />
        ) : (
          <View style={styles.imageFallback}>
            <Ionicons name="albums-outline" size={44} color={colors.inkMuted} />
          </View>
        )}
      </View>

      <View style={styles.heroBody}>
        <Text style={styles.cardName}>{item.card.name}</Text>
        <Text style={styles.setLine}>
          {item.card.set_name} · {item.card.set_code.toUpperCase()} #{item.card.collector_number}
        </Text>
        {item.card.type_line ? (
          <Text style={styles.typeLine}>{item.card.type_line}</Text>
        ) : null}
        <View style={styles.badgeRow}>
          <Text style={styles.badge}>{titleCase(item.finish)}</Text>
          <Text style={styles.badge}>{item.condition}</Text>
          <Text style={styles.badge}>{item.language.toUpperCase()}</Text>
          <Text style={styles.badge}>{titleCase(item.card.rarity)}</Text>
        </View>
        <Text style={styles.atShop}>At {shopName}</Text>
      </View>
    </View>
  );
}

function Details({ item }: { item: StockItem }) {
  return (
    <View style={styles.details}>
      <DetailRow label="Set" value={`${item.card.set_name} (${item.card.set_code.toUpperCase()})`} />
      <DetailRow label="Collector number" value={`#${item.card.collector_number}`} />
      <DetailRow label="Rarity" value={titleCase(item.card.rarity)} />
      <DetailRow label="Finish" value={titleCase(item.finish)} />
      <DetailRow label="Condition" value={item.condition} />
      <DetailRow label="Language" value={item.language.toUpperCase()} />
      <DetailRow label="Last updated" value={formatDateTime(item.updated_at)} last />
    </View>
  );
}

function DetailRow({ label, value, last }: { label: string; value: string; last?: boolean }) {
  return (
    <View style={[styles.detailRow, last && styles.detailRowLast]}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  hero: { padding: spacing.lg, gap: spacing.lg },
  imageWrap: {
    height: 340,
    borderRadius: radii.lg,
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1,
    borderColor: colors.line,
    overflow: "hidden",
    ...shadow.card,
  },
  image: { width: "100%", height: "100%" },
  imageFallback: { flex: 1, alignItems: "center", justifyContent: "center" },
  heroBody: { gap: 4 },
  cardName: {
    color: colors.ink,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  setLine: { color: colors.inkMuted, fontSize: type.small, fontWeight: "600" },
  typeLine: { color: colors.inkMuted, fontSize: type.small },
  badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: spacing.xs },
  badge: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    color: colors.inkMuted,
    fontSize: 10,
    fontWeight: "800",
    borderRadius: radii.pill,
    paddingHorizontal: 8,
    paddingVertical: 2,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  atShop: { color: colors.primary, fontSize: type.small, fontWeight: "700", marginTop: spacing.xs },
  body: { paddingHorizontal: spacing.lg, gap: spacing.lg },
  priceRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
  },
  kicker: {
    color: colors.inkMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  price: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  stockPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.successSoft,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  stockPillOff: { backgroundColor: colors.surfaceMuted },
  stockText: { color: colors.success, fontSize: type.small, fontWeight: "800" },
  stockTextOff: { color: colors.inkMuted },
  addPanel: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  addTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  addBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  addButton: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: colors.primary,
  },
  addLabel: { color: colors.white, fontSize: type.body, fontWeight: "800" },
  pressed: { opacity: 0.85 },
  soldOutBox: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  soldOutText: { flex: 1, color: colors.inkMuted, fontSize: type.small },
  stepperRow: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  stepper: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.pill,
    backgroundColor: colors.background,
    overflow: "hidden",
  },
  stepButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  stepDisabled: { opacity: 0.35 },
  quantity: {
    minWidth: 26,
    textAlign: "center",
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "800",
  },
  stepHint: { flex: 1, color: colors.inkMuted, fontSize: type.tiny },
  details: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    paddingHorizontal: spacing.lg,
  },
  detailRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  },
  detailRowLast: { borderBottomWidth: 0 },
  detailLabel: { color: colors.inkMuted, fontSize: type.small },
  detailValue: {
    flex: 1,
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "700",
    textAlign: "right",
  },
  shopLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.lg,
    padding: spacing.lg,
  },
  shopLinkText: { flex: 1, gap: 2 },
  shopLinkTitle: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
  shopLinkBody: { color: colors.primary, fontSize: type.tiny, opacity: 0.8 },
  specialOrder: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.accentSoft,
    borderRadius: radii.lg,
    padding: spacing.lg,
  },
  specialOrderIcon: {
    width: 38,
    height: 38,
    borderRadius: 13,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  specialOrderText: { flex: 1, gap: 2 },
  specialOrderTitle: { color: colors.accent, fontSize: type.small, fontWeight: "800" },
  specialOrderBody: { color: colors.ink, fontSize: type.tiny, lineHeight: 17 },
});
