import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { hydrateQueryClient, persistQueryCache } from "../lib/queryCache";
import { colors, type } from "../theme";
import { AuthProvider } from "../state/auth";
import { CartProvider } from "../state/cart";
import { LocaleProvider } from "../state/locale";
import { PushProvider } from "../state/push";
import { ReservationsProvider } from "../state/reservations";
import { RestockAlertsProvider } from "../state/restockAlerts";
import { SpecialOrdersProvider } from "../state/specialOrders";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: false,
      networkMode: "offlineFirst",
    },
  },
});

void hydrateQueryClient(queryClient);
queryClient.getQueryCache().subscribe(() => {
  void persistQueryCache(queryClient);
});

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <LocaleProvider>
          <AuthProvider>
            <PushProvider>
              <CartProvider>
                <ReservationsProvider>
                  <RestockAlertsProvider>
                    <SpecialOrdersProvider>
                      <StatusBar style="dark" />
                      <Stack
                        screenOptions={{
                          headerStyle: { backgroundColor: colors.background },
                          headerTintColor: colors.ink,
                          headerTitleStyle: { fontWeight: "800", fontSize: type.heading },
                          headerShadowVisible: false,
                          contentStyle: { backgroundColor: colors.background },
                        }}
                      >
                        <Stack.Screen name="index" options={{ headerShown: false }} />
                        <Stack.Screen name="account" options={{ title: "Your account" }} />
                        <Stack.Screen
                          name="scan"
                          options={{ title: "Scan a code", presentation: "modal" }}
                        />
                        <Stack.Screen name="shop/[slug]/index" options={{ title: "Shop" }} />
                        <Stack.Screen name="shop/[slug]/cart" options={{ title: "Your hold" }} />
                        <Stack.Screen
                          name="shop/[slug]/card/[stockId]"
                          options={{ title: "Card" }}
                        />
                        <Stack.Screen name="reservation/[id]" options={{ title: "Reservation" }} />
                        <Stack.Screen name="alerts" options={{ title: "Restock alerts" }} />
                        <Stack.Screen name="notifications" options={{ title: "Notifications" }} />
                        <Stack.Screen name="requests/index" options={{ title: "Special orders" }} />
                        <Stack.Screen name="requests/new" options={{ title: "Request a card" }} />
                        <Stack.Screen name="requests/[id]" options={{ title: "Special order" }} />
                      </Stack>
                    </SpecialOrdersProvider>
                  </RestockAlertsProvider>
                </ReservationsProvider>
              </CartProvider>
            </PushProvider>
          </AuthProvider>
        </LocaleProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}
