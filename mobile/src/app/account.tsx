import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { accountKeys, useMyCardRequests, useMyReservations, useMyRestockAlerts } from "../api/queries";
import type { ClaimedCounts } from "../api/types";
import { Field } from "../components/Field";
import { LoadingState } from "../components/LoadingState";
import { PrimaryButton } from "../components/PrimaryButton";
import { formatDateTime } from "../lib/format";
import { useAuth } from "../state/auth";
import { usePush, type PushStatus } from "../state/push";
import { colors, radii, spacing, type } from "../theme";

type Step = "email" | "code";

export default function AccountScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const {
    customer,
    hydrated,
    isAuthenticated,
    lastClaimed,
    refreshCustomer,
    requestCode,
    signOut,
    token,
    verifyCode,
  } = useAuth();
  const push = usePush();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reservations = useMyReservations(token);
  const requests = useMyCardRequests(token);
  const alerts = useMyRestockAlerts(token);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setInterval(() => setResendIn((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, [resendIn]);

  async function sendCode() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await requestCode(email);
      setStep("code");
      setCode("");
      setDebugCode(result.debug_code ?? null);
      setResendIn(result.resend_after);
      setNotice(`We sent a 6-digit code to ${email.trim().toLowerCase()}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send a code.");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await verifyCode(email, code);
      setDebugCode(null);
      setNotice(claimMessage(result.claimed));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: accountKeys.reservations }),
        queryClient.invalidateQueries({ queryKey: accountKeys.cardRequests }),
        queryClient.invalidateQueries({ queryKey: accountKeys.restockAlerts }),
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not verify this code.");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      await refreshCustomer();
      await queryClient.invalidateQueries({ queryKey: accountKeys.all });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not refresh your account.");
    } finally {
      setRefreshing(false);
    }
  }

  function handleSignOut() {
    setNotice(null);
    setError(null);
    setStep("email");
    setCode("");
    setDebugCode(null);
    signOut();
  }

  if (!hydrated) return <LoadingState label="Loading your account…" />;

  if (isAuthenticated && customer) {
    const counts = {
      reservations: reservations.data?.items.length ?? 0,
      requests: requests.data?.items.length ?? 0,
      alerts: alerts.data?.items.length ?? 0,
    };
    return (
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Ionicons name="person-outline" size={22} color={colors.primary} />
          </View>
          <Text style={styles.heroEyebrow}>SIGNED IN</Text>
          <Text style={styles.heroEmail}>{customer.email}</Text>
          <Text style={styles.heroBody}>
            Your holds, alerts, and special orders follow this verified email.
          </Text>
        </View>

        {notice ? <Notice text={notice} /> : null}
        {error ? <ErrorBox text={error} /> : null}

        <View style={styles.countGrid}>
          <CountCard icon="bag-handle-outline" label="Holds" value={counts.reservations} />
          <CountCard icon="sparkles-outline" label="Requests" value={counts.requests} />
          <CountCard icon="notifications-outline" label="Alerts" value={counts.alerts} />
        </View>

        {lastClaimed && totalClaimed(lastClaimed) > 0 ? (
          <View style={styles.linked}>
            <Ionicons name="link-outline" size={18} color={colors.primary} />
            <Text style={styles.linkedText}>
              Linked {totalClaimed(lastClaimed)} earlier item
              {totalClaimed(lastClaimed) === 1 ? "" : "s"} with this email.
            </Text>
          </View>
        ) : null}

        <View style={styles.infoCard}>
          <Row label="Verified" value="Yes" />
          <Row
            label="Account created"
            value={customer.created_at ? formatDateTime(customer.created_at) : "—"}
          />
          <Row label="Session" value="Memory only" />
        </View>

        <View style={styles.pushCard}>
          <View style={styles.pushHeader}>
            <Ionicons name="notifications-outline" size={18} color={colors.primary} />
            <Text style={styles.pushTitle}>Push notifications</Text>
          </View>
          <Text style={styles.pushBody}>{pushMessage(push.status)}</Text>
          {push.error ? <Text style={styles.pushError}>{push.error}</Text> : null}
          {push.status === "enabled" ? (
            <PrimaryButton
              label="Turn off push notifications"
              onPress={() => void push.disable()}
              variant="secondary"
            />
          ) : push.status === "denied" || push.status === "unsupported" ? null : (
            <PrimaryButton
              disabled={push.status === "enabling"}
              label="Enable push notifications"
              loading={push.status === "enabling"}
              onPress={() => void push.enable()}
            />
          )}
        </View>

        <Text style={styles.note}>
          For privacy, this session is not saved on the device. Closing and reopening the app signs
          you out; guest holds on this device are always still available.
        </Text>

        <PrimaryButton
          label="Refresh account data"
          loading={refreshing}
          onPress={() => void refresh()}
          variant="secondary"
        />
        <PrimaryButton label="Sign out" onPress={handleSignOut} variant="danger" />
      </ScrollView>
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.screen}
    >
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Ionicons name="mail-outline" size={22} color={colors.primary} />
          </View>
          <Text style={styles.heroEyebrow}>OPTIONAL ACCOUNT</Text>
          <Text style={styles.heroTitle}>Keep your card list with you.</Text>
          <Text style={styles.heroBody}>
            Sign in with a one-time email code to see your holds, restock alerts, and special
            orders on another device. Guest checkout still works without an account.
          </Text>
        </View>

        {error ? <ErrorBox text={error} /> : null}
        {notice ? <Notice text={notice} /> : null}

        <View style={styles.form}>
          <Field
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            label="Email"
            onChangeText={setEmail}
            placeholder="you@example.com"
            textContentType="emailAddress"
            value={email}
          />

          {step === "code" ? (
            <>
              <Field
                autoCapitalize="none"
                keyboardType="number-pad"
                label="6-digit code"
                maxLength={6}
                onChangeText={(value) => setCode(value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000"
                returnKeyType="done"
                textContentType="oneTimeCode"
                value={code}
              />
              <PrimaryButton
                disabled={email.trim().length === 0 || code.length !== 6}
                label="Verify and sign in"
                loading={busy}
                onPress={() => void verify()}
              />
              <Pressable
                accessibilityRole="button"
                disabled={busy || resendIn > 0}
                onPress={() => void sendCode()}
                style={({ pressed }) => [styles.resend, pressed && styles.pressed]}
              >
                <Text style={[styles.resendLabel, resendIn > 0 && styles.resendDisabled]}>
                  {resendIn > 0 ? `Send a new code in ${resendIn}s` : "Send a new code"}
                </Text>
              </Pressable>
              {__DEV__ && debugCode ? (
                <View style={styles.debug}>
                  <Text style={styles.debugLabel}>Development code</Text>
                  <Text selectable style={styles.debugCode}>
                    {debugCode}
                  </Text>
                </View>
              ) : null}
            </>
          ) : (
            <PrimaryButton
              disabled={email.trim().length === 0}
              label="Email me a sign-in code"
              loading={busy}
              onPress={() => void sendCode()}
            />
          )}
        </View>

        <View style={styles.privacy}>
          <Ionicons name="lock-closed-outline" size={16} color={colors.primary} />
          <Text style={styles.privacyText}>
            The code expires in 10 minutes. Signing in links unclaimed guest items with the same
            email; it never changes another account&apos;s data.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function pushMessage(status: PushStatus): string {
  if (status === "enabled") {
    return "This device gets a notification when a hold is ready, a special order is quoted, or a card is back in stock.";
  }
  if (status === "denied") {
    return "Notifications are blocked for Card Tracker. Allow them in your device settings, then try again.";
  }
  if (status === "unsupported") {
    return "Push notifications need a physical iOS or Android device. The web preview and simulators cannot register a native token.";
  }
  if (status === "enabling") return "Requesting notification permission…";
  if (status === "error") return "Notifications could not be enabled. Check your connection and try again.";
  return "Get a notification when a hold is ready, a special order is quoted, or a card is back in stock.";
}

function totalClaimed(claimed: ClaimedCounts): number {
  return claimed.reservations + claimed.restock_alerts + claimed.card_requests;
}

function claimMessage(claimed: ClaimedCounts): string {
  const total = totalClaimed(claimed);
  if (total === 0) return "Signed in. No older guest items needed linking.";
  return `Signed in and linked ${total} earlier item${total === 1 ? "" : "s"}.`;
}

function CountCard({
  icon,
  label,
  value,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: number;
}) {
  return (
    <View style={styles.countCard}>
      <Ionicons name={icon} size={18} color={colors.primary} />
      <Text style={styles.countValue}>{value}</Text>
      <Text style={styles.countLabel}>{label}</Text>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

function Notice({ text }: { text: string }) {
  return (
    <View style={styles.notice}>
      <Ionicons name="checkmark-circle-outline" size={18} color={colors.primary} />
      <Text style={styles.noticeText}>{text}</Text>
    </View>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <View style={styles.errorBox}>
      <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
      <Text style={styles.errorText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  hero: {
    backgroundColor: colors.primary,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  heroIcon: {
    width: 44,
    height: 44,
    borderRadius: 15,
    backgroundColor: colors.white,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  heroEyebrow: {
    color: "#D8E8E1",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.4,
  },
  heroTitle: {
    color: colors.white,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  heroEmail: {
    color: colors.white,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  heroBody: { color: "#D8E8E1", fontSize: type.small, lineHeight: 19 },
  form: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.md,
  },
  resend: { minHeight: 40, alignItems: "center", justifyContent: "center" },
  resendLabel: { color: colors.primary, fontSize: type.small, fontWeight: "800" },
  resendDisabled: { color: colors.inkMuted },
  pressed: { opacity: 0.82 },
  debug: {
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: 2,
  },
  debugLabel: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  debugCode: {
    color: colors.ink,
    fontSize: type.heading,
    fontWeight: "900",
    letterSpacing: 3,
  },
  privacy: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  privacyText: { flex: 1, color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  notice: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  noticeText: { flex: 1, color: colors.ink, fontSize: type.small, lineHeight: 19 },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerSoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  errorText: { flex: 1, color: colors.danger, fontSize: type.small, lineHeight: 19 },
  countGrid: { flexDirection: "row", gap: spacing.sm },
  countCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.md,
    padding: spacing.md,
    gap: 2,
  },
  countValue: { color: colors.ink, fontSize: type.title, fontWeight: "900" },
  countLabel: { color: colors.inkMuted, fontSize: type.tiny, fontWeight: "700" },
  linked: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.primarySoft,
    borderRadius: radii.md,
    padding: spacing.md,
  },
  linkedText: { flex: 1, color: colors.ink, fontSize: type.small, lineHeight: 19 },
  infoCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  pushCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.md,
  },
  pushHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  pushTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "800" },
  pushBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  pushError: { color: colors.danger, fontSize: type.small, lineHeight: 19 },
  row: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md },
  rowLabel: { color: colors.inkMuted, fontSize: type.small },
  rowValue: { flex: 1, color: colors.ink, fontSize: type.small, fontWeight: "800", textAlign: "right" },
  note: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
});
