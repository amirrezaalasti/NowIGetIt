import type { Metadata } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import { AuthProvider } from "@/components/AuthProvider";
import { AuthTokenBridge } from "@/components/AuthTokenBridge";
import { ThemeProvider, themeInitScript } from "@/components/ThemeProvider";
import "./globals.css";

const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
});

const sans = Source_Sans_3({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NowIGetIt — Explain it until it clicks",
  description:
    "Turn a prompt into a scene-planned educational video with VLM review and voiceover.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <AuthProvider>
          <AuthTokenBridge />
          <ThemeProvider>{children}</ThemeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
