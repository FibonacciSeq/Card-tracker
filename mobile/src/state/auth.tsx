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
  getMe,
  requestOtp,
  setAccountUnauthorizedHandler,
  verifyOtp,
} from "../api/client";
import { accountKeys } from "../api/queries";
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
  signOut: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  // Deliberately memory-only: a cold app launch starts signed out.
  const [token, setToken] = useState<string | null>(null);
  const [customer, setCustomer] = useState<CustomerAccount | null>(null);
  const [lastClaimed, setLastClaimed] = useState<ClaimedCounts | null>(null);

  const signOut = useCallback(() => {
    setToken(null);
    setCustomer(null);
    setLastClaimed(null);
    void queryClient.cancelQueries({ queryKey: accountKeys.all });
    queryClient.removeQueries({ queryKey: accountKeys.all });
  }, [queryClient]);

  useEffect(() => {
    setAccountUnauthorizedHandler(signOut);
    return () => setAccountUnauthorizedHandler(null);
  }, [signOut]);

  const requestCode = useCallback(async (email: string) => requestOtp(email.trim()), []);

  const verifyCode = useCallback(async (email: string, code: string) => {
    const result = await verifyOtp(email.trim(), code.trim());
    setToken(result.access_token);
    setCustomer(result.customer);
    setLastClaimed(result.claimed);
    return result;
  }, []);

  const refreshCustomer = useCallback(async () => {
    if (!token) return;
    const me = await getMe(token);
    setCustomer(me);
  }, [token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      hydrated: true,
      token,
      customer,
      lastClaimed,
      isAuthenticated: Boolean(token && customer),
      requestCode,
      verifyCode,
      refreshCustomer,
      signOut,
    }),
    [customer, lastClaimed, refreshCustomer, requestCode, signOut, token, verifyCode],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
