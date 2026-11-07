import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  deleteMe,
  getMe,
  logoutCustomerSession,
  refreshCustomerToken,
  requestEmailChange as requestEmailChangeApi,
  requestOtp,
  revokeAllCustomerSessions,
  setAccountRefreshHandler,
  setAccountUnauthorizedHandler,
  updateMe,
  verifyEmailChange as verifyEmailChangeApi,
  verifyOtp,
} from "../api/client";
import { clearAccountCache } from "../lib/accountCache";
import { readAuthToken, removeAuthToken, writeAuthToken } from "../lib/tokenStore";
import type {
  ClaimedCounts,
  CustomerAccount,
  CustomerToken,
  OtpRequestResult,
} from "../api/types";

type AuthContextValue = {
  hydrated: boolean;
  token: string | null;
  customer: CustomerAccount | null;
  lastClaimed: ClaimedCounts | null;
  isAuthenticated: boolean;
  requestCode: (email: string) => Promise<OtpRequestResult>;
  verifyCode: (email: string, code: string) => Promise<CustomerToken>;
  refreshCustomer: () => Promise<void>;
  updateProfile: (values: {
    display_name?: string | null;
    phone?: string | null;
    push_notifications_enabled?: boolean | null;
    email_notifications_enabled?: boolean | null;
    quiet_hours_enabled?: boolean | null;
    notifications_opt_out?: boolean | null;
  }) => Promise<CustomerAccount>;
  requestEmailChange: (email: string) => Promise<OtpRequestResult>;
  verifyEmailChange: (email: string, code: string) => Promise<CustomerToken>;
  deleteAccount: () => Promise<void>;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
};

