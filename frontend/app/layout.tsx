import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Operations AI",
  description: "Support operations console with a human-approved AI investigator (simulated environment).",
};

const BANNER = process.env.NEXT_PUBLIC_DEMO_BANNER ?? "Demo environment — all refunds and messages are simulated.";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <div role="note" className="bg-warn-soft px-4 py-1.5 text-center text-xs font-medium text-warn" data-testid="demo-banner">
          {BANNER}
        </div>
        {children}
      </body>
    </html>
  );
}
