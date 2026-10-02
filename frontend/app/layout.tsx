import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import Providers from "@/components/Providers";
import { StatusBar } from "@/components/StatusBar";
import { Disclaimer } from "@/components/ui";

export const metadata: Metadata = { title: "FinIntel — research terminal", description: "Financial research and validated quantitative forecasting" };

const NAV = [["/", "Overview"], ["/screener", "Screener"], ["/forecasts", "Forecasts"], ["/macro", "Macro"], ["/performance", "Model performance"]];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <Providers>
          <header className="border-b" style={{ borderColor: "var(--line)", background: "var(--panel)" }}>
            <nav className="mx-auto flex max-w-[1400px] items-center gap-6 px-4 py-3 text-sm" aria-label="Main">
              <Link href="/" className="font-bold tracking-tight">FinIntel</Link>
              {NAV.map(([h, l]) => <Link key={h} href={h} className="muted hover:underline">{l}</Link>)}
            </nav>
            <StatusBar />
          </header>
          <main className="mx-auto max-w-[1400px] space-y-4 px-4 py-5">{children}</main>
          <footer className="mx-auto max-w-[1400px] px-4 pb-8"><Disclaimer /></footer>
        </Providers>
      </body>
    </html>
  );
}
