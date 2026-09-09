import AppShell from "@/components/app-shell";
import { HomeContent } from "@/components/read-pages";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Analysis System",
  description: "Trang chủ — giao diện mới của analysis-system.",
};

/**
 * Pha 0: chi can vong dang nhap chay thong. Trang 4 chinh se duoc do vao
 * Pha 1; noi dung nay chi la cho de kiem tra "login round-trip" tren :3000.
 */
export default function HomePage() {
  return <AppShell><HomeContent /></AppShell>;
}
