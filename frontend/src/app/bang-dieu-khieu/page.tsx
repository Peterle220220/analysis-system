import DashboardPage from "@/components/dashboard-page";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Dashboard | Analysis System",
  description: "Ghép kết luận AI, biểu đồ Tự phân tích và hộp văn bản trên một lưới.",
};

/**
 * Khong gian trinh bay: widget ghim tu hai luong va hop van ban tren luoi keo tha.
 * Suspense boc ngoai vi trang doc `?bang=` tu dia chi.
 */
export default function Page() {
  return (
    <Suspense fallback={<p className="status-line">Đang mở…</p>}>
      <DashboardPage />
    </Suspense>
  );
}
