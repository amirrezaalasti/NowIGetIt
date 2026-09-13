import type { Metadata } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import { AuthProvider } from "@/components/AuthProvider";
import { AuthTokenBridge } from "@/components/AuthTokenBridge";
import { ThemeProvider, themeInitScript } from "@/components/ThemeProvider";
import "./globals.css";

const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const sans = Source_Sans_3({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://nowigetit.app"),
  title: "Now I Get It — Explain it until it clicks",
  description:
    "Turn a prompt into a scene-planned educational video with VLM review and voiceover.",
  openGraph: {
    title: "Now I Get It",
    description: "Turn ideas into understanding.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Now I Get It",
    description: "Turn ideas into understanding.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-screen flex flex-col">
        <AuthProvider>
          <AuthTokenBridge />
          <ThemeProvider>{children}</ThemeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
