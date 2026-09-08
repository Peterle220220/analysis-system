import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Analysis System",
  description:
    "Bảng điều khiển phân tích dữ liệu — giao diện mới dựng trên JSON từ FastAPI.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
