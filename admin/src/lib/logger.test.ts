import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { installGlobalErrorHandlers, logger, summarizeError } from "./logger";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("logger", () => {
  it("summarizes only safe error fields", () => {
    const api = new ApiError(409, "conflict", { secret: "payload" });
    expect(summarizeError(api)).toEqual({ type: "ApiError", status: 409 });
    expect(summarizeError(new TypeError("bad"))).toEqual({ type: "TypeError" });
    expect(summarizeError("text")).toEqual({ type: "string" });
  });

  it("writes in development and includes summaries", () => {
    const debug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);

    logger.debug("d");
    logger.info("i");
    logger.warn("w");
    logger.warn("w", new Error("bad"));
    logger.error("e");
    logger.error("e", new ApiError(500, "boom"));

    expect(debug).toHaveBeenCalledWith("d");
    expect(info).toHaveBeenCalledWith("i");
    expect(warn).toHaveBeenCalledWith("w");
    expect(warn).toHaveBeenCalledWith("w", { type: "Error" });
    expect(error).toHaveBeenCalledWith("e");
    expect(error).toHaveBeenCalledWith("e", { type: "ApiError", status: 500 });
  });

  it("stays silent outside development", () => {
    vi.stubEnv("DEV", false);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    logger.error("hidden");
    expect(error).not.toHaveBeenCalled();
  });

  it("installs browser error handlers", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    installGlobalErrorHandlers();

    window.dispatchEvent(new ErrorEvent("error", { error: new Error("browser") }));
    const rejection = new Event("unhandledrejection") as Event & { reason?: unknown };
    rejection.reason = new Error("promise");
    window.dispatchEvent(rejection);

    expect(error).toHaveBeenCalled();
  });
});
