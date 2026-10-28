import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_BASE_URL, shopPath } from "../lib/config";
import { useDebouncedValue, useShops } from "../api/queries";
import { EmptyState } from "../components/EmptyState";
import { HoldCard } from "../components/HoldCard";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SearchField } from "../components/SearchField";
import { ShopCard } from "../components/ShopCard";
import { useReservations } from "../state/reservations";
import { colors, radii, spacing, type } from "../theme";

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const shops = useShops(debouncedSearch);
  const { hydrated, reservations } = useReservations();

  const hasNoShops = shops.isSuccess && shops.data.length === 0;

  return (
    <View style={styles.screen}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={shops.isRefetching}
            onRefresh={() => void shops.refetch()}
            tintColor={colors.primary}
          />
        }
      >
        <View style={[styles.hero, { paddingTop: insets.top + spacing.xl }]}>
          <View style={styles.brand}>
            <View style={styles.brandMark}>
              <Ionicons name="diamond-outline" size={15} color={colors.primary} />
            </View>
            <Text style={styles.brandText}>CARD TRACKER</Text>
          </View>
          <Text style={styles.title}>Find the card you need.</Text>
          <Text style={styles.subtitle}>
            Browse local card shops, put a card on hold, and collect it in store.
          </Text>
        </View>

        <View style={styles.content}>
          <SearchField
            value={search}
            onChangeText={setSearch}
            placeholder="Search shops by name"
          />

          {hydrated && reservations.length > 0 ? (
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Your holds</Text>
                <Text style={styles.sectionCount}>{reservations.length}</Text>
              </View>
              <View style={styles.holdList}>
                {reservations.map((reservation) => (
                  <HoldCard
                    key={reservation.id}
                    reservation={reservation}
                    onPress={() => router.push(`/reservation/${reservation.id}`)}
                  />
                ))}
              </View>
            </View>
          ) : null}

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Shops on Card Tracker</Text>
              {shops.isFetching ? (
                <Text style={styles.sectionCount}>Updating…</Text>
              ) : null}
            </View>

            {shops.isLoading ? <LoadingState label="Finding shops…" /> : null}

            {shops.isError ? (
              <ErrorState
                message={
                  "We could not reach the shop directory. Check that the API is running and try again."
                }
                onRetry={() => void shops.refetch()}
              />
            ) : null}

            {hasNoShops ? (
              <EmptyState
                icon="storefront-outline"
                title={debouncedSearch ? "No matching shops" : "No shops yet"}
                body={
                  debouncedSearch
                    ? "Try a different shop name or clear the search."
                    : "Start the demo API and seed a shop, then pull to refresh."
                }
                actionLabel={debouncedSearch ? "Clear search" : "Try again"}
                onAction={() => {
                  if (debouncedSearch) setSearch("");
                  else void shops.refetch();
                }}
              />
            ) : null}

            <View style={styles.shopList}>
              {shops.data?.map((shop) => (
                <ShopCard
                  key={shop.slug}
                  shop={shop}
                  onPress={() => router.push(shopPath(shop.slug))}
                />
              ))}
            </View>
          </View>

          <View style={styles.howItWorks}>
            <Text style={styles.howTitle}>How holds work</Text>
            <View style={styles.steps}>
              <Step icon="search-outline" number="01" label="Find your card" />
              <Step icon="bag-handle-outline" number="02" label="Request a hold" />
              <Step icon="storefront-outline" number="03" label="Pick up in store" />
            </View>
          </View>

          {__DEV__ ? <Text style={styles.devHint}>API: {API_BASE_URL}</Text> : null}
        </View>
      </ScrollView>
    </View>
  );
}

function Step({
  icon,
  number,
  label,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  number: string;
  label: string;
}) {
  return (
    <View style={styles.step}>
      <View style={styles.stepIcon}>
        <Ionicons name={icon} size={18} color={colors.primary} />
      </View>
      <Text style={styles.stepNumber}>{number}</Text>
      <Text style={styles.stepLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  hero: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  brand: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  brandMark: {
    width: 28,
    height: 28,
    borderRadius: 9,
    backgroundColor: colors.white,
    alignItems: "center",
    justifyContent: "center",
  },
  brandText: {
    color: colors.white,
    fontSize: type.tiny,
    fontWeight: "900",
    letterSpacing: 1.5,
  },
  title: {
    color: colors.white,
    fontSize: type.display,
    fontWeight: "900",
    letterSpacing: -0.8,
    marginTop: spacing.xl,
    maxWidth: 300,
  },
  subtitle: {
    color: "#D8E8E1",
    fontSize: type.body,
    lineHeight: 22,
    marginTop: spacing.sm,
    maxWidth: 330,
  },
  content: {
    paddingHorizontal: spacing.lg,
    marginTop: spacing.lg,
    gap: spacing.xl,
  },
  section: { gap: spacing.md },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sectionTitle: {
    color: colors.ink,
    fontSize: type.heading,
    fontWeight: "900",
  },
  sectionCount: {
    color: colors.inkMuted,
    fontSize: type.small,
    fontWeight: "700",
  },
  shopList: { gap: spacing.md },
  holdList: { gap: spacing.sm },
  howItWorks: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
  },
  howTitle: {
    color: colors.ink,
    fontSize: type.body,
    fontWeight: "900",
    marginBottom: spacing.md,
  },
  steps: { flexDirection: "row", gap: spacing.sm },
  step: { flex: 1, gap: 4 },
  stepIcon: {
    width: 34,
    height: 34,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  stepNumber: {
    color: colors.accent,
    fontSize: type.tiny,
    fontWeight: "900",
    marginTop: 2,
  },
  stepLabel: {
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "700",
    lineHeight: 17,
  },
  devHint: {
    color: colors.inkMuted,
    fontSize: 10,
    textAlign: "center",
    marginTop: spacing.sm,
  },
});