const ACCESS_TOKEN_KEY = "cardtracker.customer.access.token";
const REFRESH_TOKEN_KEY = "cardtracker.customer.refresh.token";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [hydrated, setHydrated] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [customer, setCustomer] = useState<CustomerAccount | null>(null);
  const [lastClaimed, setLastClaimed] = useState<ClaimedCounts | null>(null);

  const persistTokens = useCallback(async (access: string | null, refresh: string | null) => {
    if (access) {
      await writeAuthToken(ACCESS_TOKEN_KEY, access);
    } else {
      await removeAuthToken(ACCESS_TOKEN_KEY);
    }
    if (refresh) {
      await writeAuthToken(REFRESH_TOKEN_KEY, refresh);
    } else {
      await removeAuthToken(REFRESH_TOKEN_KEY);
    }
  }, []);

  /** Clear this device without calling the API. */
  const clearLocalSession = useCallback(async () => {
    setToken(null);
    setRefreshToken(null);
    setCustomer(null);
    setLastClaimed(null);
    await persistTokens(null, null);
    await clearAccountCache(queryClient);
  }, [persistTokens, queryClient]);

  /**
   * Sign out this device. The refresh token is sent so the backend revokes only
   * this session; other devices stay signed in. Local state is cleared even if
   * the network call fails, and the server token then expires on its own.
   */
  const signOut = useCallback(async () => {
    const currentAccess = token;
    const currentRefresh = refreshToken;
    await clearLocalSession();
    if (currentAccess) {
      try {
        await logoutCustomerSession(currentAccess, currentRefresh);
      } catch {
        // Ignore network issues when clearing a stale local session.
      }
    }
  }, [clearLocalSession, refreshToken, token]);

  /** Revoke every refresh session, then clear this device. */
  const signOutEverywhere = useCallback(async () => {
    if (token) {
      await revokeAllCustomerSessions(token);
    }
    await clearLocalSession();
  }, [clearLocalSession, token]);

  const handleRefreshFailure = useCallback(async () => {
    await clearLocalSession();
    return false;
  }, [clearLocalSession]);

  const handleSessionRefresh = useCallback(async () => {
    if (!refreshToken) {
      return false;
    }
    try {
      const next = await refreshCustomerToken(refreshToken);
      setToken(next.access_token);
      setRefreshToken(next.refresh_token ?? refreshToken);
      setCustomer(next.customer);
      setLastClaimed(next.claimed);
      await persistTokens(next.access_token, next.refresh_token ?? refreshToken);
      return true;
    } catch {
      await handleRefreshFailure();
      return false;
    }
  }, [handleRefreshFailure, persistTokens, refreshToken]);

  useEffect(() => {
    setAccountUnauthorizedHandler(() => {
      void clearLocalSession();
    });
    setAccountRefreshHandler(async () => {
      if (!refreshToken) {
        await clearLocalSession();
        return false;
      }
      return handleSessionRefresh();
    });
    return () => {
      setAccountUnauthorizedHandler(null);
      setAccountRefreshHandler(null);
    };
  }, [clearLocalSession, handleSessionRefresh, refreshToken]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const savedAccess = await readAuthToken(ACCESS_TOKEN_KEY);
        const savedRefresh = await readAuthToken(REFRESH_TOKEN_KEY);
        if (!active) return;

        if (savedAccess) {
          setToken(savedAccess);
        }
        if (savedRefresh) {
          setRefreshToken(savedRefresh);
        }

        if (savedAccess) {
          try {
            const me = await getMe(savedAccess);
            if (active) {
              setCustomer(me);
              setHydrated(true);
              return;
            }
          } catch {
            // Fall through to refresh-token recovery below.
          }
        }

        if (active && savedRefresh) {
          try {
            const next = await refreshCustomerToken(savedRefresh);
            setToken(next.access_token);
            setRefreshToken(next.refresh_token ?? savedRefresh);
            setCustomer(next.customer);
            setLastClaimed(next.claimed);
            await persistTokens(next.access_token, next.refresh_token ?? savedRefresh);
          } catch {
            if (active) {
              setToken(null);
              setRefreshToken(null);
              setCustomer(null);
              setLastClaimed(null);
              await persistTokens(null, null);
            }
          }
        }
      } finally {
        if (active) {
          setHydrated(true);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [persistTokens]);

  const requestCode = useCallback(async (email: string) => requestOtp(email.trim()), []);

  const verifyCode = useCallback(async (email: string, code: string) => {
    const result = await verifyOtp(email.trim(), code.trim());
    // Verification can be an account switch or a first sign-in that claims
    // guest rows. Drop the previous identity's cached rows before exposing the
    // new session; guest stores and the cart stay untouched.
    await clearAccountCache(queryClient);
    setToken(result.access_token);
    setRefreshToken(result.refresh_token ?? null);
    setCustomer(result.customer);
    setLastClaimed(result.claimed);
    await persistTokens(result.access_token, result.refresh_token ?? null);
    return result;
  }, [persistTokens, queryClient]);

  const refreshCustomer = useCallback(async () => {
    if (!refreshToken) {
      if (token) {
        const me = await getMe(token);
        setCustomer(me);
      }
      return;
    }
    const result = await refreshCustomerToken(refreshToken);
    setToken(result.access_token);
    setRefreshToken(result.refresh_token ?? refreshToken);
    setCustomer(result.customer);
    setLastClaimed(result.claimed);
    await persistTokens(result.access_token, result.refresh_token ?? refreshToken);
  }, [persistTokens, refreshToken, token]);

  const updateProfile = useCallback(
    async (values: {
      display_name?: string | null;
      phone?: string | null;
      push_notifications_enabled?: boolean | null;
      email_notifications_enabled?: boolean | null;
      quiet_hours_enabled?: boolean | null;
      notifications_opt_out?: boolean | null;
    }) => {
      if (!token) throw new Error("Not signed in.");
      const next = await updateMe(token, values);
      setCustomer(next);
      return next;
    },
    [token],
  );

  const deleteAccount = useCallback(async () => {
    if (!token) return;
    await deleteMe(token);
    // The DELETE endpoint already revokes every refresh token and deactivates
    // the account, so only local cleanup remains.
    await clearLocalSession();
  }, [clearLocalSession, token]);

  const requestEmailChange = useCallback(
    async (email: string) => {
      if (!token) throw new Error("Not signed in.");
      return requestEmailChangeApi(token, email.trim());
    },
    [token],
  );

  const verifyEmailChange = useCallback(
    async (email: string, code: string) => {
      if (!token) throw new Error("Not signed in.");
      const result = await verifyEmailChangeApi(token, email.trim(), code.trim());
      // The address and claimed rows changed, even though the account id did
      // not. Clear the account cache so no pre-change rows can render after the
      // new token is applied.
      await clearAccountCache(queryClient);
      setToken(result.access_token);
      setRefreshToken(result.refresh_token ?? null);
      setCustomer(result.customer);
      setLastClaimed(result.claimed);
      await persistTokens(result.access_token, result.refresh_token ?? null);
      return result;
    },
    [persistTokens, queryClient, token],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      hydrated,
      token,
      customer,
      lastClaimed,
      isAuthenticated: Boolean(token && customer),
      requestCode,
      verifyCode,
      refreshCustomer,
      updateProfile,
      requestEmailChange,
      verifyEmailChange,
      deleteAccount,
      signOut,
      signOutEverywhere,
    }),
    [
      customer,
      deleteAccount,
      hydrated,
      lastClaimed,
      refreshCustomer,
      requestCode,
      requestEmailChange,
      signOut,
      signOutEverywhere,
      token,
      updateProfile,
      verifyCode,
      verifyEmailChange,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
