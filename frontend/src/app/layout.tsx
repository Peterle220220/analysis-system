import type { Metadata } from "next";
import "./globals.css";
import AppShell from "@/components/app-shell";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

// Bieu tuong tab: Next tu sinh the <link rel="icon"> tu src/app/icon.png.
export const metadata: Metadata = {
  title: "Analysis System",
  description:
    "Bảng điều khiển phân tích dữ liệu, giao diện mới dựng trên JSON từ FastAPI.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // data-theme="dark" ngay tu HTML: tat JavaScript van la giao dien toi. Doan
  // script trong <head> doi sang lua chon da luu truoc khi trang ve.
  return (
    <html lang="vi" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
