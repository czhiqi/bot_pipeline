import { defineConfig } from "drizzle-kit";

// Google Cloud SQL connection string, e.g.
//   mysql://<user>:<password>@<host>:3306/<database>
// Populate DATABASE_URL in a local `.env` (dev) or `.env.production`
// (deploy) file — see `.env.example`.
export default defineConfig({
  out: "./drizzle",
  schema: "./db/schema.ts",
  dialect: "mysql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "",
  },
});
