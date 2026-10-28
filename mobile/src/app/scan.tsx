import { Ionicons } from "@expo/vector-icons";
import {
  CameraView,
  useCameraPermissions,
  type BarcodeScanningResult,
} from "expo-camera";
import * as Linking from "expo-linking";
import { Stack, useIsFocused, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { targetFromInput, targetPath } from "../lib/deeplink";
import { colors, radii, spacing, type } from "../theme";

const REPEAT_SCAN_MS = 2500;

export default function ScanScreen() {
  const router = useRouter();
  const isFocused = useIsFocused();
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const lastScan = useRef<{ data: string; at: number } | null>(null);
  const navigating = useRef(false);

  useEffect(() => {
    if (!isFocused) return;
    navigating.current = false;
    lastScan.current = null;
  }, [isFocused]);

  function openTarget(raw: string): boolean {
    if (navigating.current) return false;
    const target = targetFromInput(raw);
    if (!target) {
      setScanError("That code is not a Card Tracker shop or card code.");
      return false;
    }
    setScanError(null);
    navigating.current = true;
    router.dismissTo(targetPath(target));
    return true;
  }

  function handleScan(result: BarcodeScanningResult) {
    const now = Date.now();
    const previous = lastScan.current;
    if (previous && previous.data === result.data && now - previous.at < REPEAT_SCAN_MS) {
      return;
    }
    lastScan.current = { data: result.data, at: now };
    openTarget(result.data);
  }

  function submitManual() {
    const value = manual.trim();
    if (!value) return;
    if (openTarget(value)) setManual("");
  }

  const manualEntry = (
    <View style={styles.manualPanel}>
      <Text style={styles.panelTitle}>Enter a code by hand</Text>
      <Text style={styles.panelBody}>
        Type the shop code printed under the QR code, for example <Text style={styles.mono}>bolt-shop</Text>.
      </Text>
      <View style={styles.manualRow}>
        <TextInput
          accessibilityLabel="Shop code or Card Tracker link"
          autoCapitalize="none"
          autoCorrect={false}
          onChangeText={(value) => {
            setManual(value);
            if (scanError) setScanError(null);
          }}
          onSubmitEditing={submitManual}
          placeholder="bolt-shop"
          placeholderTextColor={colors.inkMuted}
          returnKeyType="go"
          style={styles.input}
          value={manual}
        />
        <Pressable
          accessibilityLabel="Open this shop"
          accessibilityRole="button"
          disabled={!manual.trim()}
          onPress={submitManual}
          style={({ pressed }) => [
            styles.goButton,
            pressed && styles.pressed,
            !manual.trim() && styles.disabled,
          ]}
        >
          <Ionicons name="arrow-forward" size={18} color={colors.white} />
        </Pressable>
      </View>
      {scanError ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {scanError}
        </Text>
      ) : null}
    </View>
  );

  return (
    <View style={styles.screen}>
      <Stack.Screen options={{ title: "Scan a code" }} />
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + spacing.xl }]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {permission === null ? (
          <View style={styles.permissionPanel}>
            <Text style={styles.panelBody}>Checking camera permission…</Text>
          </View>
        ) : !permission.granted ? (
          <View style={styles.permissionPanel}>
            <View style={styles.permissionIcon}>
              <Ionicons name="camera-outline" size={26} color={colors.primary} />
            </View>
            <Text style={styles.panelTitle}>Scan with the camera</Text>
            <Text style={styles.panelBody}>
              Allow camera access to scan the QR code on the shop counter or a card
              label. You can always enter the shop code by hand instead.
            </Text>
            {permission.canAskAgain ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => void requestPermission()}
                style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
              >
                <Text style={styles.primaryLabel}>Allow camera</Text>
              </Pressable>
            ) : (
              <Pressable
                accessibilityRole="button"
                onPress={() => void Linking.openSettings()}
                style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
              >
                <Text style={styles.primaryLabel}>Open settings</Text>
              </Pressable>
            )}
          </View>
        ) : cameraError ? (
          <View style={styles.permissionPanel}>
            <View style={styles.permissionIcon}>
              <Ionicons name="alert-circle-outline" size={26} color={colors.danger} />
            </View>
            <Text style={styles.panelTitle}>Camera unavailable</Text>
            <Text style={styles.panelBody}>
              {cameraError} You can still enter the shop code below.
            </Text>
            <Pressable
              accessibilityRole="button"
              onPress={() => setCameraError(null)}
              style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
            >
              <Text style={styles.primaryLabel}>Try the camera again</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.cameraWrap}>
            {isFocused ? (
              <CameraView
                barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
                facing="back"
                onBarcodeScanned={handleScan}
                onMountError={(event) => setCameraError(event.message)}
                style={styles.camera}
              />
            ) : null}
            <View pointerEvents="none" style={styles.frame} />
            <View pointerEvents="none" style={styles.scanHint}>
              <Text style={styles.scanHintText}>Point at the shop QR code</Text>
            </View>
          </View>
        )}

        {manualEntry}

        <View style={styles.tip}>
          <Ionicons name="qr-code-outline" size={16} color={colors.inkMuted} />
          <Text style={styles.tipText}>
            Codes point at a shop or a single card. A card code opens the card with its
            price and availability.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: {
    flexGrow: 1,
    padding: spacing.lg,
    gap: spacing.lg,
  },
  cameraWrap: {
    height: 360,
    borderRadius: radii.lg,
    overflow: "hidden",
    backgroundColor: colors.ink,
  },
  camera: { flex: 1 },
  frame: {
    position: "absolute",
    top: "18%",
    left: "18%",
    width: "64%",
    height: "64%",
    borderWidth: 2,
    borderColor: colors.white,
    borderRadius: radii.md,
    opacity: 0.9,
  },
  scanHint: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: spacing.lg,
    alignItems: "center",
  },
  scanHintText: {
    color: colors.white,
    backgroundColor: colors.overlay,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    fontSize: type.small,
    fontWeight: "700",
    overflow: "hidden",
  },
  permissionPanel: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  permissionIcon: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  panelTitle: { color: colors.ink, fontSize: type.heading, fontWeight: "900" },
  panelBody: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  primaryButton: {
    marginTop: spacing.sm,
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryLabel: { color: colors.white, fontSize: type.body, fontWeight: "800" },
  pressed: { opacity: 0.85 },
  disabled: { opacity: 0.45 },
  manualPanel: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  manualRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  input: {
    flex: 1,
    minHeight: 48,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radii.md,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
    color: colors.ink,
    fontSize: type.body,
  },
  goButton: {
    width: 48,
    height: 48,
    borderRadius: radii.md,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  mono: { fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }) },
  error: { color: colors.danger, fontSize: type.small, lineHeight: 18 },
  tip: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  tipText: { flex: 1, color: colors.inkMuted, fontSize: type.tiny, lineHeight: 16 },
});
