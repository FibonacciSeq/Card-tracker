import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { CartLine, Money, StockItem } from "../api/types";

const STORAGE_KEY = "cardtracker.cart.v1";

type Carts = Record<string, CartLine[]>;

type CartContextValue = {
  hydrated: boolean;
  linesFor: (slug: string) => CartLine[];
  countFor: (slug: string) => number;
  totalFor: (slug: string) => Money | null;
  add: (slug: string, item: StockItem) => void;
  setQuantity: (slug: string, stockId: string, quantity: number) => void;
  clear: (slug: string) => void;
};

const CartContext = createContext<CartContextValue | null>(null);

function parseCarts(value: string | null): Carts {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value) as Carts;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function CartProvider({ children }: { children: ReactNode }) {
  const [carts, setCarts] = useState<Carts>({});
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((value) => {
        if (active) setCarts(parseCarts(value));
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setHydrated(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(carts)).catch(() => undefined);
  }, [carts, hydrated]);

  const add = useCallback((slug: string, item: StockItem) => {
    setCarts((current) => {
      const lines = current[slug] ?? [];
      const existing = lines.find((line) => line.stockId === item.stock_id);
      if (existing) {
        return {
          ...current,
          [slug]: lines.map((line) =>
            line.stockId === item.stock_id
              ? {
                  ...line,
                  item,
                  quantity: Math.min(item.available, Math.max(1, line.quantity + 1)),
                }
              : line,
          ),
        };
      }
      return {
        ...current,
        [slug]: [...lines, { stockId: item.stock_id, quantity: 1, item }],
      };
    });
  }, []);

  const setQuantity = useCallback((slug: string, stockId: string, quantity: number) => {
    setCarts((current) => {
      const lines = current[slug] ?? [];
      if (quantity <= 0) {
        return { ...current, [slug]: lines.filter((line) => line.stockId !== stockId) };
      }
      return {
        ...current,
        [slug]: lines.map((line) =>
          line.stockId === stockId
            ? { ...line, quantity: Math.min(line.item.available, quantity) }
            : line,
        ),
      };
    });
  }, []);

  const clear = useCallback((slug: string) => {
    setCarts((current) => ({ ...current, [slug]: [] }));
  }, []);

  const linesFor = useCallback((slug: string) => carts[slug] ?? [], [carts]);
  const countFor = useCallback(
    (slug: string) => (carts[slug] ?? []).reduce((sum, line) => sum + line.quantity, 0),
    [carts],
  );
  const totalFor = useCallback(
    (slug: string): Money | null => {
      const lines = carts[slug] ?? [];
      if (lines.length === 0) return null;
      return {
        amount_minor: lines.reduce(
          (sum, line) => sum + line.item.price.amount_minor * line.quantity,
          0,
        ),
        currency: lines[0].item.price.currency,
      };
    },
    [carts],
  );

  const value = useMemo(
    () => ({ hydrated, linesFor, countFor, totalFor, add, setQuantity, clear }),
    [add, clear, countFor, hydrated, linesFor, setQuantity, totalFor],
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be used inside CartProvider");
  return context;
}
