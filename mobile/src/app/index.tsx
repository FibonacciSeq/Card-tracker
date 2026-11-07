import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import { RefreshControl, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  accountKeys,
  useDebouncedValue,
  useMyCardRequests,
  useMyReservations,
  useMyRestockAlerts,
  useShops,
} from "../api/queries";
import { EmptyState } from "../components/EmptyState";
import { HoldCard } from "../components/HoldCard";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { RequestCard } from "../components/RequestCard";
import { SearchField } from "../components/SearchField";
import { ShopCard } from "../components/ShopCard";
import { mergeCardRequests, mergeReservations, mergeRestockAlerts } from "../lib/accountMerge";
import { API_BASE_URL, shopPath } from "../lib/config";
import { useLocale } from "../state/locale";
import { useAuth } from "../state/auth";
import { useReservations } from "../state/reservations";
import { useRestockAlerts } from "../state/restockAlerts";
import { useSpecialOrders } from "../state/specialOrders";
import { colors, radii, spacing, type } from "../theme";

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { t } = useLocale();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const shops = useShops(debouncedSearch);
  const { customer, isAuthenticated, token } = useAuth();
  const { hydrated, reservations } = useReservations();
  const { hydrated: alertsHydrated, alerts } = useRestockAlerts();
  const { hydrated: requestsHydrated, requests } = useSpecialOrders();
  const accountReservations = useMyReservations(token);
  const accountRequests = useMyCardRequests(token);
  const accountAlerts = useMyRestockAlerts(token);

  // Never render cached account rows while the session is absent. The query
  // cache can hold the last signed-in account across a restart; the guest
  // stores are the only rows that belong to a signed-out device.
  const accountReservationRows = isAuthenticated
    ? (accountReservations.data?.items ?? [])
    : [];
  const accountRequestRows = isAuthenticated ? (accountRequests.data?.items ?? []) : [];
  const accountAlertRows = isAuthenticated ? (accountAlerts.data?.items ?? []) : [];
  const allReservations = mergeReservations(accountReservationRows, reservations);
  const allRequests = mergeCardRequests(accountRequestRows, requests);
  const allAlerts = mergeRestockAlerts(accountAlertRows, alerts);
  const accountRefreshing =
    accountReservations.isRefetching ||
    accountRequests.isRefetching ||
    accountAlerts.isRefetching;
  const listsHydrated = hydrated && requestsHydrated && alertsHydrated;

  const hasNoShops = shops.isSuccess && shops.data.length === 0;

  async function refresh() {
    await Promise.all([
      shops.refetch(),
      queryClient.invalidateQueries({ queryKey: accountKeys.all }),
    ]);
  }

  return (
    <View style={styles.screen}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={shops.isRefetching || accountRefreshing}
            onRefresh={() => void refresh()}
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
          <Text style={styles.title}>{t("homeTitle")}</Text>
          <Text style={styles.subtitle}>{t("homeSubtitle")}</Text>
          <Pressable
            accessibilityHint="Opens your account and sign-in options"
            accessibilityLabel={isAuthenticated ? "Your account" : "Sign in to sync your list"}
            accessibilityRole="button"
            onPress={() => router.push("/account")}
            style={({ pressed }) => [styles.accountBar, pressed && styles.scanPressed]}
          >
            <Ionicons
              name={isAuthenticated ? "person-circle" : "person-circle-outline"}
              size={22}
              color={colors.white}
            />
            <View style={styles.accountText}>
              <Text numberOfLines={1} style={styles.accountTitle}>
                {isAuthenticated ? customer?.email : t("signInToSync")}
              </Text>
              <Text style={styles.accountSubtitle}>
                {isAuthenticated
                  ? "Holds, alerts, and requests across devices"
                  : "Optional — guest checkout still works"}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color="#D8E8E1" />
          </Pressable>
          <Pressable
            accessibilityHint="Opens the camera to scan a QR code at a shop"
            accessibilityLabel="Scan a shop code"
            accessibilityRole="button"
            onPress={() => router.push("/scan")}
            style={({ pressed }) => [styles.scanButton, pressed && styles.scanPressed]}
          >
            <Ionicons name="qr-code-outline" size={18} color={colors.primary} />
            <Text style={styles.scanLabel}>{t("scanShopCode")}</Text>
          </Pressable>
        </View>

        <View style={styles.content}>
          <SearchField
            value={search}
            onChangeText={setSearch}
            placeholder="Search shops by name"
          />

          <View style={styles.quickRow}>
            <QuickAction
              count={listsHydrated ? allRequests.length : 0}
              icon="sparkles-outline"
              label={t("specialOrders")}
              onPress={() => router.push("/requests")}
            />
            <QuickAction
              count={listsHydrated ? allAlerts.length : 0}
              icon="notifications-outline"
              label={t("restockAlerts")}
              onPress={() => router.push("/alerts")}
            />
          </View>

          {listsHydrated && allReservations.length > 0 ? (
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>{t("yourHolds")}</Text>
                <Text style={styles.sectionCount}>{allReservations.length}</Text>
              </View>
              <View style={styles.holdList}>
                {allReservations.map((reservation) => (
                  <HoldCard
                    key={reservation.id}
                    reservation={reservation}
                    onPress={() => router.push(`/reservation/${reservation.id}`)}
                  />
                ))}
              </View>
            </View>
          ) : null}

          {listsHydrated && allRequests.length > 0 ? (
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Your special orders</Text>
                <Text style={styles.sectionCount}>{allRequests.length}</Text>
              </View>
              <View style={styles.holdList}>
                {allRequests.slice(0, 3).map((request) => (
                  <RequestCard
                    key={request.id}
                    request={request}
                    onPress={() => router.push(`/requests/${request.id}`)}
                  />
                ))}
              </View>
              {allRequests.length > 3 ? (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => router.push("/requests")}
                  style={({ pressed }) => [styles.seeAll, pressed && styles.scanPressed]}
                >
                  <Text style={styles.seeAllLabel}>See all {allRequests.length} requests</Text>
                  <Ionicons name="arrow-forward" size={16} color={colors.primary} />
                </Pressable>
              ) : null}
            </View>
          ) : null}

          <View style={styles.section}>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>{t("shopsOnCardTracker")}</Text>
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

