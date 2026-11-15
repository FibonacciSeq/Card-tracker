export const SHOP_RADIUS_OPTIONS = [5, 10, 25, 50] as const;

export type ShopRadiusKm = (typeof SHOP_RADIUS_OPTIONS)[number];

export type ShopNear = {
  latitude: number;
  longitude: number;
  radiusKm: ShopRadiusKm;
};

/** Formats a backend distance for the compact shop-card meta row. */
export function formatDistanceKm(distanceKm: number): string {
  if (!Number.isFinite(distanceKm) || distanceKm < 0) return "";
  if (distanceKm < 1) {
    const roundedMeters = Math.max(10, Math.round((distanceKm * 1000) / 10) * 10);
    return roundedMeters < 1000 ? `${roundedMeters} m` : "1.0 km";
  }
  if (distanceKm < 10) return `${distanceKm.toFixed(1)} km`;
  return `${Math.round(distanceKm)} km`;
}
