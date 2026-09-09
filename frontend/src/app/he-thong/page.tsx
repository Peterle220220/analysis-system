import AppShell from "@/components/app-shell";
import { SystemContent } from "@/components/read-pages";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Hệ thống — Analysis System",
  description: "Phiên bản đang chạy và cập nhật code mới.",
};

/**
 * Cho den khi Pha 1 do noi dung that vao, trang nay chi la dich den cua muc
 * Hệ thống tren Sidebar — de thu duoc trang thai dang mo cua thanh dieu huong.
 */
export default function SystemPage() {
  return <AppShell><SystemContent /></AppShell>;
}
