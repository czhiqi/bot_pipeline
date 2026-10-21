/**
 * Creates the app's tables from db/init.sql. Works on MySQL 5.6.5+, 5.7 and 8.x,
 * and needs no mysql command-line client (handy on Windows).
 *
 *   npm run db:init
 *
 * Reads DATABASE_URL from .env.production or .env. Safe to run more than once.
 */
import { readFileSync } from "fs";
import { join } from "path";
import mysql from "mysql2/promise";

async function main() {
  const { DATABASE_URL } = process.env;
  if (!DATABASE_URL) throw new Error("Missing DATABASE_URL. Put it in .env (see .env.example).");

  const sql = readFileSync(join(process.cwd(), "db", "init.sql"), "utf8");
  const conn = await mysql.createConnection({ uri: DATABASE_URL, multipleStatements: true });
  try {
    const [rows] = await conn.query("SELECT VERSION() AS v");
    const version = (rows as { v: string }[])[0]?.v ?? "?";
    console.log(`Connected to MySQL ${version} at ${DATABASE_URL.replace(/:[^:@/]*@/, ":****@")}`);
    await conn.query(sql);

    const [tables] = await conn.query("SHOW TABLES");
    console.log("✅ Tables ready:", (tables as Record<string, string>[]).map((r) => Object.values(r)[0]).join(", "));
  } finally {
    await conn.end();
  }
}

main().catch((err) => {
  console.error("❌ db:init failed:", err);
  process.exit(1);
});
