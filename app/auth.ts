import { eq } from "drizzle-orm";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getDb } from "@/db";
import { users } from "@/db/schema";
import { createSessionToken, verifySessionToken } from "@/lib/session";

const SESSION_COOKIE = "session";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7; // 7 days

export type SessionUser = {
  id: number;
  email: string;
  displayName: string;
  isAdmin: boolean;
};

function sessionSecret(): string {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("SESSION_SECRET must be set to a random string of at least 32 characters.");
  }
  return secret;
}

/** Admins are configured by email in ADMIN_EMAILS (comma-separated). */
export function isAdminEmail(email: string): boolean {
  return (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean)
    .includes(email.toLowerCase());
}

export async function getSessionUser(): Promise<SessionUser | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE)?.value;
  if (!token) return null;

  const userId = verifySessionToken(token, sessionSecret());
  if (!userId) return null;

  const [user] = await getDb()
    .select({ id: users.id, email: users.email, displayName: users.displayName})
    .from(users)
    .where(eq(users.id, userId))
    .limit(1);

  return user ? { ...user, isAdmin: isAdminEmail(user.email) } : null;
}

/** Server Components: redirects to /login if not signed in. */
export async function requireSessionUser(returnTo: string): Promise<SessionUser> {
  const user = await getSessionUser();
  if (user) return user;
  redirect(`/login?return_to=${encodeURIComponent(returnTo)}`);
}

/** Server Components: redirects non-admins to the workspace. */
export async function requireAdminPage(): Promise<SessionUser> {
  const user = await requireSessionUser("/admin");
  if (!user.isAdmin) redirect("/workspace");
  return user;
}

/** Route Handlers: returns the user or a 401/403 Response. */
export async function apiUser(opts: { admin?: boolean } = {}): Promise<SessionUser | Response> {
  const user = await getSessionUser();
  if (!user) return Response.json({ error: "unauthorized" }, { status: 401 });
  if (opts.admin && !user.isAdmin) return Response.json({ error: "forbidden" }, { status: 403 });
  return user;
}

/**
 * Browsers drop "secure" cookies on plain-http sites, which makes login bounce back
 * to /login. Defaults to secure in production; set COOKIE_SECURE=false while the
 * site is served over http (e.g. http://your-domain:3002), and remove it once on https.
 */
function cookieSecure(): boolean {
  const v = process.env.COOKIE_SECURE?.trim().toLowerCase();
  if (v === "false" || v === "0") return false;
  if (v === "true" || v === "1") return true;
  return process.env.NODE_ENV === "production";
}

export async function setSessionCookie(userId: number): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, createSessionToken(userId, sessionSecret()), {
    httpOnly: true,
    secure: cookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export async function clearSessionCookie(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
}
