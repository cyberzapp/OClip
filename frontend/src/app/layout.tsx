import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OClip Studio — Local AI Video Clipping & Editing",
  description: "Local macOS studio inspired by OpusClip: ClipAnything, Virality Score, Auto Reframe, Animated Captions, AI B-Roll, Speech Cleanup & XML Export.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta name="color-scheme" content="dark" />
      </head>
      <body className="min-h-screen bg-[#08090e] text-gray-100 antialiased">
        {children}
      </body>
    </html>
  );
}
