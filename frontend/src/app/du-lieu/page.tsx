import AppShell from "@/components/app-shell";
import { DataContent } from "@/components/read-pages";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Data — Analysis System",
  description: "Các bộ dữ liệu đã và đang xử lý.",
};

/**
 * Cho den khi Pha 1 do noi dung that vao, trang nay chi la dich den cua muc
 * Data tren Sidebar — de thu duoc trang thai dang mo cua thanh dieu huong.
 */
export default function DataPage() {
  return <AppShell><DataContent /></AppShell>;
}
