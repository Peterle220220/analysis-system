import AppShell from "@/components/app-shell";
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
  return (
    <AppShell>
      <h1>Data</h1>
      <p className="status-line">
        Các bộ dữ liệu đã và đang xử lý. Nội dung sẽ được dựng trong Pha 1.
      </p>
    </AppShell>
  );
}
