import { and, eq, gte, sql } from "drizzle-orm";
import type { MySql2Database } from "drizzle-orm/mysql2";
import * as schema from "./schema";

type Db = MySql2Database<typeof schema>;

export async function findUserByEmail(db: Db, email: string) {
  const [user] = await db
    .select()
    .from(schema.users)
    .where(eq(schema.users.email, email.trim().toLowerCase()))
    .limit(1);
  return user ?? null;
}

export async function createUser(db: Db, params: { email: string; passwordHash: string; displayName: string }) {
  const email = params.email.trim().toLowerCase();
  const [result] = await db.insert(schema.users).values({
    email,
    passwordHash: params.passwordHash,
    displayName: params.displayName.trim() || email,
  });
  return { id: result.insertId };
}

export function affected(result: unknown): number {
  const header = Array.isArray(result) ? result[0] : result;
  return (header as { affectedRows?: number })?.affectedRows ?? 0;
}

function num(v: string | undefined, d: number) {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : d;
}

export function limits() {
  return {
    aiPerHour: num(process.env.AI_CALLS_PER_HOUR, 30),
    strategiesPerUser: num(process.env.MAX_STRATEGIES_PER_USER, 20),
    commitsPerHour: num(process.env.COMMITS_PER_HOUR, 20),
  };
}

/** AI calls a user made in the last hour. */
export async function aiCallsLastHour(db: Db, userId: number): Promise<number> {
  const since = new Date(Date.now() - 3600 * 1000);
  const [row] = await db
    .select({ n: sql<number>`count(*)` })
    .from(schema.aiCalls)
    .where(and(eq(schema.aiCalls.userId, userId), gte(schema.aiCalls.createdAt, since)));
  return Number(row?.n ?? 0);
}

export async function logAiCall(db: Db, row: { userId: number; kind: string; model: string; ok: boolean; tokens?: number | null }) {
  await db.insert(schema.aiCalls).values({ ...row, ok: row.ok ? 1 : 0, tokens: row.tokens ?? null });
}
