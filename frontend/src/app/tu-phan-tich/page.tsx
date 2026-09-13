import BiBuilder from "@/components/bi-builder";
import type { Metadata } from "next";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "Tự phân tích | Analysis System",
  description: "Kéo thả cột để tự vẽ biểu đồ từ dữ liệu đã làm sạch.",
};

/**
 * Khung keo tha tu phan tich; moi con so do DuckDB tinh, khong qua model.
 * Suspense boc ngoai vi trang doc `?bo=&ban=` tu dia chi.
 */
export default function SelfServicePage() {
  return (
    <Suspense fallback={<p className="status-line">Đang mở…</p>}>
      <BiBuilder />
    </Suspense>
  );
}
