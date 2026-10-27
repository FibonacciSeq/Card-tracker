import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { request, setAccessToken } from "../api/client";
import type { StaffMe, Token } from "../api/types";
import { AuthContext, type AuthContextValue } from "./context";
import { clearSession, loadSession, saveSession, type Session } from "./session";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const stored = loadSession();
    // Set the token before the first render so queries fired by children
    // already carry it. Doing this in an effect would let the first request
    // go out unauthenticated and trigger a spurious sign-out.
    setAccessToken(stored?.token ?? null);
    return stored;
  });

  const signOut = useCallback(() => {
    clearSession();
    setAccessToken(null);
    setSession(null);
  }, []);

  // The API client fires this when a request comes back 401.
  useEffect(() => {
    window.addEventListener("cardtracker:unauthorized", signOut);
    return () => window.removeEventListener("cardtracker:unauthorized", signOut);
  }, [signOut]);

  const signIn = useCallback(async (tenantSlug: string, email: string, password: string) => {
    const token = await request<Token>("/v1/staff/auth/login", {
      method: "POST",
      body: { tenant_slug: tenantSlug.trim(), email: email.trim(), password },
    });
    setAccessToken(token.access_token);
    try {
      const me = await request<StaffMe>("/v1/staff/me");
      const next: Session = {
        token: token.access_token,
        expiresAt: Date.now() + token.expires_in * 1000,
        me,
      };
      saveSession(next);
      setSession(next);
    } catch (error) {
      setAccessToken(null);
      throw error;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ session, signIn, signOut }),
    [session, signIn, signOut],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
