import AppShell from "@/components/app-shell";
import { DashboardContent } from "@/components/read-pages";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard — Analysis System",
  description: "Ghép các kết luận thành một báo cáo.",
};

/** Dashboard đọc material đã có từ API Python để người dùng mở lại dataset. */
export default function DashboardPage() {
  return <AppShell><DashboardContent /></AppShell>;
}
