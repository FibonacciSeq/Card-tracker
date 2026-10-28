import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  Modal,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQueryClient } from "@tanstack/react-query";

import { cancelReservation } from "../../api/client";
import { queryKeys, useGuestReservation, useShop } from "../../api/queries";
import type { Reservation, SavedReservation } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { PrimaryButton } from "../../components/PrimaryButton";
import { StatusPill } from "../../components/StatusPill";
import { formatDateTime, formatMoney, formatRemaining, titleCase } from "../../lib/format";
import { useNow } from "../../lib/useNow";
import { useReservations } from "../../state/reservations";
import { colors, radii, spacing, type } from "../../theme";

const ACTIVE = new Set(["REQUESTED", "CONFIRMED", "READY"]);

function shopInfo(reservation: SavedReservation | Reservation): {
  slug: string;
  name: string;
} {
  const shop = reservation.shop as { slug?: string; name?: string };
  return {
    slug: typeof shop.slug === "string" ? shop.slug : "",
    name: typeof shop.name === "string" ? shop.name : "Shop",
  };
}

export default function ReservationScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { get, getToken, hydrated, update } = useReservations();
  const saved = get(id);
  const [token, setToken] = useState<string | null>(null);
  const [tokenLoaded, setTokenLoaded] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const now = useNow();

  const info = saved ? shopInfo(saved) : null;
  const shopQuery = useShop(info?.slug ?? "");
  const reservationQuery = useGuestReservation(id, info?.slug ?? "", token);

  useEffect(() => {
    let active = true;
    getToken(id)
      .then((value) => {
        if (active) setToken(value);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setTokenLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [getToken, id]);

  useEffect(() => {
    if (!reservationQuery.data) return;
    const { access_token: _token, ...rest } = reservationQuery.data;
    update(id, rest);
  }, [id, reservationQuery.data, update]);

  if (!hydrated || !tokenLoaded) {
    return <LoadingState label="Loading reservation…" />;
  }

  if (!saved) {
    return (
      <EmptyState
        icon="receipt-outline"
        title="Reservation not found"
        body="This hold is not stored on this device. Guest holds are tied to the app that created them."
        actionLabel="Browse shops"
        onAction={() => router.replace("/")}
      />
    );
  }

  const reservation = reservationQuery.data ?? saved;
  const shop = shopQuery.data;
  const expiresAt = new Date(reservation.expires_at).getTime();
  const expired = Number.isFinite(expiresAt) && expiresAt <= now;
  const active = ACTIVE.has(reservation.status) && !expired;
  const payment = shop?.payment_instructions;
  const expiryText =
    reservation.status === "CANCELLED"
      ? "This hold was cancelled"
      : reservation.status === "EXPIRED"
        ? "This hold has expired"
        : reservation.status === "COMPLETED"
          ? "This hold was completed"
          : expired
            ? "This hold has expired"
            : `Collect within ${formatRemaining(reservation.expires_at, now)}`;
  const expiryIcon =
    reservation.status === "COMPLETED"
      ? "checkmark-circle-outline"
      : reservation.status === "CANCELLED" || expired
        ? "alert-circle-outline"
        : "time-outline";
  const expiryTone =
    reservation.status === "COMPLETED"
      ? colors.success
      : reservation.status === "CANCELLED" || expired
        ? colors.danger
        : colors.primary;

  async function cancel() {
    if (!token || !info) return;
    setCancelling(true);
    setCancelError(null);
    try {
      const updated = await cancelReservation(id, info.slug, token);
      const { access_token: _token, ...rest } = updated;
      update(id, rest);
      queryClient.setQueryData([...queryKeys.reservation(id), token], updated);
    } catch (error) {
      setCancelError(error instanceof Error ? error.message : "Could not cancel this hold.");
    } finally {
      setCancelling(false);
    }
  }


  async function share() {
    try {
      await Share.share({
        message: `My Card Tracker hold at ${info?.name ?? "the shop"}: #${reservation.public_ref}`,
      });
    } catch {
      // Sharing is optional; a dismissed or unsupported share sheet is not an error.
    }
  }

  return (
    <>
      <Stack.Screen options={{ title: `#${reservation.public_ref}` }} />
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.statusCard}>
          <View style={styles.statusTop}>
            <View style={styles.statusTitle}>
              <Text style={styles.eyebrow}>RESERVATION</Text>
              <Text style={styles.shopName}>{info?.name}</Text>
            </View>
            <StatusPill status={reservation.status} />
          </View>
          <Text style={styles.reference}>#{reservation.public_ref}</Text>
          <View style={styles.expiryRow}>
            <Ionicons name={expiryIcon} size={17} color={expiryTone} />
            <Text style={[styles.expiry, expiryTone === colors.danger && styles.expired]}>
              {expiryText}
            </Text>
          </View>
          {reservationQuery.isError ? (
            <Text style={styles.syncNote}>Showing the copy saved on this device.</Text>
          ) : null}
        </View>

        {active ? (
          <View style={styles.showCard}>
            <Ionicons name="storefront-outline" size={22} color={colors.primary} />
            <View style={styles.showText}>
              <Text style={styles.showTitle}>Show this reference at the shop</Text>
              <Text style={styles.showBody}>
                The shop will match your hold and prepare the cards for pickup.
              </Text>
            </View>
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Your cards</Text>
          <View style={styles.lines}>
            {reservation.lines.map((line) => (
              <View key={line.line_id} style={styles.line}>
                <View style={styles.lineBody}>
                  <Text style={styles.lineName}>{line.name}</Text>
                  <Text style={styles.lineMeta}>
                    {line.set_code.toUpperCase()} · #{line.collector_number} ·{" "}
                    {titleCase(line.finish)} · {line.condition} · {line.language.toUpperCase()}
                  </Text>
                </View>
                <View style={styles.lineNumbers}>
                  <Text style={styles.quantity}>×{line.quantity}</Text>
                  <Text style={styles.linePrice}>
                    {formatMoney({
                      amount_minor: line.unit_price.amount_minor * line.quantity,
                      currency: line.unit_price.currency,
                    })}
                  </Text>
                </View>
              </View>
            ))}
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.total}>{formatMoney(reservation.total)}</Text>
          </View>
        </View>

        {payment ? (
          <View style={styles.infoCard}>
            <Ionicons name="card-outline" size={19} color={colors.accent} />
            <View style={styles.infoText}>
              <Text style={styles.infoTitle}>Payment</Text>
              <Text style={styles.infoBody}>{payment}</Text>
            </View>
          </View>
        ) : null}

        <View style={styles.infoGrid}>
          <Info label="Placed" value={formatDateTime(reservation.created_at)} />
          <Info label="Expires" value={formatDateTime(reservation.expires_at)} />
        </View>

        {reservation.status === "READY" ? (
          <View style={styles.readyCard}>
            <Ionicons name="checkmark-circle-outline" size={22} color={colors.success} />
            <Text style={styles.readyText}>Your cards are ready. Head to the shop.</Text>
          </View>
        ) : null}

        {cancelError ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.errorText}>{cancelError}</Text>
          </View>
        ) : null}

        <View style={styles.actions}>
          <PrimaryButton label="Share reference" onPress={() => void share()} variant="secondary" />
          {active ? (
            <PrimaryButton
              label="Cancel this hold"
              loading={cancelling}
              onPress={() => setConfirmingCancel(true)}
              variant="danger"
            />
          ) : (
            <PrimaryButton
              label="Browse this shop"
              onPress={() => router.push(`/shop/${info?.slug ?? ""}`)}
              variant="secondary"
            />
          )}
        </View>

        {!token && !reservationQuery.isError ? (
          <Text style={styles.disclaimer}>
            This hold was saved without a guest token, so live updates are unavailable.
          </Text>
        ) : null}
      </ScrollView>

      <Modal
        animationType="fade"
        onRequestClose={() => setConfirmingCancel(false)}
        transparent
        visible={confirmingCancel}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <View style={styles.modalIcon}>
              <Ionicons name="alert-circle-outline" size={24} color={colors.danger} />
            </View>
            <Text style={styles.modalTitle}>Cancel this hold?</Text>
            <Text style={styles.modalBody}>
              The shop will release your cards. You can place a new hold later if they are still
              available.
            </Text>
            <PrimaryButton
              label="Keep my hold"
              onPress={() => setConfirmingCancel(false)}
              variant="secondary"
            />
            <PrimaryButton
              label="Cancel hold"
              loading={cancelling}
              onPress={() => {
                setConfirmingCancel(false);
                void cancel();
              }}
              variant="danger"
            />
          </View>
        </View>
      </Modal>
    </>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoCell}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  statusCard: {
    backgroundColor: colors.primary,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  statusTop: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  statusTitle: { flex: 1, gap: 3 },
  eyebrow: {
    color: "#D8E8E1",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  shopName: {
    color: colors.white,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  reference: {
    color: colors.white,
    fontSize: 30,
    fontWeight: "900",
    letterSpacing: 1.2,
    marginTop: spacing.sm,
  },
  expiryRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 },
  expiry: { color: "#D8E8E1", fontSize: type.small, fontWeight: "700" },
  expired: { color: "#FFD9D5" },
  syncNote: { color: "#D8E8E1", fontSize: type.tiny, fontStyle: "italic" },
  showCard: {
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "center",
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  showText: { flex: 1, gap: 2 },
  showTitle: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
  showBody: { color: colors.primary, fontSize: type.tiny, lineHeight: 17 },
  section: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  lines: { gap: spacing.md },
  line: {
    flexDirection: "row",
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: spacing.md,
  },
  lineBody: { flex: 1, gap: 2 },
  lineName: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
  lineMeta: { color: colors.inkMuted, fontSize: type.tiny, lineHeight: 16 },
  lineNumbers: { alignItems: "flex-end", gap: 2 },
  quantity: { color: colors.inkMuted, fontSize: type.small, fontWeight: "700" },
  linePrice: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  totalRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingTop: spacing.md,
  },
  totalLabel: { color: colors.inkMuted, fontSize: type.body, fontWeight: "700" },
  total: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  infoCard: {
    flexDirection: "row",
    gap: spacing.md,
    alignItems: "flex-start",
    backgroundColor: colors.accentSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  infoText: { flex: 1, gap: 2 },
  infoTitle: { color: colors.accent, fontSize: type.small, fontWeight: "800" },
  infoBody: { color: colors.ink, fontSize: type.small, lineHeight: 19 },
  infoGrid: { flexDirection: "row", gap: spacing.md },
  infoCell: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.md,
    gap: 3,
  },
  infoLabel: {
    color: colors.inkMuted,
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  infoValue: { color: colors.ink, fontSize: type.small, fontWeight: "700", lineHeight: 18 },
  readyCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.successSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  readyText: { flex: 1, color: colors.success, fontSize: type.small, fontWeight: "700" },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  actions: { gap: spacing.sm },

  modalOverlay: {
    flex: 1,
    backgroundColor: colors.overlay,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  modalCard: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  modalIcon: {
    width: 46,
    height: 46,
    borderRadius: 16,
    backgroundColor: colors.dangerSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  modalTitle: {
    color: colors.ink,
    fontSize: type.title,
    fontWeight: "900",
  },
  modalBody: {
    color: colors.inkMuted,
    fontSize: type.body,
    lineHeight: 22,
    marginBottom: spacing.sm,
  },
  disclaimer: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    lineHeight: 17,
    textAlign: "center",
  },
});
