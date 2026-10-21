"use client";

/** POSTs JSON and returns { ok, error } — error is a dictionary key or message from the API. */
export async function postJson(url: string, body?: unknown): Promise<{ ok: boolean; error?: string; data?: Record<string, unknown> }> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) return { ok: false, error: String(data.error ?? "errGeneric"), data };
    return { ok: true, data };
  } catch {
    return { ok: false, error: "errGeneric" };
  }
}

/** POSTs multipart form data (file uploads). Same return shape as postJson. */
export async function postForm(url: string, body: FormData): Promise<{ ok: boolean; error?: string; data?: Record<string, unknown> }> {
  try {
    const res = await fetch(url, { method: "POST", body });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) return { ok: false, error: String(data.error ?? "errGeneric"), data };
    return { ok: true, data };
  } catch {
    return { ok: false, error: "errGeneric" };
  }
}

/** Error text for an API result, including the upstream message (GitHub, Gemini, OpenRouter) when present. */
export function apiErr(t: Record<string, string>, r: { error?: string; data?: Record<string, unknown> }) {
  const base = errText(t, r.error);
  const msg = r.data?.message;
  return typeof msg === "string" && msg ? `${base}: ${msg}` : base;
}

/** Looks up an API error key in the dictionary, falling back to the raw message. */
export function errText(t: Record<string, string>, key?: string) {
  if (!key) return t.errGeneric;
  return t[key] ?? key;
}
