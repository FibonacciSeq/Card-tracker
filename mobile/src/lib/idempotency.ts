import * as Crypto from "expo-crypto";

export function newIdempotencyKey(): string {
  return Crypto.randomUUID();
}
