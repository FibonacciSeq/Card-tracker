import { useRouter } from "expo-router";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useMyCardRequests } from "../../api/queries";
import { EmptyState } from "../../components/EmptyState";
import { LoadingState } from "../../components/LoadingState";
import { RequestCard } from "../../components/RequestCard";
import { mergeCardRequests } from "../../lib/accountMerge";
import { useAuth } from "../../state/auth";
import { useLocale } from "../../state/locale";
import { useSpecialOrders } from "../../state/specialOrders";
import { colors, radii, spacing, type } from "../../theme";

export default function RequestsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { isAuthenticated, token } = useAuth();
  const { t } = useLocale();
  const { hydrated, requests } = useSpecialOrders();
  const accountRequests = useMyCardRequests(token);
  const allRequests = mergeCardRequests(
    isAuthenticated ? (accountRequests.data?.items ?? []) : [],
    requests,
  );

  if (!hydrated || (token && accountRequests.isLoading)) {
    return <LoadingState label={t("Loading special orders…")} />;
  }

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
          <Text style={styles.eyebrow}>{t("SPECIAL ORDERS")}</Text>
          <Text style={styles.title}>{t("Looking for something specific?")}</Text>
          <Text style={styles.subtitle}>
            {t("Open a shop and choose Request a special order to ask it to source a card you cannot find. You will get a quote before anything is reserved.")}
          </Text>
        </View>

        {allRequests.length === 0 ? (
          <EmptyState
            icon="sparkles-outline"
            title={t("No special orders yet")}
            body={t("Open a shop and choose “Request a special order”, or open any card at a shop and choose “Need a different copy?”.")}
            actionLabel={t("Browse shops")}
            onAction={() => router.replace("/")}
          />
        ) : (
          <View style={styles.list}>
            {allRequests.map((request) => (
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
  list: { gap: spacing.md },
});
