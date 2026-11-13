import { Ionicons } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Modal, RefreshControl, ScrollView, Share, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useQueryClient } from "@tanstack/react-query";

import {
  acceptCardRequest,
  acceptMyCardRequest,
  cancelCardRequest,
  cancelMyCardRequest,
} from "../../api/client";
import {
  accountKeys,
  queryKeys,
  useGuestCardRequest,
  useMyCardRequest,
} from "../../api/queries";
import type { AccountCardRequest, CardRequest } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { PrimaryButton } from "../../components/PrimaryButton";
import { StatusPill } from "../../components/StatusPill";
import { readShop } from "../../lib/accountMerge";
import { formatDateTime, formatMoney, formatRemaining, titleCase } from "../../lib/format";
import { useNow } from "../../lib/useNow";
import { useAuth } from "../../state/auth";
import { useSpecialOrders } from "../../state/specialOrders";
import { colors, radii, spacing, type } from "../../theme";

// UI-only copy of the backend CARD_REQUEST_ACTIVE_STATUSES tuple; the API
// serializes status as a plain string.
const ACTIVE = new Set(["REQUESTED", "QUOTED", "ACCEPTED"]);

export default function RequestScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { get, getToken, hydrated, update } = useSpecialOrders();
  const { isAuthenticated, token: accountToken } = useAuth();
  const saved = get(id);
  const [token, setToken] = useState<string | null>(null);
  const [tokenLoaded, setTokenLoaded] = useState(false);
  const [acting, setActing] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const now = useNow();

  const accountQuery = useMyCardRequest(id, accountToken);
  const accountRequest = isAuthenticated ? accountQuery.data : undefined;
  const requestQuery = useGuestCardRequest(id, saved?.shopSlug ?? "", token);
  const accountShop = accountRequest ? readShop(accountRequest.shop) : null;
  const shopName = accountShop?.name ?? saved?.shopName ?? "Shop";
  const shopSlug = accountShop?.slug ?? saved?.shopSlug ?? "";

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
    if (!requestQuery.data) return;
    const { access_token: _accessToken, ...rest } = requestQuery.data;
    update(id, rest);
  }, [id, requestQuery.data, update]);

  if (!hydrated || !tokenLoaded || (accountToken && accountQuery.isLoading)) {
    return <LoadingState label="Loading special order…" />;
  }

  if (!saved && !accountRequest) {
    return (
      <EmptyState
        icon="sparkles-outline"
        title="Request not found"
        body="This special order is not stored on this device or linked to your signed-in email."
        actionLabel="My requests"
        onAction={() => router.replace("/requests")}
      />
    );
  }

  const request: CardRequest | AccountCardRequest =
    accountRequest ?? requestQuery.data ?? saved!;
  const quoteExpiresAt = request.quote_expires_at
    ? new Date(request.quote_expires_at).getTime()
    : null;
  const quoteExpired = quoteExpiresAt !== null && quoteExpiresAt <= now;
  const canAccept = request.status === "QUOTED" && !quoteExpired;
  const canCancel = ACTIVE.has(request.status);

  async function accept() {
    setActing(true);
    setActionError(null);
    try {
      if (accountRequest && accountToken) {
        const updated = await acceptMyCardRequest(id, accountToken);
        queryClient.setQueryData(accountKeys.cardRequest(id), updated);
        await queryClient.invalidateQueries({ queryKey: accountKeys.cardRequests });
        if (saved) {
          const { access_token: _accessToken, ...rest } = updated;
          update(id, rest);
        }
      } else {
        if (!token || !saved) return;
        const updated = await acceptCardRequest(id, saved.shopSlug, token);
        const { access_token: _accessToken, ...rest } = updated;
        update(id, rest);
        queryClient.setQueryData([...queryKeys.cardRequest(id), token], updated);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not accept this quote.");
      void (accountRequest ? accountQuery.refetch() : requestQuery.refetch());
    } finally {
      setActing(false);
    }
  }

  async function cancel() {
    setActing(true);
    setActionError(null);
    try {
      if (accountRequest && accountToken) {
        const updated = await cancelMyCardRequest(id, accountToken);
        queryClient.setQueryData(accountKeys.cardRequest(id), updated);
        await queryClient.invalidateQueries({ queryKey: accountKeys.cardRequests });
        if (saved) {
          const { access_token: _accessToken, ...rest } = updated;
          update(id, rest);
        }
      } else {
        if (!token || !saved) return;
        const updated = await cancelCardRequest(id, saved.shopSlug, token);
        const { access_token: _accessToken, ...rest } = updated;
        update(id, rest);
        queryClient.setQueryData([...queryKeys.cardRequest(id), token], updated);
      }
      setConfirmingCancel(false);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not cancel this request.");
      void (accountRequest ? accountQuery.refetch() : requestQuery.refetch());
    } finally {
      setActing(false);
    }
  }

  async function share() {
    try {
      await Share.share({
        message: `My Card Tracker special order at ${shopName}: #${request.public_ref}`,
      });
    } catch {
      // A dismissed or unsupported share sheet is not an error.
    }
  }

  return (
    <>
      <Stack.Screen options={{ title: `#${request.public_ref}` }} />
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        refreshControl={
          <RefreshControl
            onRefresh={() =>
              void (accountRequest ? accountQuery.refetch() : requestQuery.refetch())
            }
            refreshing={
              accountRequest ? accountQuery.isRefetching : requestQuery.isRefetching
            }
            tintColor={colors.primary}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.statusCard}>
          <View style={styles.statusTop}>
            <View style={styles.statusTitle}>
              <Text style={styles.eyebrow}>SPECIAL ORDER</Text>
              <Text style={styles.shopName}>{shopName}</Text>
            </View>
            <StatusPill status={request.status} />
          </View>
          <Text style={styles.reference}>#{request.public_ref}</Text>
          <Text style={styles.statusLine}>{statusMessage(request.status, quoteExpired)}</Text>
          {!accountRequest &&
          (requestQuery.isError || (accountToken && accountQuery.isError)) &&
          saved ? (
            <Text style={styles.syncNote}>Showing the copy saved on this device.</Text>
          ) : null}
        </View>

        {request.status === "QUOTED" && request.quote_price ? (
          <View style={styles.quoteCard}>
            <View style={styles.quoteTop}>
              <View style={styles.quoteHeading}>
                <Text style={styles.quoteEyebrow}>QUOTE FROM THE SHOP</Text>
                <Text style={styles.quotePrice}>{formatMoney(request.quote_price)}</Text>
              </View>
              <Ionicons name="pricetag-outline" size={24} color={colors.accent} />
            </View>
            {request.quote_expires_at ? (
              <View style={styles.quoteExpiry}>
                <Ionicons
                  name={quoteExpired ? "alert-circle-outline" : "time-outline"}
                  size={16}
                  color={quoteExpired ? colors.danger : colors.accent}
                />
                <Text style={[styles.quoteExpiryText, quoteExpired && styles.quoteExpiredText]}>
                  {quoteExpired
                    ? "This quote has expired"
                    : `Accept within ${formatRemaining(request.quote_expires_at, now)}`}
                </Text>
              </View>
            ) : null}
            {request.vendor_note ? (
              <Text style={styles.vendorNote}>{request.vendor_note}</Text>
            ) : null}
            <Text style={styles.quotePricingNote}>
              This is an indicative quote. When the shop converts it, the hold uses the card&apos;s
              current shelf price.
            </Text>
          </View>
        ) : null}

        {request.status === "ACCEPTED" ? (
          <View style={styles.infoCard}>
            <Ionicons name="checkmark-circle-outline" size={20} color={colors.success} />
            <Text style={styles.infoText}>
              Quote accepted. The shop will reserve the card at its current shelf price and let you
              know when it is ready.
            </Text>
          </View>
        ) : null}

        {request.status === "CONVERTED" ? (
          <View style={styles.infoCard}>
            <Ionicons name="bag-check-outline" size={20} color={colors.success} />
            <Text style={styles.infoText}>
              Your card is reserved
              {request.reservation_ref ? ` under #${request.reservation_ref}` : ""}. Show that
              reference at the shop when you collect it.
            </Text>
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>What you asked for</Text>
          <View style={styles.cardLine}>
            <View style={styles.cardBody}>
              <Text style={styles.cardName}>{request.requested_name}</Text>
              <Text style={styles.cardMeta}>
                {request.set_code ? request.set_code.toUpperCase() : "Set code not given"}
                {request.collector_number ? ` · #${request.collector_number}` : ""}
              </Text>
              <Text style={styles.cardMeta}>
                {titleCase(request.finish)} · {request.condition} ·{" "}
                {request.language.toUpperCase()} · ×{request.quantity}
              </Text>
            </View>
            {request.target_price ? (
              <View style={styles.target}>
                <Text style={styles.targetLabel}>TARGET</Text>
                <Text style={styles.targetValue}>{formatMoney(request.target_price)}</Text>
              </View>
            ) : null}
          </View>
          {request.vendor_note && request.status !== "QUOTED" ? (
            <View style={styles.noteBox}>
              <Text style={styles.noteLabel}>Note from the shop</Text>
              <Text style={styles.noteText}>{request.vendor_note}</Text>
            </View>
          ) : null}
        </View>

        <View style={styles.infoGrid}>
          <Info label="Requested" value={formatDateTime(request.created_at)} />
          <Info label="Updated" value={formatDateTime(request.updated_at)} />
        </View>

        {actionError ? (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.errorText}>{actionError}</Text>
          </View>
        ) : null}

        <View style={styles.actions}>
          <PrimaryButton label="Share reference" onPress={() => void share()} variant="secondary" />
          {canAccept && (token || accountRequest) ? (
            <PrimaryButton
              label="Accept this quote"
              loading={acting}
              onPress={() => void accept()}
            />
          ) : null}
          {canCancel && (token || accountRequest) ? (
            <PrimaryButton
              label="Cancel this request"
              onPress={() => {
                setActionError(null);
                setConfirmingCancel(true);
              }}
              variant="danger"
            />
          ) : null}
          {!ACTIVE.has(request.status) ? (
            <PrimaryButton
              label="Browse this shop"
              onPress={() => router.push(`/shop/${shopSlug}`)}
              variant="secondary"
            />
          ) : null}
        </View>

        {!token && !accountRequest ? (
          <Text style={styles.disclaimer}>
            This request was saved without a guest token, so live updates are unavailable.
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
            <Text style={styles.modalTitle}>Cancel this request?</Text>
            <Text style={styles.modalBody}>
              The shop will stop looking for this card. You can send a new request later.
            </Text>
            {actionError ? <Text style={styles.modalError}>{actionError}</Text> : null}
            <PrimaryButton
              label="Keep request"
              onPress={() => setConfirmingCancel(false)}
              variant="secondary"
            />
            <PrimaryButton
              label="Cancel request"
              loading={acting}
              onPress={() => void cancel()}
              variant="danger"
            />
          </View>
        </View>
      </Modal>
    </>
  );
}

function statusMessage(status: string, quoteExpired: boolean): string {
  switch (status) {
    case "REQUESTED":
      return "The shop is checking whether it can source this card.";
    case "QUOTED":
      return quoteExpired
        ? "The quote expired. Ask the shop for a fresh one."
        : "The shop found it. Review the quote below.";
    case "ACCEPTED":
      return "The shop is preparing your card.";
    case "CONVERTED":
      return "Your card is in and reserved.";
    case "DECLINED":
      return "The shop could not source this card this time.";
    case "EXPIRED":
      return "This request expired.";
    case "CANCELLED":
      return "You cancelled this request.";
    default:
      return "";
  }
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
  eyebrow: { color: "#D8E8E1", fontSize: 10, fontWeight: "900", letterSpacing: 1.4 },
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
  statusLine: { color: "#D8E8E1", fontSize: type.small, lineHeight: 19 },
  syncNote: { color: "#D8E8E1", fontSize: type.tiny, fontStyle: "italic" },
  quoteCard: {
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  quoteTop: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  quoteHeading: { gap: 2 },
  quoteEyebrow: { color: colors.accent, fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  quotePrice: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  quoteExpiry: { flexDirection: "row", alignItems: "center", gap: 5 },
  quoteExpiryText: { color: colors.accent, fontSize: type.small, fontWeight: "700" },
  quoteExpiredText: { color: colors.danger },
  vendorNote: { color: colors.ink, fontSize: type.small, lineHeight: 19 },
  quotePricingNote: { color: colors.inkMuted, fontSize: type.tiny, lineHeight: 18 },
  infoCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.successSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  infoText: { flex: 1, color: colors.success, fontSize: type.small, lineHeight: 19 },
  section: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  cardLine: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  cardBody: { flex: 1, gap: 3 },
  cardName: { color: colors.ink, fontSize: type.body, fontWeight: "800" },
  cardMeta: { color: colors.inkMuted, fontSize: type.small },
  target: { alignItems: "flex-end", gap: 2 },
  targetLabel: { color: colors.inkMuted, fontSize: 10, fontWeight: "900", letterSpacing: 0.8 },
  targetValue: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  noteBox: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: 3,
  },
  noteLabel: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "800" },
  noteText: { color: colors.ink, fontSize: type.small, lineHeight: 19 },
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
  disclaimer: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    lineHeight: 17,
    textAlign: "center",
  },
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
  modalTitle: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  modalBody: {
    color: colors.inkMuted,
    fontSize: type.body,
    lineHeight: 22,
    marginBottom: spacing.sm,
  },
  modalError: { color: colors.danger, fontSize: type.small, lineHeight: 19 },
});
