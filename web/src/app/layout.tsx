import type { Metadata, Viewport } from "next";
import { Header } from "@/components/Header";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "Internship Board KZ",
  description: "Internships for students in Kazakhstan, collected from many sources, de-duplicated and ranked for you.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f5f6e" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <AuthProvider>
          <Header />
          <main id="main" className="container main">
            {children}
          </main>
          <footer className="site-footer container muted small">
            Postings are collected from public sources and always link back to the original. Unknown means the posting
            doesn&apos;t say, so we don&apos;t guess. Team 26 · Nazarbayev University.
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
