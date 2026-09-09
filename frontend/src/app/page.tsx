import AppShell from "@/components/app-shell";
import { HomeContent } from "@/components/read-pages";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Analysis System",
  description: "Trang chủ — giao diện mới của analysis-system.",
};

/** Trang chủ thật: upload và danh sách dataset được đọc từ API Python. */
export default function HomePage() {
  return <AppShell><HomeContent /></AppShell>;
}
