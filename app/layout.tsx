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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Apply saved theme before paint to avoid a flash of the wrong theme. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var p=JSON.parse(localStorage.getItem('tallyai-prefs')||'{}');var t=p.theme||'system';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d)document.documentElement.classList.add('dark');}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
