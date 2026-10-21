import { setSessionCookie } from "@/app/auth";
import { getDb } from "@/db";
import { createUser, findUserByEmail } from "@/db/queries";
import { fail, readJson } from "@/lib/http";
import { hashPassword } from "@/lib/password";

export async function POST(request: Request) {
  try {
    const body = await readJson<{ email?: string; password?: string; displayName?: string; agreeTerms?: boolean }>(request);
    if (body instanceof Response) return body;
    const email = body.email?.trim().toLowerCase() ?? "";
    const password = body.password ?? "";
    const displayName = body.displayName?.trim().slice(0, 100) ?? "";

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return fail("errInvalidEmail");
    if (password.length < 8) return fail("errPassword");
    if (!displayName) return fail("errName");
    if (body.agreeTerms !== true) return fail("agreeTerms");

    const db = getDb();
    if (await findUserByEmail(db, email)) return fail("errEmailTaken", 409);

    const user = await createUser(db, { email, passwordHash: await hashPassword(password), displayName });
    await setSessionCookie(user.id);
    return Response.json({ ok: true }, { status: 201 });
  } catch (error) {
    console.error("[api/auth/register] failed:", error);
    return fail("errGeneric", 500);
  }
}
