import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "滨发协同系统",
  description: "ERP 管理系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
