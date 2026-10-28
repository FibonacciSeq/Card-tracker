import { ApiError } from "../api/client";

type ErrorSummary = {
  type: string;
  status?: number;
};

/**
 * Keep only non-sensitive fields. Never pass `ApiError.payload`, request
 * bodies, tokens, emails, or form values to a logger or telemetry provider.
 */
export function summarizeError(error: unknown): ErrorSummary {
  if (error instanceof ApiError) {
    return { type: error.name, status: error.status };
  }
  if (error instanceof Error) {
    return { type: error.name };
  }
  return { type: typeof error };
}

/* eslint-disable no-console */
function write(level: "debug" | "info" | "warn" | "error", message: string, error?: unknown) {
  if (!import.meta.env.DEV) return;
  const summary = error === undefined ? undefined : summarizeError(error);
  if (summary === undefined) {
    console[level](message);
  } else {
    console[level](message, summary);
  }
}

export const logger = {
  debug: (message: string) => write("debug", message),
  info: (message: string) => write("info", message),
  warn: (message: string, error?: unknown) => write("warn", message, error),
  error: (message: string, error?: unknown) => write("error", message, error),
};

export function installGlobalErrorHandlers(): void {
  window.addEventListener("error", (event) => {
    logger.error("Unhandled browser error", event.error);
  });
  window.addEventListener("unhandledrejection", (event) => {
    logger.error("Unhandled promise rejection", event.reason);
  });
}
