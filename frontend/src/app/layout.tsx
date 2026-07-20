import type { Metadata } from "next";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import AppAuthProvider from "@/components/AppAuthProvider";
import { SessionProvider } from "@/components/SessionProvider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Serif for assistant narrative — the defining trait of the Claude-style reading surface.
const serif = Source_Serif_4({
  variable: "--font-serif",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CSA Workbench",
  description: "CSA Workbench — the agent-powered engagement workspace for solution architects",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${serif.variable} font-sans antialiased`}
      >
        <AppAuthProvider>
          <SessionProvider>{children}</SessionProvider>
        </AppAuthProvider>
      </body>
    </html>
  );
}
