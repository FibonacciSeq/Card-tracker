/**
 * In-store QR codes carry a link into the customer app.
 *
 * Canonical payloads:
 *   cardtracker://shop/<slug>
 *   cardtracker://shop/<slug>/card/<stock-id>
 *
 * The parser also accepts the same paths from http(s) links and Expo Go
 * (`exp://host/--/shop/<slug>`), plus a bare path or shop slug typed by hand.
 * Anything else is rejected so a scanned foreign QR code cannot open an
 * arbitrary route.
 */

export type ScanTarget =
  | { kind: "shop"; slug: string }
  | { kind: "card"; slug: string; stockId: string };

const SLUG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ALLOWED_SCHEMES = new Set(["cardtracker", "exp", "exps", "http", "https"]);
const MAX_INPUT_LENGTH = 2048;

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Reads `[shop, <slug>]` or `[shop, <slug>, card, <stock-id>]`. */
export function targetFromPath(path: string): ScanTarget | null {
  const segments = path
    .split(/[?#]/)[0]
    .split("/")
    .filter(Boolean)
    .map(safeDecode);

  if (segments[0] !== "shop") return null;

  const slug = segments[1];
  if (!slug || !SLUG_PATTERN.test(slug)) return null;

  const rest = segments.slice(2);
  if (rest.length === 0) return { kind: "shop", slug };
  if (rest.length === 2 && rest[0] === "card" && UUID_PATTERN.test(rest[1])) {
    return { kind: "card", slug, stockId: rest[1] };
  }
  return null;
}

export function targetFromUrl(raw: string): ScanTarget | null {
  const input = raw.trim();
  if (!input || input.length > MAX_INPUT_LENGTH) return null;

  const match = /^([a-z][a-z0-9+.-]*):\/\/(.*)$/i.exec(input);
  if (!match) return targetFromPath(input);

  const scheme = match[1].toLowerCase();
  if (!ALLOWED_SCHEMES.has(scheme)) return null;

  if (scheme === "http" || scheme === "https" || scheme === "exp" || scheme === "exps") {
    let url: URL;
    try {
      url = new URL(input);
    } catch {
      return null;
    }
    const marker = url.pathname.indexOf("/--/");
    return targetFromPath(marker >= 0 ? url.pathname.slice(marker + 4) : url.pathname);
  }

  // Custom schemes such as `cardtracker://shop/<slug>` put the first path
  // segment in the URL host, so parse everything after the scheme ourselves.
  return targetFromPath(match[2]);
}

/** Accepts a scanned link, a path, or a shop slug typed by hand. */
export function targetFromInput(raw: string): ScanTarget | null {
  const input = raw.trim();
  if (!input || input.length > MAX_INPUT_LENGTH) return null;

  const parsed = targetFromUrl(input);
  if (parsed) return parsed;
  if (SLUG_PATTERN.test(input)) return { kind: "shop", slug: input };
  return null;
}

/** Route path used with `router.push` / `router.dismissTo`. */
export function targetPath(target: ScanTarget): string {
  const base = `/shop/${encodeURIComponent(target.slug)}`;
  return target.kind === "card"
    ? `${base}/card/${encodeURIComponent(target.stockId)}`
    : base;
}

/** Link encoded into a shop's printed QR code. */
export function shopDeepLink(slug: string): string {
  return `cardtracker://shop/${encodeURIComponent(slug)}`;
}

export function cardDeepLink(slug: string, stockId: string): string {
  return `${shopDeepLink(slug)}/card/${encodeURIComponent(stockId)}`;
}
