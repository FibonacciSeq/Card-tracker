import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { accountKeys, useMyCardRequests, useMyReservations, useMyRestockAlerts } from "../api/queries";
import type { ClaimedCounts, CustomerAccount, CustomerProfileUpdate } from "../api/types";
import { Field } from "../components/Field";
import { LoadingState } from "../components/LoadingState";
import { PrimaryButton } from "../components/PrimaryButton";
import { formatDateTime } from "../lib/format";
import {
  APPEARANCE_OPTIONS,
  SORT_OPTIONS,
  TIME_FORMAT_OPTIONS,
  type AppearancePreference,
  type TimeFormatPreference,
} from "../lib/preferences";
import { useLocale } from "../state/locale";
import { usePreferences } from "../state/preferences";
import { useAuth } from "../state/auth";
import { usePush, type PushStatus } from "../state/push";
import { colors, radii, spacing, type } from "../theme";

type EmailChangeStep = "idle" | "code";
type AccountAction = "delete" | "sign-out" | "sign-out-all" | null;

export default function AccountScreen() {
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const { t, locale } = useLocale();
  const { preferences } = usePreferences();
  const {
    changePassword,
    customer,
    deleteAccount,
    hydrated,
    isAuthenticated,
    lastClaimed,
    refreshCustomer,
    requestEmailChange,
    signOut,
    signOutEverywhere,
    token,
    updateProfile,
    verifyEmailChange,
  } = useAuth();
  const push = usePush();
  const router = useRouter();

  const [emailStep, setEmailStep] = useState<EmailChangeStep>("idle");
  const [newEmail, setNewEmail] = useState("");
  const [emailCode, setEmailCode] = useState("");
  const [emailDebugCode, setEmailDebugCode] = useState<string | null>(null);
  const [emailResendIn, setEmailResendIn] = useState(0);
  const [changingEmail, setChangingEmail] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [accountAction, setAccountAction] = useState<AccountAction>(null);
  const [accountActionError, setAccountActionError] = useState<string | null>(null);

  const reservations = useMyReservations(token);
  const requests = useMyCardRequests(token);
  const alerts = useMyRestockAlerts(token);

  useEffect(() => {
    if (emailResendIn <= 0) return;
    const timer = setInterval(() => setEmailResendIn((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(timer);
  }, [emailResendIn]);

  async function saveProfile(values: CustomerProfileUpdate) {
    setError(null);
    setNotice(null);
    try {
      await updateProfile(values);
      setNotice(t("Profile updated."));
    } catch (caught) {
      setError(t(caught instanceof Error ? caught.message : "Could not update your profile."));
    }
  }

  function openAccountAction(action: Exclude<AccountAction, null>) {
    setError(null);
    setNotice(null);
    setAccountActionError(null);
    setAccountAction(action);
  }

  function resetEmailChangeForm() {
    setEmailStep("idle");
    setNewEmail("");
    setEmailCode("");
    setEmailDebugCode(null);
    setEmailResendIn(0);
  }

  async function performAccountAction() {
    if (!accountAction) return;
    setError(null);
    setNotice(null);
    setAccountActionError(null);
    setBusy(true);
    try {
      if (accountAction === "delete") {
        await deleteAccount();
        setNotice(
          t("Your account is closed and every device is signed out. Guest items saved on this device remain available."),
        );
      } else if (accountAction === "sign-out-all") {
        await signOutEverywhere();
        resetEmailChangeForm();
        setNotice(t("Signed out on every device that was using this account."));
      } else {
        await signOut();
        resetEmailChangeForm();
        setNotice(t("Signed out on this device. Other devices stay signed in."));
      }
      setAccountAction(null);
    } catch (caught) {
      setAccountActionError(
        t(
          caught instanceof Error
            ? caught.message
            : accountAction === "delete"
              ? "Could not delete your account."
              : accountAction === "sign-out-all"
                ? "Could not sign out every device."
                : "Could not sign out this device.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function sendEmailChangeCode() {
    setError(null);
    setNotice(null);
    setChangingEmail(true);
    try {
      const result = await requestEmailChange(newEmail);
      setEmailStep("code");
      setEmailCode("");
      setEmailDebugCode(result.debug_code ?? null);
      setEmailResendIn(result.resend_after);
      setNotice(
        t("We sent a confirmation code to {email}.", { email: newEmail.trim().toLowerCase() }),
      );
    } catch (caught) {
      setError(
        t(caught instanceof Error ? caught.message : "Could not send a confirmation code."),
      );
    } finally {
      setChangingEmail(false);
    }
  }

  async function confirmEmailChange() {
    setError(null);
    setNotice(null);
    setChangingEmail(true);
    try {
      const result = await verifyEmailChange(newEmail, emailCode);
      setEmailStep("idle");
      setNewEmail("");
      setEmailCode("");
      setEmailDebugCode(null);
      setEmailResendIn(0);
      setNotice(emailChangeMessage(result.claimed, t));
      await queryClient.invalidateQueries({ queryKey: accountKeys.all });
    } catch (caught) {
      setError(
        t(caught instanceof Error ? caught.message : "Could not confirm the new email."),
      );
    } finally {
      setChangingEmail(false);
    }
  }

  function cancelEmailChange() {
    setEmailStep("idle");
    setNewEmail("");
    setEmailCode("");
    setEmailDebugCode(null);
    setEmailResendIn(0);
  }

  async function savePassword(currentPassword: string | null, newPassword: string) {
    setError(null);
    setNotice(null);
    try {
      const hadPassword = customer?.has_password ?? false;
      await changePassword(currentPassword, newPassword);
      setNotice(hadPassword ? t("passwordUpdated") : t("passwordSet"));
    } catch (caught) {
      setError(
        t(caught instanceof Error ? caught.message : "Could not update your password."),
      );
    }
  }

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      await refreshCustomer();
      await queryClient.invalidateQueries({ queryKey: accountKeys.all });
    } catch (caught) {
      setError(
        t(caught instanceof Error ? caught.message : "Could not refresh your account."),
      );
    } finally {
      setRefreshing(false);
    }
  }

  if (!hydrated || !isAuthenticated || !customer) {
    return <LoadingState label={t("Loading your account…")} />;
  }

  if (isAuthenticated && customer) {
    const counts = {
      reservations: reservations.data?.items.length ?? 0,
      requests: requests.data?.items.length ?? 0,
      alerts: alerts.data?.items.length ?? 0,
    };
    const linkedCount = lastClaimed ? totalClaimed(lastClaimed) : 0;
    return (
      <>
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

        <AppPreferencesCard />

        <PrimaryButton
          label={t("Browse shops")}
          onPress={() => router.replace("/")}
          variant="secondary"
        />

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
              {linkedCount === 1
                ? t("Linked {count} earlier item with this email.", { count: linkedCount })
                : t("Linked {count} earlier items with this email.", { count: linkedCount })}
            </Text>
          </View>
        ) : null}

        <View style={styles.infoCard}>
          <Row label={t("Verified")} value={t("Yes")} />
          <Row
            label={t("Account created")}
            value={customer.created_at ? formatDateTime(customer.created_at, { locale, timeFormat: preferences.timeFormat }) : t("—")}
          />
          <Row label={t("Session")} value={t("Secure storage with refresh")} />
        </View>

        <ProfileCard customer={customer} onSave={saveProfile} />

        <PasswordCard
          hasPassword={customer.has_password ?? false}
          onSave={savePassword}
        />

        <View style={styles.profileCard}>
          <Text style={styles.pushTitle}>{t("Email address")}</Text>
          <Text style={styles.pushBody}>
            {t("Changing your email signs out other devices and links guest items that use the new address. We send a confirmation code before applying the change.")}
          </Text>
          {emailStep === "idle" ? (
            <>
              <Field
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                label={t("New email")}
                onChangeText={setNewEmail}
                placeholder={t("new@example.com")}
                textContentType="emailAddress"
                value={newEmail}
              />
              <PrimaryButton
                disabled={
                  changingEmail ||
                  newEmail.trim().length === 0 ||
                  newEmail.trim().toLowerCase() === customer.email.toLowerCase()
                }
                label={t("Send confirmation code")}
                loading={changingEmail}
                onPress={() => void sendEmailChangeCode()}
                variant="secondary"
              />
            </>
          ) : (
            <>
              <Text style={styles.pushBody}>
                {t("Enter the 6-digit code sent to {email}.", { email: newEmail.trim().toLowerCase() })}
              </Text>
              <Field
                autoCapitalize="none"
                keyboardType="number-pad"
                label={t("Confirmation code")}
                maxLength={6}
                onChangeText={(value) => setEmailCode(value.replace(/\D/g, "").slice(0, 6))}
                placeholder={t("000000")}
                returnKeyType="done"
                textContentType="oneTimeCode"
                value={emailCode}
              />
              <PrimaryButton
                disabled={changingEmail || emailCode.length !== 6}
                label={t("Confirm new email")}
                loading={changingEmail}
                onPress={() => void confirmEmailChange()}
              />
              <Pressable
                accessibilityRole="button"
                disabled={changingEmail || emailResendIn > 0}
                onPress={() => void sendEmailChangeCode()}
                style={({ pressed }) => [styles.resend, pressed && styles.pressed]}
              >
                <Text style={[styles.resendLabel, emailResendIn > 0 && styles.resendDisabled]}>
                  {emailResendIn > 0
                    ? t("Send a new code in {count}s", { count: emailResendIn })
                    : t("Send a new code")}
                </Text>
              </Pressable>
              {__DEV__ && emailDebugCode ? (
                <View style={styles.debug}>
                  <Text style={styles.debugLabel}>{t("Development code")}</Text>
                  <Text selectable style={styles.debugCode}>
                    {emailDebugCode}
                  </Text>
                </View>
              ) : null}
              <Pressable
                accessibilityRole="button"
                disabled={changingEmail}
                onPress={cancelEmailChange}
                style={({ pressed }) => [styles.resend, pressed && styles.pressed]}
              >
                <Text style={styles.resendLabel}>{t("Cancel email change")}</Text>
              </Pressable>
            </>
          )}
        </View>

        <View style={styles.pushCard}>
          <View style={styles.pushHeader}>
            <Ionicons name="notifications-outline" size={18} color={colors.primary} />
            <Text style={styles.pushTitle}>{t("turnOnPush")}</Text>
          </View>
          <Text style={styles.pushBody}>{pushMessage(push.status, t)}</Text>
          {push.error ? <Text style={styles.pushError}>{t(push.error)}</Text> : null}
          {push.status === "enabled" ? (
            <PrimaryButton
              label={t("Turn off push notifications")}
              onPress={() => void push.disable()}
              variant="secondary"
            />
          ) : push.status === "denied" || push.status === "unsupported" ? null : (
            <PrimaryButton
              disabled={push.status === "enabling"}
              label={t("Enable push notifications")}
              loading={push.status === "enabling"}
              onPress={() => void push.enable()}
            />
          )}
        </View>

        <View style={styles.pushCard}>
          <View style={styles.pushHeader}>
            <Ionicons name="list-outline" size={18} color={colors.primary} />
            <Text style={styles.pushTitle}>{t("Notification delivery")}</Text>
          </View>
          <Text style={styles.pushBody}>
            {t("See which hold, request, and restock updates were sent, skipped, or failed, and check whether this account still has an active push device.")}
          </Text>
          <PrimaryButton
            label={t("View notification log")}
            onPress={() => router.push("/notifications")}
            variant="secondary"
          />
        </View>

        <Text style={styles.note}>
          {t("This signed-in session is kept in secure device storage so you can stay signed in across app restarts. Signing out revokes this device's refresh session; other devices stay signed in. Guest holds saved on this device remain available.")}
        </Text>
        <Text style={styles.note}>
          {t("Deleting your account closes it for this email and signs out every device. Your hold, special-order, and restock-alert history stays with the shops, and guest data saved on this device is not removed.")}
        </Text>

        <PrimaryButton
          label={t("Refresh account data")}
          loading={refreshing}
          onPress={() => void refresh()}
          variant="secondary"
        />
        <PrimaryButton
          label={t("Sign out all devices")}
          onPress={() => openAccountAction("sign-out-all")}
          variant="secondary"
        />
        <PrimaryButton
          label={t("Delete account")}
          onPress={() => openAccountAction("delete")}
          variant="danger"
        />
        <PrimaryButton label={t("Sign out")} onPress={() => openAccountAction("sign-out")} variant="danger" />
        </ScrollView>
        <Modal
          animationType="fade"
          onRequestClose={() => setAccountAction(null)}
          transparent
          visible={accountAction !== null}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalCard}>
              <View style={styles.modalIcon}>
                <Ionicons
                  name={accountAction === "delete" ? "trash-outline" : "log-out-outline"}
                  size={24}
                  color={colors.danger}
                />
              </View>
              <Text style={styles.modalTitle}>{accountActionTitle(accountAction, t)}</Text>
              <Text style={styles.modalBody}>{accountActionBody(accountAction, t)}</Text>
              {accountActionError ? (
                <Text style={styles.modalError}>{accountActionError}</Text>
              ) : null}
              <PrimaryButton
                label={accountActionCancelLabel(accountAction, t)}
                onPress={() => setAccountAction(null)}
                variant="secondary"
              />
              <PrimaryButton
                label={accountActionConfirmLabel(accountAction, t)}
                loading={busy}
                onPress={() => void performAccountAction()}
                variant="danger"
              />
            </View>
          </View>
        </Modal>
      </>
    );
  }

  return <LoadingState label={t("Redirecting to sign in…")} />;
}

function PasswordCard({
  hasPassword,
  onSave,
}: {
  hasPassword: boolean;
  onSave: (currentPassword: string | null, newPassword: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function save() {
    setLocalError(null);
    if (newPassword.length < 8) {
      setLocalError(t("passwordHint"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError(t("passwordsDoNotMatch"));
      return;
    }
    setSaving(true);
    try {
      await onSave(hasPassword ? currentPassword : null, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } finally {
      setSaving(false);
    }
  }

  return (
    <View style={styles.profileCard}>
      <View style={styles.pushHeader}>
        <Ionicons name="key-outline" size={18} color={colors.primary} />
        <Text style={styles.pushTitle}>{t("accountPasswordTitle")}</Text>
      </View>
      <Text style={styles.pushBody}>{t("accountPasswordBody")}</Text>
      {hasPassword ? (
        <Field
          autoCapitalize="none"
          autoComplete="current-password"
          autoCorrect={false}
          label={t("currentPasswordLabel")}
          onChangeText={setCurrentPassword}
          placeholder={t("••••••••")}
          secureTextEntry
          textContentType="password"
          value={currentPassword}
        />
      ) : null}
      <Field
        autoCapitalize="none"
        autoComplete="new-password"
        autoCorrect={false}
        label={t("newPasswordLabel")}
        onChangeText={setNewPassword}
        placeholder={t("••••••••")}
        secureTextEntry
        textContentType="newPassword"
        value={newPassword}
      />
      <Field
        autoCapitalize="none"
        autoComplete="new-password"
        autoCorrect={false}
        label={t("confirmPasswordLabel")}
        onChangeText={setConfirmPassword}
        placeholder={t("••••••••")}
        secureTextEntry
        textContentType="newPassword"
        value={confirmPassword}
      />
      <Text style={styles.cardHint}>{t("passwordHint")}</Text>
      {localError ? <Text style={styles.pushError}>{localError}</Text> : null}
      <PrimaryButton
        disabled={
          newPassword.length < 8 ||
          confirmPassword.length === 0 ||
          (hasPassword && currentPassword.length === 0)
        }
        label={hasPassword ? t("changePassword") : t("setPassword")}
        loading={saving}
        onPress={() => void save()}
        variant="secondary"
      />
    </View>
  );
}

type Translate = ReturnType<typeof useLocale>["t"];

function pushMessage(status: PushStatus, t: Translate): string {
  if (status === "enabled") {
    return t("This device gets a notification when a hold is ready, a special order is quoted, or a card is back in stock.");
  }
  if (status === "denied") {
    return t("Notifications are blocked for Card Tracker. Allow them in your device settings, then try again.");
  }
  if (status === "unsupported") {
    return t("Push notifications need a physical iOS or Android device. The web preview and simulators cannot register a native token.");
  }
  if (status === "enabling") return t("Requesting notification permission…");
  if (status === "error") return t("Notifications could not be enabled. Check your connection and try again.");
  return t("Get a notification when a hold is ready, a special order is quoted, or a card is back in stock.");
}

function totalClaimed(claimed: ClaimedCounts): number {
  return claimed.reservations + claimed.restock_alerts + claimed.card_requests;
}

function emailChangeMessage(claimed: ClaimedCounts, t: Translate): string {
  const total = totalClaimed(claimed);
  if (total === 0) return t("Email updated. Other devices were signed out.");
  return total === 1
    ? t("Email updated and linked {count} earlier item. Other devices were signed out.", {
        count: total,
      })
    : t("Email updated and linked {count} earlier items. Other devices were signed out.", {
        count: total,
      });
}

function accountActionTitle(action: AccountAction, t: Translate): string {
  if (action === "delete") return t("Delete this account?");
  if (action === "sign-out-all") return t("Sign out on every device?");
  return t("Sign out on this device?");
}

function accountActionBody(action: AccountAction, t: Translate): string {
  if (action === "delete") {
    return t("This closes your account and stops sign-in with this email. Every device is signed out. Your shop history is kept, and guest data saved on this device is not removed.");
  }
  if (action === "sign-out-all") {
    return t("Every device using this account is signed out and can no longer refresh its session. Guest items saved on this device remain available.");
  }
  return t("This device's session is revoked. Other devices stay signed in. Guest items saved on this device remain available.");
}

function accountActionCancelLabel(action: AccountAction, t: Translate): string {
  return action === "delete" ? t("Keep my account") : t("Stay signed in");
}

function accountActionConfirmLabel(action: AccountAction, t: Translate): string {
  if (action === "delete") return t("Delete account");
  if (action === "sign-out-all") return t("Sign out everywhere");
  return t("Sign out");
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

function ProfileCard({
  customer,
  onSave,
}: {
  customer: CustomerAccount;
  onSave: (values: CustomerProfileUpdate) => Promise<void>;
}) {
  const { t } = useLocale();
  const [displayName, setDisplayName] = useState(customer.display_name ?? "");
  const [phone, setPhone] = useState(customer.phone ?? "");
  const [pushEnabled, setPushEnabled] = useState(customer.push_notifications_enabled ?? true);
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(customer.quiet_hours_enabled ?? false);
  const [notificationsOptOut, setNotificationsOptOut] = useState(
    customer.notifications_opt_out ?? false,
  );
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await onSave({
        display_name: displayName.trim() || null,
        phone: phone.trim() || null,
        push_notifications_enabled: pushEnabled,
        quiet_hours_enabled: quietHoursEnabled,
        notifications_opt_out: notificationsOptOut,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <View style={styles.profileCard}>
      <Text style={styles.pushTitle}>{t("Profile")}</Text>
      <Field
        label={t("Display name")}
        onChangeText={setDisplayName}
        placeholder={t("Your name")}
        value={displayName}
      />
      <Field
        autoComplete="tel"
        keyboardType="phone-pad"
        label={t("Phone")}
        onChangeText={setPhone}
        placeholder={t("+381600000000")}
        textContentType="telephoneNumber"
        value={phone}
      />
      <SettingToggle
        label={t("Push notifications")}
        value={pushEnabled}
        onValueChange={setPushEnabled}
      />
      <SettingToggle
        label={t("Quiet hours")}
        value={quietHoursEnabled}
        onValueChange={setQuietHoursEnabled}
      />
      <SettingToggle
        label={t("Opt out of all notifications")}
        value={notificationsOptOut}
        onValueChange={setNotificationsOptOut}
      />
      <PrimaryButton
        label={t("Save profile")}
        loading={saving}
        onPress={() => void save()}
        variant="secondary"
      />
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

function OptionChip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [
        styles.optionChip,
        selected && styles.optionChipActive,
        pressed && styles.pressed,
      ]}
    >
      <Text style={[styles.optionChipText, selected && styles.optionChipTextActive]}>{label}</Text>
    </Pressable>
  );
}

function AppPreferencesCard() {
  const { t } = useLocale();
  const { preferences, updatePreferences } = usePreferences();

  return (
    <View style={styles.profileCard}>
      <View style={styles.pushHeader}>
        <Ionicons name="options-outline" size={18} color={colors.primary} />
        <Text style={styles.pushTitle}>{t("appPreferences")}</Text>
      </View>
      <Text style={styles.pushBody}>{t("appPreferencesHint")}</Text>

      <View style={styles.prefBlock}>
        <Text style={styles.prefLabel}>{t("appearance")}</Text>
        <Text style={styles.cardHint}>{t("appearanceHint")}</Text>
        <View style={styles.optionRow}>
          {APPEARANCE_OPTIONS.map((option) => (
            <OptionChip
              key={option.value}
              label={t(option.value === "system" ? "system" : option.value === "light" ? "light" : "dark")}
              selected={preferences.appearance === option.value}
              onPress={() => updatePreferences({ appearance: option.value as AppearancePreference })}
            />
          ))}
        </View>
      </View>

      <View style={styles.prefBlock}>
        <Text style={styles.prefLabel}>{t("timeFormat")}</Text>
        <Text style={styles.cardHint}>{t("timeFormatHint")}</Text>
        <View style={styles.optionRow}>
          {TIME_FORMAT_OPTIONS.map((option) => (
            <OptionChip
              key={option.value}
              label={t(option.value === "auto" ? "automatic" : option.value === "12h" ? "hour12" : "hour24")}
              selected={preferences.timeFormat === option.value}
              onPress={() => updatePreferences({ timeFormat: option.value as TimeFormatPreference })}
            />
          ))}
        </View>
      </View>

      <View style={styles.prefBlock}>
        <Text style={styles.prefLabel}>{t("catalogDefaults")}</Text>
        <Text style={styles.cardHint}>{t("catalogDefaultsHint")}</Text>
        <Text style={styles.prefSubLabel}>{t("defaultSort")}</Text>
        <View style={styles.optionRow}>
          {SORT_OPTIONS.map((option) => (
            <OptionChip
              key={option.value}
              label={t(
                option.value === "relevance"
                  ? "sortRelevance"
                  : option.value === "name"
                    ? "sortName"
                    : option.value === "price_asc"
                      ? "sortPriceAsc"
                      : option.value === "price_desc"
                        ? "sortPriceDesc"
                        : "sortNewest",
              )}
              selected={preferences.shopSortDefault === option.value}
              onPress={() => updatePreferences({ shopSortDefault: option.value })}
            />
          ))}
        </View>
        <SettingToggle
          label={t("defaultAvailableOnly")}
          value={preferences.shopAvailableOnlyDefault}
          onValueChange={(next) => updatePreferences({ shopAvailableOnlyDefault: next })}
        />
      </View>
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
  heroEmail: {
    color: colors.white,
    fontSize: type.title,
    fontWeight: "900",
    letterSpacing: -0.4,
  },
  heroBody: { color: "#D8E8E1", fontSize: type.small, lineHeight: 19 },
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
  cardHint: { color: colors.inkMuted, fontSize: type.tiny, lineHeight: 17 },
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
  modalTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  modalBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 20 },
  modalError: { color: colors.danger, fontSize: type.small, lineHeight: 19 },
  prefBlock: { gap: spacing.sm },
  prefLabel: { color: colors.ink, fontSize: type.small, fontWeight: "800" },
  prefSubLabel: { color: colors.inkMuted, fontSize: type.small, fontWeight: "700", marginTop: spacing.xs },
  optionRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  optionChip: {
    minHeight: 36,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
    alignItems: "center",
    justifyContent: "center",
  },
  optionChipActive: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  optionChipText: { color: colors.ink, fontSize: type.small, fontWeight: "700" },
  optionChipTextActive: { color: colors.primary },
});
