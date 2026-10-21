import mysql from "mysql2/promise";
import { drizzle } from "drizzle-orm/mysql2";
import * as schema from "./schema";

// Connection to Google Cloud SQL for MySQL, over a normal TCP connection.
//
// This app now runs as a plain Next.js app on a regular Node.js server
// (not Cloudflare Workers), so there's no restriction on `mysql2`'s use of
// dynamic code generation — it works exactly as it would in any other
// Node backend.
//
// Required env var: DATABASE_URL, e.g.
//   mysql://<user>:<password>@<host>:3306/<database>
let pool: mysql.Pool | undefined;

function getPool(): mysql.Pool {
  if (pool) return pool;

  const { DATABASE_URL } = process.env;
  if (!DATABASE_URL) {
    throw new Error(
      "MySQL connection env var is missing. Set DATABASE_URL (see .env.example) before using the database."
    );
  }

  pool = mysql.createPool({ uri: DATABASE_URL, timezone: "Z", charset: "utf8mb4" });
  // Drizzle reads and writes TIMESTAMP/DATETIME values as UTC. Pin every
  // connection's session to UTC so times aren't shifted by the server's local zone
  // (e.g. a MySQL in UTC+8 would otherwise show 14:46 as 22:46).
  pool.on("connection", (conn) => {
    conn.query("SET time_zone = '+00:00'");
  });

  return pool;
}

export function getDb() {
  return drizzle(getPool(), { schema, mode: "default" });
}
