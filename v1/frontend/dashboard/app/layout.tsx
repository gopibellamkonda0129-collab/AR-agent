import type { Metadata } from "next";
import type { ReactNode } from "react";
import Nav from "./Nav";
import Header from "./Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "AR Agent — Receivables Assistant",
  description:
    "Connect your inbox and invoice ledger. The AI finds who owes you money, understands why they're late, tells you what to do next, and prepares the follow-up for you.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          <div className="app-main">
            <Header />
            <main className="app-shell-main">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}