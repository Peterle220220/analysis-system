"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Thanh dieu huong chinh — ban Next.js cua MAIN_NAV trong render.py.
 *
 * Bon muc giong het phien ban SSR: Home, Data, Dashboard, He thong. Muc dang
 * mo duoc danh dau `.here` (va aria-current) tu `usePathname()` — thay cho tham
 * so `here` ma render.py truyen xuong. Nut ◀/▶ thu/mo thanh, nho trang thai
 * trong localStorage["asys.nav"] nen chuyen trang van giu nguyen.
 */

export type NavItem = {
  href: string;
  name: string;
  hint: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", name: "Home", hint: "Đưa dữ liệu vào và xem việc đang chạy" },
  { href: "/du-lieu", name: "Data", hint: "Các bộ dữ liệu đã và đang xử lý" },
  { href: "/bang-dieu-khieu", name: "Dashboard", hint: "Ghép các kết luận thành một báo cáo" },
  { href: "/he-thong", name: "Hệ thống", hint: "Phiên bản đang chạy và cập nhật code mới" },
];

/** Cung key voi SSR: trang cu va trang moi chia se mot trang thai thu/mo. */
export const NAV_STORAGE_KEY = "asys.nav";

/** Trang chi tiet (vi du /bo/r_web) van tinh la dang o duoi muc Data. */
function isHere(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href);
}

export default function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: (next: boolean) => void;
}) {
  // usePathname() chi co gia tri that sau khi thu du lieu route; giong nhau o
  // moi lan render cung mot duong dan, nen khong gay nhap nhang noi dung.
  const pathname = usePathname() ?? "/";

  return (
    <nav className="aside" aria-label="Điều hướng chính">
      <button
        type="button"
        className="nav-toggle"
        aria-pressed={collapsed}
        title={collapsed ? "Mở thanh điều hướng" : "Thu thanh điều hướng"}
        onClick={() => onToggle(!collapsed)}
      >
        <span className="tat" aria-hidden="true">
          ◀
        </span>
        <span className="mo" aria-hidden="true">
          ▶
        </span>
      </button>
      <ul className="nav">
        {NAV_ITEMS.map(({ href, name, hint }) => {
          const here = isHere(href, pathname);
          return (
            <li key={href}>
              <Link
                href={href}
                className={here ? "here" : undefined}
                title={hint}
                aria-current={here ? "page" : undefined}
              >
                {name}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
