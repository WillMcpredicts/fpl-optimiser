/**
 * Single-password gate (section 1: personal-use tool, no multi-tenant auth).
 *
 * The cookie holds an HMAC of a fixed marker, so it cannot be forged without
 * AUTH_SECRET, and it carries no user data. Web Crypto is used rather than
 * node:crypto so the same code runs in Edge middleware.
 */
const MARKER = "fpl-optimiser-authenticated";

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export const COOKIE_NAME = "fplo_session";

export async function sessionToken(): Promise<string> {
  const secret = process.env.AUTH_SECRET;
  if (!secret) throw new Error("AUTH_SECRET is not set");
  return hmac(secret, MARKER);
}

export async function isValidToken(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const secret = process.env.AUTH_SECRET;
  if (!secret) return false;
  const expected = await hmac(secret, MARKER);
  // Constant-time compare: length first, then accumulate differences.
  if (token.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < token.length; i++) diff |= token.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

/** True when no password is configured, which leaves the app open. */
export function gateDisabled(): boolean {
  return !process.env.APP_PASSWORD || !process.env.AUTH_SECRET;
}
