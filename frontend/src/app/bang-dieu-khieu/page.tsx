import AppShell from "@/components/app-shell";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Dashboard — Analysis System",
  description: "Ghép các kết luận thành một báo cáo.",
};

/**
 * Cho den khi Pha 1 do noi dung that vao, trang nay chi la dich den cua muc
 * Dashboard tren Sidebar — de thu duoc trang thai dang mo cua thanh dieu huong.
 */
export default function DashboardPage() {
  return (
    <AppShell>
      <h1>Dashboard</h1>
      <p className="status-line">
        Ghép các kết luận thành một báo cáo. Nội dung sẽ được dựng trong Pha 1.
      </p>
    </AppShell>
  );
}
