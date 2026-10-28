import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useStock, useShop, useDebouncedValue } from "../../../api/queries";
import type { StockItem, StockSort } from "../../../api/types";
import { CartBar } from "../../../components/CartBar";
import { EmptyState } from "../../../components/EmptyState";
import { ErrorState, LoadingState } from "../../../components/LoadingState";
import { SearchField } from "../../../components/SearchField";
import { SortBar } from "../../../components/SortBar";
import { StockCard } from "../../../components/StockCard";
import { useCart } from "../../../state/cart";
import { colors, radii, spacing, type } from "../../../theme";

export default function ShopScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<StockSort>("relevance");
  const [availableOnly, setAvailableOnly] = useState(false);
  const debouncedSearch = useDebouncedValue(search);

  const shopQuery = useShop(slug);
  const stockQuery = useStock(slug, debouncedSearch, sort, availableOnly);
  const cart = useCart();

  const shop = shopQuery.data;
  const items = stockQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const cartLines = cart.linesFor(slug);
  const cartCount = cart.countFor(slug);
  const cartTotal = cart.totalFor(slug);

  const title = shop?.brand_name || shop?.name || "Shop";

  return (
    <>
      <Stack.Screen options={{ title }} />
      <View style={styles.screen}>
        <FlatList
          data={items}
          keyExtractor={(item) => item.stock_id}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          onEndReached={() => {
            if (stockQuery.hasNextPage && !stockQuery.isFetchingNextPage) {
              void stockQuery.fetchNextPage();
            }
          }}
          onEndReachedThreshold={0.35}
          refreshControl={
            <RefreshControl
              refreshing={stockQuery.isRefetching && !stockQuery.isFetchingNextPage}
              onRefresh={() => {
                void shopQuery.refetch();
                void stockQuery.refetch();
              }}
              tintColor={colors.primary}
            />
          }
          ListHeaderComponent={
            <View>
              {shop ? <ShopHero shop={shop} /> : shopQuery.isLoading ? <LoadingState label="Opening shop…" /> : null}
              {shopQuery.isError ? (
                <View style={styles.pad}>
                  <ErrorState
                    message="We could not load this shop."
                    onRetry={() => void shopQuery.refetch()}
                  />
                </View>
              ) : null}

              <View style={styles.controls}>
                <SearchField
                  value={search}
                  onChangeText={setSearch}
                  placeholder={`Search ${title}`}
                />
                <SortBar
                  value={sort}
                  onChange={setSort}
                  availableOnly={availableOnly}
                  onToggleAvailable={() => setAvailableOnly((value) => !value)}
                />
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>
                    {stockQuery.isLoading
                      ? "Looking for cards…"
                      : `${items.length}${stockQuery.hasNextPage ? "+" : ""} card${items.length === 1 ? "" : "s"}`}
                  </Text>
                  {stockQuery.isFetching && !stockQuery.isLoading ? (
                    <ActivityIndicator size="small" color={colors.inkMuted} />
                  ) : null}
                </View>
              </View>
            </View>
          }
          renderItem={({ item }) => (
            <StockRow
              item={item}
              quantity={cartLines.find((line) => line.stockId === item.stock_id)?.quantity ?? 0}
              onAdd={() => cart.add(slug, item)}
              onIncrease={() => {
                const line = cartLines.find((entry) => entry.stockId === item.stock_id);
                cart.setQuantity(slug, item.stock_id, (line?.quantity ?? 0) + 1);
              }}
              onDecrease={() => {
                const line = cartLines.find((entry) => entry.stockId === item.stock_id);
                cart.setQuantity(slug, item.stock_id, (line?.quantity ?? 0) - 1);
              }}
            />
          )}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          ListEmptyComponent={
            stockQuery.isLoading ? (
              <LoadingState label="Finding cards…" />
            ) : stockQuery.isError ? (
              <ErrorState
                message={
                  stockQuery.error instanceof Error
                    ? stockQuery.error.message
                    : "We could not load this shop's stock."
                }
                onRetry={() => void stockQuery.refetch()}
              />
            ) : (
              <EmptyState
                icon="search-outline"
                title="No cards found"
                body={
                  debouncedSearch || availableOnly
                    ? "Try another search, or turn off the availability filter."
                    : "This shop has no cards listed right now."
                }
                actionLabel={search || availableOnly ? "Clear filters" : undefined}
                onAction={() => {
                  setSearch("");
                  setAvailableOnly(false);
                }}
              />
            )
          }
          ListFooterComponent={
            <View>
              {stockQuery.isFetchingNextPage ? (
                <ActivityIndicator color={colors.primary} style={styles.footerSpinner} />
              ) : null}
              {!stockQuery.hasNextPage && items.length > 0 ? (
                <Text style={styles.endLabel}>That’s the whole shelf.</Text>
              ) : null}
            </View>
          }
        />

        {cartCount > 0 ? (
          <CartBar
            count={cartCount}
            total={cartTotal}
            bottomInset={insets.bottom}
            onPress={() => router.push(`/shop/${slug}/cart`)}
          />
        ) : null}
      </View>
    </>
  );
}

