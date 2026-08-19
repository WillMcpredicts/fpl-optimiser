import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "FPL Optimiser",
  description: "Predicted points, trends and transfer planning",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB">
      <body>{children}</body>
    </html>
  );
}
