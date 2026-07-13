import type { Metadata } from "next";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import AuthGate from "@/components/AuthGate";
import SignInGate from "@/components/SignInGate";
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
  title: "Personal Assistant",
  description: "Personal Assistant — AI assistant for personal productivity",
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
        {/* AuthGate (caller auth) > SignInGate (app user, spec F1) > SessionProvider: the
            agent session 401s without a signed-in user, so the provider must not mount
            until the gate has a token. One continuous session across all routes. */}
        <AuthGate>
          <SignInGate>
            <SessionProvider>{children}</SessionProvider>
          </SignInGate>
        </AuthGate>
      </body>
    </html>
  );
}
