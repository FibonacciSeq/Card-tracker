import { createContext, useContext } from "react";
import type { Session } from "./session";

export type AuthContextValue = {
  session: Session | null;
  signIn: (tenantSlug: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
