/**
 * Table deployment script: applies pending Drizzle migrations to the
 * Google Cloud SQL database described by DATABASE_URL.
 *
 * Usage:
 *   1. npm run db:generate    # turns db/schema.ts changes into SQL under ./drizzle
 *   2. npm run db:deploy      # runs this script against the live database
 *
 * Required env var: DATABASE_URL, e.g.
 *   mysql://<user>:<password>@<host>:3306/<database>
 */
import { drizzle } from "drizzle-orm/mysql2";
import { migrate } from "drizzle-orm/mysql2/migrator";
import mysql from "mysql2/promise";

async function main() {
  const { DATABASE_URL } = process.env;

  if (!DATABASE_URL) {
    throw new Error("Missing DATABASE_URL. See .env.example.");
  }

  const connection = await mysql.createConnection({
    uri: DATABASE_URL,
    multipleStatements: true,
  });

  try {
    const db = drizzle(connection);
    const safeUrl = DATABASE_URL.replace(/:[^:@]*@/, ":****@");
    console.log(`Connecting to ${safeUrl} ...`);
    console.log("Applying pending migrations from ./drizzle ...");
    await migrate(db, { migrationsFolder: "./drizzle" });
    console.log("✅ Migrations applied successfully.");
  } finally {
    await connection.end();
  }
}

main().catch((err) => {
  console.error("❌ Migration failed:", err);
  process.exit(1);
});