function ShopHero({ shop }: { shop: NonNullable<ReturnType<typeof useShop>["data"]> }) {
  const contact = shop.contact as { email?: string; phone?: string };
  const name = shop.brand_name || shop.name;
  return (
    <View style={styles.hero}>
      <View style={styles.heroTop}>
        <View style={styles.shopLogo}>
          {shop.logo_url ? (
            <Image source={{ uri: shop.logo_url }} style={styles.shopLogoImage} contentFit="cover" />
          ) : (
            <Text style={styles.shopLogoLetter}>{name.slice(0, 1).toUpperCase()}</Text>
          )}
        </View>
        <View style={styles.heroText}>
          <Text style={styles.kicker}>LOCAL CARD SHOP</Text>
          <Text style={styles.shopName}>{name}</Text>
          <Text style={styles.shopSlug}>@{shop.slug}</Text>
        </View>
      </View>
      <View style={styles.heroMeta}>
        <Meta icon="time-outline" text={`${shop.hold_hours}h holds`} />
        <Meta icon="pricetag-outline" text={shop.currency} />
        {contact.email ? <Meta icon="mail-outline" text={contact.email} /> : null}
      </View>
      {shop.payment_instructions ? (
        <View style={styles.payment}>
          <Ionicons name="card-outline" size={15} color={colors.primary} />
          <Text style={styles.paymentText}>{shop.payment_instructions}</Text>
        </View>
      ) : null}
    </View>
  );
}

function Meta({ icon, text }: { icon: keyof typeof Ionicons.glyphMap; text: string }) {
  return (
    <View style={styles.meta}>
      <Ionicons name={icon} size={13} color={colors.inkMuted} />
      <Text numberOfLines={1} style={styles.metaText}>
        {text}
      </Text>
    </View>
  );
}

function StockRow({
  item,
  quantity,
  onAdd,
  onIncrease,
  onDecrease,
}: {
  item: StockItem;
  quantity: number;
  onAdd: () => void;
  onIncrease: () => void;
  onDecrease: () => void;
}) {
  return (
    <View style={styles.row}>
      <StockCard
        item={item}
        quantity={quantity}
        onAdd={onAdd}
        onIncrease={onIncrease}
        onDecrease={onDecrease}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  hero: {
    margin: spacing.lg,
    marginBottom: spacing.md,
    borderRadius: radii.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  heroTop: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  shopLogo: {
    width: 64,
    height: 64,
    borderRadius: 18,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  shopLogoImage: { width: "100%", height: "100%" },
  shopLogoLetter: { color: colors.primary, fontSize: 28, fontWeight: "900" },
  heroText: { flex: 1, gap: 2 },
  kicker: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  shopName: {
    color: colors.ink,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  shopSlug: { color: colors.primary, fontSize: type.small, fontWeight: "700" },
  heroMeta: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  meta: { flexDirection: "row", alignItems: "center", gap: 4, maxWidth: "100%" },
  metaText: { color: colors.inkMuted, fontSize: type.tiny },
  payment: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  paymentText: { flex: 1, color: colors.primary, fontSize: type.small, lineHeight: 18 },
  pad: { paddingHorizontal: spacing.lg },
  controls: { paddingHorizontal: spacing.lg, gap: spacing.sm },
  resultRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  resultLabel: { color: colors.inkMuted, fontSize: type.small, fontWeight: "700" },
  row: { paddingHorizontal: spacing.lg },
  separator: { height: spacing.md },
  footerSpinner: { paddingVertical: spacing.xl },
  endLabel: {
    color: colors.inkMuted,
    fontSize: type.small,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },
});
