import { createHmac, timingSafeEqual } from "crypto";

const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("hex");
}

/** Creates a `userId.expiresAt.signature` token, verifiable without server-side storage. */
export function createSessionToken(userId: number, secret: string): string {
  const expiresAt = Date.now() + SESSION_TTL_MS;
  const payload = `${userId}.${expiresAt}`;
  return `${payload}.${sign(payload, secret)}`;
}

/** Returns the userId encoded in the token if its signature is valid and it hasn't expired. */
export function verifySessionToken(token: string, secret: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  const [userIdRaw, expiresAtRaw, signature] = parts;
  const payload = `${userIdRaw}.${expiresAtRaw}`;
  const expectedSignature = sign(payload, secret);

  const signatureBuffer = Buffer.from(signature, "hex");
  const expectedBuffer = Buffer.from(expectedSignature, "hex");
  if (signatureBuffer.length !== expectedBuffer.length || !timingSafeEqual(signatureBuffer, expectedBuffer)) {
    return null;
  }

  const expiresAt = Number(expiresAtRaw);
  if (!Number.isFinite(expiresAt) || expiresAt < Date.now()) return null;

  const userId = Number(userIdRaw);
  return Number.isFinite(userId) ? userId : null;
}
