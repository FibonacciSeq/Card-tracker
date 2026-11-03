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
import { useLocale } from "../state/locale";
import { useAuth } from "../state/auth";
import { usePush, type PushStatus } from "../state/push";
import { colors, radii, spacing, type } from "../theme";

type Step = "email" | "code";

export default function AccountScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { locale, setLocale, t } = useLocale();
  const {
    customer,
    deleteAccount,
    hydrated,
    isAuthenticated,
    lastClaimed,
    refreshCustomer,
    requestCode,
    signOut,
    token,
    updateProfile,
    verifyCode,
  } = useAuth();
  const push = usePush();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(0);
  const [busy, setBusy] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [phone, setPhone] = useState("");
  const [pushEnabled, setPushEnabled] = useState(true);
  const [emailNotificationsEnabled, setEmailNotificationsEnabled] = useState(true);
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(false);
  const [notificationsOptOut, setNotificationsOptOut] = useState(false);

  const reservations = useMyReservations(token);
  const requests = useMyCardRequests(token);
  const alerts = useMyRestockAlerts(token);

  useEffect(() => {
    if (resendIn <= 0) return;
    const timer = setInterval(() => setResendIn((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, [resendIn]);

  useEffect(() => {
    if (!customer) return;
    setDisplayName(customer.display_name ?? "");
    setPhone(customer.phone ?? "");
    setPushEnabled(customer.push_notifications_enabled ?? true);
    setEmailNotificationsEnabled(customer.email_notifications_enabled ?? true);
    setQuietHoursEnabled(customer.quiet_hours_enabled ?? false);
    setNotificationsOptOut(customer.notifications_opt_out ?? false);
  }, [customer]);

  async function saveProfile() {
    setError(null);
    setNotice(null);
    setSavingProfile(true);
    try {
      await updateProfile({
        display_name: displayName.trim() || null,
        phone: phone.trim() || null,
        push_notifications_enabled: pushEnabled,
        email_notifications_enabled: emailNotificationsEnabled,
        quiet_hours_enabled: quietHoursEnabled,
        notifications_opt_out: notificationsOptOut,
      });
      setNotice("Profile updated.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update your profile.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function deleteCurrentAccount() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      await deleteAccount();
      setNotice("Your account has been removed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete your account.");
    } finally {
      setBusy(false);
    }
  }

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
          <Text style={styles.heroEyebrow}>{t("signedIn")}</Text>
          <Text style={styles.heroEmail}>{customer.email}</Text>
          <Text style={styles.heroBody}>{t("signedInBody")}</Text>
        </View>

        {notice ? <Notice text={notice} /> : null}
        {error ? <ErrorBox text={error} /> : null}

        <View style={styles.countGrid}>
          <CountCard icon="bag-handle-outline" label={t("holds")} value={counts.reservations} />
          <CountCard icon="sparkles-outline" label={t("requests")} value={counts.requests} />
          <CountCard icon="notifications-outline" label={t("alerts")} value={counts.alerts} />
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

        <View style={styles.profileCard}>
          <Text style={styles.pushTitle}>Profile</Text>
          <Field
            label="Display name"
            onChangeText={setDisplayName}
            placeholder="Your name"
            value={displayName}
          />
          <Field
            autoComplete="tel"
            keyboardType="phone-pad"
            label="Phone"
            onChangeText={setPhone}
            placeholder="+381600000000"
            textContentType="telephoneNumber"
            value={phone}
          />
          <SettingToggle
            label="Push notifications"
            value={pushEnabled}
            onValueChange={setPushEnabled}
          />
          <SettingToggle
            label="Email notifications"
            value={emailNotificationsEnabled}
            onValueChange={setEmailNotificationsEnabled}
          />
          <SettingToggle
            label="Quiet hours"
            value={quietHoursEnabled}
            onValueChange={setQuietHoursEnabled}
          />
          <SettingToggle
            label="Opt out of all notifications"
            value={notificationsOptOut}
            onValueChange={setNotificationsOptOut}
          />
          <PrimaryButton
            label="Save profile"
            loading={savingProfile}
            onPress={() => void saveProfile()}
            variant="secondary"
          />
        </View>

        <View style={styles.pushCard}>
          <View style={styles.pushHeader}>
            <Ionicons name="notifications-outline" size={18} color={colors.primary} />
            <Text style={styles.pushTitle}>{t("turnOnPush")}</Text>
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
          This signed-in session is kept in secure device storage so you can stay signed in across
          app restarts. Signing out revokes the active refresh token, while guest holds on this device
          remain available.
        </Text>

        <PrimaryButton
          label="Refresh account data"
          loading={refreshing}
          onPress={() => void refresh()}
          variant="secondary"
        />
        <PrimaryButton
          label="Delete account"
          loading={busy}
          onPress={() => void deleteCurrentAccount()}
          variant="danger"
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
          <Text style={styles.heroEyebrow}>{t("optionalAccount")}</Text>
          <Text style={styles.heroTitle}>{t("accountHeroTitle")}</Text>
          <Text style={styles.heroBody}>{t("accountHeroBody")}</Text>
        </View>

        {error ? <ErrorBox text={error} /> : null}
        {notice ? <Notice text={notice} /> : null}

        <View style={styles.localeCard}>
          <Text style={styles.localeLabel}>{t("language")}</Text>
          <View style={styles.localeRow}>
            <Pressable
              accessibilityRole="button"
              onPress={() => setLocale("en")}
              style={({ pressed }) => [
                styles.localeButton,
                locale === "en" && styles.localeButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text style={[styles.localeButtonText, locale === "en" && styles.localeButtonTextActive]}>
                {t("english")}
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              onPress={() => setLocale("sr")}
              style={({ pressed }) => [
                styles.localeButton,
                locale === "sr" && styles.localeButtonActive,
                pressed && styles.pressed,
              ]}
            >
              <Text style={[styles.localeButtonText, locale === "sr" && styles.localeButtonTextActive]}>
                {t("serbian")}
              </Text>
            </Pressable>
          </View>
          <Text style={styles.localeHint}>{t("languageHint")}</Text>
        </View>

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
                label={t("verifyAndSignIn")}
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
              label={t("emailMeCode")}
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

function SettingToggle({
  label,
  value,
  onValueChange,
}: {
  label: string;
  value: boolean;
  onValueChange: (next: boolean) => void;
}) {
  return (
    <View style={styles.toggleRow}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <Pressable
        accessibilityRole="switch"
        onPress={() => onValueChange(!value)}
        style={({ pressed }) => [
          styles.switch,
          value ? styles.switchOn : styles.switchOff,
          pressed && styles.pressed,
        ]}
      >
        <View style={[styles.switchThumb, value && styles.switchThumbOn]} />
      </Pressable>
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
  localeCard: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  localeLabel: {
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "800",
  },
  localeRow: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  localeButton: {
    flex: 1,
    minHeight: 40,
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
  },
  localeButtonActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  localeButtonText: {
    color: colors.ink,
    fontSize: type.small,
    fontWeight: "700",
  },
  localeButtonTextActive: {
    color: colors.primary,
  },
  localeHint: {
    color: colors.inkMuted,
    fontSize: type.tiny,
    lineHeight: 18,
  },
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
  profileCard: {
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
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    paddingVertical: spacing.xs,
  },
  toggleLabel: { flex: 1, color: colors.ink, fontSize: type.small, fontWeight: "700" },
  switch: {
    width: 52,
    height: 32,
    borderRadius: 16,
    justifyContent: "center",
    paddingHorizontal: 4,
  },
  switchOn: { backgroundColor: colors.primary },
  switchOff: { backgroundColor: colors.line },
  switchThumb: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.white,
    marginLeft: 0,
  },
  switchThumbOn: { marginLeft: 20 },
  note: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
});
