/**
 * True when the request comes from this site. Browsers always send Origin on
 * POST fetches, so a missing or foreign Origin blocks cross-site (CSRF) posts —
 * including multipart form posts, which browsers *can* send cross-site.
 */
export function sameOrigin(request: Request, requireHeader = false): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return !requireHeader;
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * Reads a JSON body from a same-origin request. Rejecting non-JSON content
 * types and foreign Origin headers blocks cross-site form (CSRF) posts,
 * since browsers can't send application/json cross-site without CORS.
 */
export async function readJson<T>(request: Request): Promise<T | Response> {
  const ct = request.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) {
    return Response.json({ error: "unsupported_media_type" }, { status: 415 });
  }
  if (!sameOrigin(request)) return Response.json({ error: "bad_origin" }, { status: 403 });
  try {
    return (await request.json()) as T;
  } catch {
    return Response.json({ error: "bad_json" }, { status: 400 });
  }
}

export function fail(error: string, status = 400, extra: Record<string, unknown> = {}) {
  return Response.json({ error, ...extra }, { status });
}