function QuickAction({
  count,
  icon,
  label,
  onPress,
}: {
  count: number;
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityLabel={`${label}${count ? `, ${count} saved` : ""}`}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.quickCard, pressed && styles.scanPressed]}
    >
      <View style={styles.quickIcon}>
        <Ionicons name={icon} size={17} color={colors.primary} />
      </View>
      <View style={styles.quickText}>
        <Text style={styles.quickLabel}>{label}</Text>
        <Text style={styles.quickCount}>{count === 0 ? "None yet" : `${count} saved`}</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={colors.inkMuted} />
    </Pressable>
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
  accountBar: {
    marginTop: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "rgba(255,255,255,0.12)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.2)",
    borderRadius: radii.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  accountText: { flex: 1, gap: 1 },
  accountTitle: { color: colors.white, fontSize: type.small, fontWeight: "800" },
  accountSubtitle: { color: "#D8E8E1", fontSize: type.tiny },
  scanButton: {
    marginTop: spacing.sm,
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.white,
    borderRadius: 999,
    paddingHorizontal: spacing.lg,
    paddingVertical: 11,
  },
  scanPressed: { opacity: 0.85 },
  scanLabel: {
    color: colors.primary,
    fontSize: type.small,
    fontWeight: "800",
  },
  content: {
    paddingHorizontal: spacing.lg,
    marginTop: spacing.lg,
    gap: spacing.xl,
  },
  quickRow: { flexDirection: "row", gap: spacing.sm },
  quickCard: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
  },
  quickIcon: {
    width: 34,
    height: 34,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
  },
  quickText: { flex: 1, gap: 1 },
  quickLabel: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  quickCount: { color: colors.inkMuted, fontSize: type.tiny },
  seeAll: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    minHeight: 40,
  },
  seeAllLabel: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
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
