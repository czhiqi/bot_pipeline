import { setSessionCookie } from "@/app/auth";
import { getDb } from "@/db";
import { findUserByEmail } from "@/db/queries";
import { fail, readJson } from "@/lib/http";
import { verifyPassword } from "@/lib/password";

export async function POST(request: Request) {
  try {
    const body = await readJson<{ email?: string; password?: string }>(request);
    if (body instanceof Response) return body;
    const email = body.email?.trim().toLowerCase() ?? "";
    const password = body.password ?? "";
    if (!email || !password) return fail("errLogin", 400);

    const user = await findUserByEmail(getDb(), email);
    if (!user || !(await verifyPassword(password, user.passwordHash))) return fail("errLogin", 401);

    await setSessionCookie(user.id);
    return Response.json({ ok: true });
  } catch (error) {
    console.error("[api/auth/login] failed:", error);
    return fail("errGeneric", 500);
  }
}
