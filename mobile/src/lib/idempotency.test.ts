import { describe, expect, it, vi } from "vitest";

const randomUUID = vi.fn(() => "uuid-1");

vi.mock("expo-crypto", () => ({ randomUUID }));

describe("idempotency keys", () => {
  it("uses the platform UUID source", async () => {
    const { newIdempotencyKey } = await import("./idempotency");
    expect(newIdempotencyKey()).toBe("uuid-1");
    expect(randomUUID).toHaveBeenCalled();
  });
});
