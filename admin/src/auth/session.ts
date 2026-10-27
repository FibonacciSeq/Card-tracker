import type { StaffMe } from "../api/types";

export type Session = {
  token: string;
  /** Epoch milliseconds. The backend token is valid for `expires_in` seconds. */
  expiresAt: number;
  me: StaffMe;
};

const STORAGE_KEY = "cardtracker.admin.session";

export function loadSession(): Session | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (
      typeof parsed.token !== "string" ||
      typeof parsed.expiresAt !== "number" ||
      typeof parsed.me !== "object" ||
      parsed.me === null
    ) {
      return null;
    }
    if (parsed.expiresAt <= Date.now()) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed as Session;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}
