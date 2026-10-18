import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import "./tokens.css";
import AppShell from "@/components/AppShell";

// Inter with a system fallback stack; next/font also injects its own
// size-adjusted fallback automatically.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
  fallback: ["system-ui", "-apple-system", "Segoe UI", "Arial", "sans-serif"],
});

export const metadata: Metadata = {
  title: {
    default: "AgentTrust — Live Dashboard",
    template: "%s · AgentTrust",
  },
  description: "Real-time observability for tool-using AI agents.",
};

// Applies the persisted theme before first paint so there is no flash.
// Default is dark: the script only ever removes the class for an explicit
// "light" preference.
const themeInitScript = `(function(){try{if(localStorage.getItem("agenttrust_theme")==="light"){document.documentElement.classList.remove("dark");}}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className={`${inter.variable} antialiased`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
