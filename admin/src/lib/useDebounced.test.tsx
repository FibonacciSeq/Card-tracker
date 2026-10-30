import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useDebounced } from "./useDebounced";

afterEach(() => {
  vi.useRealTimers();
});

describe("useDebounced", () => {
  it("updates after the delay and clears the timer on change", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ value }) => useDebounced(value, 200), {
      initialProps: { value: "a" },
    });
    expect(result.current).toBe("a");

    rerender({ value: "b" });
    expect(result.current).toBe("a");
    act(() => vi.advanceTimersByTime(100));
    rerender({ value: "c" });
    act(() => vi.advanceTimersByTime(199));
    expect(result.current).toBe("a");
    act(() => vi.advanceTimersByTime(1));
    expect(result.current).toBe("c");
  });

  it("uses the default delay", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDebounced("x"));
    act(() => vi.advanceTimersByTime(250));
    expect(result.current).toBe("x");
  });
});
