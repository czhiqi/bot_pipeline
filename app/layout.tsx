import type { Metadata, Viewport } from "next";
import { getLang } from "@/lib/lang-server";
import "./globals.css";

export const metadata: Metadata = {
  title: "FORGE · Strategy Pipeline",
  description: "Hypothesis → backtest → risk → bot. Strategy branches on GitHub, AI-assisted code, the same gates for every bot.",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = { themeColor: "#15114a" };

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang={(await getLang()) === "zh" ? "zh-CN" : "en"}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
