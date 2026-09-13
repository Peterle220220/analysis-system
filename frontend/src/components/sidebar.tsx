"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import ThemeToggle from "@/components/theme-toggle";

/** Thanh điều hướng chính của giao diện Next.js. */
export type NavItem = {
  href: string;
  name: string;
  hint: string;
  icon: "home" | "data" | "dashboard" | "explore" | "system";
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/", name: "Trang chủ", hint: "Đưa dữ liệu vào và xem việc đang chạy", icon: "home" },
  { href: "/du-lieu", name: "Dữ liệu", hint: "Các bộ dữ liệu đã và đang xử lý", icon: "data" },
  { href: "/bang-dieu-khieu", name: "Dashboard", hint: "Ghép các kết luận thành một báo cáo", icon: "dashboard" },
  { href: "/tu-phan-tich", name: "Tự phân tích", hint: "Kéo thả cột để tự vẽ biểu đồ", icon: "explore" },
  { href: "/he-thong", name: "Hệ thống", hint: "Phiên bản đang chạy và cập nhật code mới", icon: "system" },
];

export const NAV_STORAGE_KEY = "asys.nav";

function isHere(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href);
}

function NavIcon({ name }: { name: NavItem["icon"] }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  if (name === "home") {
    return <svg {...common}><path d="m3 10 9-7 9 7" /><path d="M5 9.5V21h14V9.5" /><path d="M9 21v-7h6v7" /></svg>;
  }
  if (name === "data") {
    return <svg {...common}><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5" /><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" /></svg>;
  }
  if (name === "explore") {
    return <svg {...common}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><path d="M17.5 14v7M14 17.5h7" /></svg>;
  }
  if (name === "dashboard") {
    return <svg {...common}><path d="M4 19V5" /><path d="M4 19h16" /><path d="m7 15 3-4 3 2 4-6" /><path d="M17 7h2v2" /></svg>;
  }
  return <svg {...common}><path d="M12 3v2" /><path d="M12 19v2" /><path d="m4.2 4.2 1.4 1.4" /><path d="m18.4 18.4 1.4 1.4" /><path d="M3 12h2" /><path d="M19 12h2" /><path d="m4.2 19.8 1.4-1.4" /><path d="m18.4 5.6 1.4-1.4" /><circle cx="12" cy="12" r="3.5" /></svg>;
}

function Chevron({ direction }: { direction: "left" | "right" }) {
  return <svg className="nav-chevron" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={direction === "left" ? "m15 18-6-6 6-6" : "m9 18 6-6-6-6"} /></svg>;
}

export default function Sidebar({
  collapsed,
  onToggle,
  onSignOut,
  signOutBusy,
}: {
  collapsed: boolean;
  onToggle: (next: boolean) => void;
  onSignOut: () => void;
  signOutBusy: boolean;
}) {
  const pathname = usePathname() ?? "/";

  return (
    <aside className="aside" aria-label="Điều hướng chính">
      <div className="aside-head">
        <Link className="aside-brand" href="/" aria-label="Về trang chủ Analysis System">
          <img className="aside-mark" src="/logo.png" alt="" aria-hidden="true" width={34} height={34} />
          <span className="aside-brand-copy nav-copy">
            <strong>Analysis System</strong>
            <small>Bảng điều khiển</small>
          </span>
        </Link>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Mở thanh điều hướng" : "Thu thanh điều hướng"}
          title={collapsed ? "Mở thanh điều hướng" : "Thu thanh điều hướng"}
          onClick={() => onToggle(!collapsed)}
        >
          <Chevron direction={collapsed ? "right" : "left"} />
        </button>
      </div>

      <nav className="nav" aria-label="Các trang chính">
        <p className="nav-section-label nav-copy">ĐIỀU HƯỚNG</p>
        <ul>
          {NAV_ITEMS.map(({ href, name, hint, icon }) => {
            const here = isHere(href, pathname);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={`nav-link${here ? " here" : ""}`}
                  aria-label={name}
                  title={collapsed ? hint : undefined}
                  aria-current={here ? "page" : undefined}
                >
                  <span className="nav-icon"><NavIcon name={icon} /></span>
                  <span className="nav-copy nav-link-copy">
                    <strong>{name}</strong>
                    <small>{hint}</small>
                  </span>
                  {collapsed && <span className="nav-tooltip" role="tooltip">{name}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="aside-footer" title={collapsed ? "Phiên đang hoạt động" : undefined}>
        <span className="session-mark" aria-hidden="true"><span /></span>
        <span className="nav-copy aside-footer-copy">
          <strong>Phiên đang hoạt động</strong>
          <small>Đã đăng nhập</small>
        </span>
      </div>
      <ThemeToggle />
      <button className="sidebar-logout" type="button" onClick={onSignOut} disabled={signOutBusy} title="Đăng xuất" aria-label={signOutBusy ? "Đang đăng xuất" : "Đăng xuất"}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M9 4H4v16h5M9 12h12m-4-4 4 4-4 4" /></svg>
        <span className="nav-copy">{signOutBusy ? "Đang đăng xuất…" : "Đăng xuất"}</span>
      </button>
    </aside>
  );
}
