import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Workflow Designer",
  description:
    "Design and visualize intelligent, multi-step workflows from natural language requirements.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 antialiased font-sans overflow-hidden">
        {children}
      </body>
    </html>
  );
}
