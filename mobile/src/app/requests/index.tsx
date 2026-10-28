import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { RequestCard } from "../../components/RequestCard";
import { useSpecialOrders } from "../../state/specialOrders";
import { colors, radii, spacing, type } from "../../theme";

export default function RequestsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { hydrated, requests } = useSpecialOrders();

  if (!hydrated) return <LoadingState label="Loading special orders…" />;

  return (
    <View style={styles.screen}>
      <ScrollView
        contentContainerStyle={{
          padding: spacing.lg,
          paddingBottom: insets.bottom + spacing.xxl,
          gap: spacing.lg,
        }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.intro}>
          <Text style={styles.eyebrow}>SPECIAL ORDERS</Text>
          <Text style={styles.title}>Looking for something specific?</Text>
          <Text style={styles.subtitle}>
            Ask a shop to source a card you cannot find. You will get a quote before anything is
            reserved.
          </Text>
          <Pressable
            accessibilityLabel="Request a card"
            accessibilityRole="button"
            onPress={() => router.push("/requests/new")}
            style={({ pressed }) => [styles.newButton, pressed && styles.pressed]}
          >
            <Ionicons name="add-circle-outline" size={18} color={colors.primary} />
            <Text style={styles.newLabel}>Request a card</Text>
          </Pressable>
        </View>

        {requests.length === 0 ? (
          <EmptyState
            icon="sparkles-outline"
            title="No special orders yet"
            body="Request a card by name, or open any card at a shop and choose “Need a different copy?”."
            actionLabel="Browse shops"
            onAction={() => router.replace("/")}
          />
        ) : (
          <View style={styles.list}>
            {requests.map((request) => (
              <RequestCard
                key={request.id}
                request={request}
                onPress={() => router.push(`/requests/${request.id}`)}
              />
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  intro: {
    backgroundColor: colors.accentSoft,
    borderRadius: radii.lg,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  eyebrow: { color: colors.accent, fontSize: 10, fontWeight: "900", letterSpacing: 1.4 },
  title: { color: colors.ink, fontSize: type.title, fontWeight: "900", letterSpacing: -0.4 },
  subtitle: { color: colors.inkMuted, fontSize: type.small, lineHeight: 19 },
  newButton: {
    marginTop: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
  },
  newLabel: { color: colors.primary, fontSize: type.body, fontWeight: "800" },
  list: { gap: spacing.md },
  pressed: { opacity: 0.85 },
});
