import { sql } from "drizzle-orm";
import { datetime, index, int, mediumtext, mysqlEnum, mysqlTable, text, timestamp, tinyint, varchar } from "drizzle-orm/mysql-core";

export const users = mysqlTable("users", {
  id: int("id").autoincrement().primaryKey(),
  // 191 chars keeps the unique index under MySQL 5.x's 767-byte limit with utf8mb4.
  email: varchar("email", { length: 191 }).notNull().unique(),
  passwordHash: varchar("password_hash", { length: 255 }).notNull(),
  displayName: varchar("display_name", { length: 255 }).notNull(),
  createdAt: timestamp("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
});

export const STRATEGY_STATUSES = [
  "draft", // not committed yet, or edited since the last commit
  "testing", // committed; GitHub Actions is running the gates
  "passed", // gates passed on the committed version
  "failed", // gates failed (or the run errored)
  "submitted", // pull request open for review
  "merged", // pull request merged into the base branch
  "archived", // deleted by the user (branch removed)
] as const;
export type StrategyStatus = (typeof STRATEGY_STATUSES)[number];

/**
 * One strategy = one branch (strategy/<slug>) = one bot folder (bots/<slug>/).
 * The draft files live here until they are committed to the branch.
 */
export const strategies = mysqlTable(
  "strategies",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("user_id").notNull(),
    name: varchar("name", { length: 80 }).notNull(),
    slug: varchar("slug", { length: 60 }).notNull().unique(),
    branch: varchar("branch", { length: 120 }).notNull(),
    /** JSON: { idea, expected, invalidation, rules, notes } as typed by the user */
    hypothesis: text("hypothesis").notNull(),
    /** Gemini-polished hypothesis.md (empty = build it from the raw fields) */
    spec: mediumtext("spec").notNull(),
    code: mediumtext("code").notNull(),
    config: text("config").notNull(),
    status: mysqlEnum("status", STRATEGY_STATUSES).notNull().default("draft"),
    /** sha256 of the files at the last commit; differs from the draft = unsaved changes */
    committedHash: varchar("committed_hash", { length: 64 }).notNull().default(""),
    commitSha: varchar("commit_sha", { length: 40 }).notNull().default(""),
    committedAt: datetime("committed_at"),
    gateStatus: varchar("gate_status", { length: 20 }).notNull().default(""),
    gateReport: mediumtext("gate_report"),
    runId: varchar("run_id", { length: 30 }).notNull().default(""),
    runUrl: varchar("run_url", { length: 300 }).notNull().default(""),
    lastCheckedAt: datetime("last_checked_at"),
    prNumber: int("pr_number"),
    prUrl: varchar("pr_url", { length: 300 }).notNull().default(""),
    error: varchar("error", { length: 500 }).notNull().default(""),
    createdAt: timestamp("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
    updatedAt: timestamp("updated_at").notNull().default(sql`CURRENT_TIMESTAMP`).onUpdateNow(),
  },
  (t) => [index("strategies_user_idx").on(t.userId, t.updatedAt), index("strategies_status_idx").on(t.status)]
);

/** One row per AI call, for per-user hourly limits and the admin page. */
export const aiCalls = mysqlTable(
  "ai_calls",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("user_id").notNull(),
    kind: varchar("kind", { length: 20 }).notNull(), // beautify | generate
    model: varchar("model", { length: 120 }).notNull().default(""),
    ok: tinyint("ok").notNull().default(1),
    tokens: int("tokens"),
    createdAt: timestamp("created_at").notNull().default(sql`CURRENT_TIMESTAMP`),
  },
  (t) => [index("ai_calls_user_idx").on(t.userId, t.createdAt)]
);
