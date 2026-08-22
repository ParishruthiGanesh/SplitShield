import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SplitShield — dataset leakage auditing",
  description:
    "Detect, repair, and quantify hidden leakage in computer-vision datasets.",
};

function Nav() {
  return (
    <header className="border-b border-edge/70 bg-raised/70 backdrop-blur sticky top-0 z-40">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3"
      >
        <Link
          href="/"
          className="flex items-center gap-2 font-semibold tracking-tight text-ink"
        >
          <ShieldMark />
          SplitShield
        </Link>
        <div className="ml-auto flex items-center gap-5 text-sm text-muted">
          <Link href="/upload" className="hover:text-ink">
            Analyze
          </Link>
          <Link href="/methodology" className="hover:text-ink">
            Methodology
          </Link>
          <a
            href="http://localhost:8000/docs"
            className="hover:text-ink"
            target="_blank"
            rel="noreferrer"
          >
            API
          </a>
        </div>
      </nav>
    </header>
  );
}

function ShieldMark() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="text-accent"
    >
      <path
        d="M12 2 4 5.5v5.7c0 4.9 3.4 9.4 8 10.8 4.6-1.4 8-5.9 8-10.8V5.5L12 2Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M12 2v20" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2.5 2.5" />
    </svg>
  );
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-6xl px-4 pb-24">{children}</main>
        <footer className="border-t border-edge/60 py-6 text-center text-xs text-muted">
          SplitShield · analysis runs locally · no facial recognition, no identity
          inference · uploads auto-delete after the retention window
        </footer>
      </body>
    </html>
  );
}
