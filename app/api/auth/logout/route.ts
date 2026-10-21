import { clearSessionCookie } from "@/app/auth";

export async function POST() {
  await clearSessionCookie();
  return Response.json({ ok: true });
}
