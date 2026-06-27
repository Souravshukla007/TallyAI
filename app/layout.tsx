import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "TallyAI — Ask your database anything",
  description:
    "Plain-English questions in. Safe, explainable SQL and consultant-level insights out. Read-only by default with grounded answers.",
  openGraph: {
    title: "TallyAI — Ask your database anything",
    description:
      "Plain-English questions in. Safe, explainable SQL and consultant-level insights out.",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
