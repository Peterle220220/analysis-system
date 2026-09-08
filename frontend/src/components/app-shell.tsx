"use client";

import Sidebar, { NAV_STORAGE_KEY } from "@/components/sidebar";
import SignInForm from "@/components/sign-in";
import { getSession } from "@/lib/session";
import { useEffect, useState } from "react";

/**
 * Vo ngoai cua giao dien moi: hoi /api/session de biet dang nhap chua.
 * Chua dang nhap -> man hinh dang nhap (khong redirect mu, khong loi 401
 * khi mo trang). Da dang nhap -> cot trai la Sidebar (thanh dieu huong
 * chinh, co the thu/mo) va ben phai la noi dung thuc cua trang.
 */
export default function AppShell({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [navCollapsed, setNavCollapsed] = useState(false);

  useEffect(() => {
    let alive = true;
    getSession().then((state) => {
      if (alive) setSignedIn(state.signed_in);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Khoi phuc trang thai thu/mo thanh dieu huong da nho truoc do.
  useEffect(() => {
    setNavCollapsed(localStorage.getItem(NAV_STORAGE_KEY) === "off");
  }, []);

  const rememberNav = (collapsed: boolean) => {
    setNavCollapsed(collapsed);
    localStorage.setItem(NAV_STORAGE_KEY, collapsed ? "off" : "on");
  };

  if (signedIn === null) {
    return (
      <>
        <Brand />
        <main>
          <p className="status-line">Đang kiểm tra phiên…</p>
        </main>
      </>
    );
  }

  if (!signedIn) {
    return (
      <>
        <Brand />
        <main>
          <SignInForm />
        </main>
      </>
    );
  }

  return (
    <>
      <Brand />
      <div className={`with-aside${navCollapsed ? " nav-off" : ""}`}>
        <Sidebar collapsed={navCollapsed} onToggle={rememberNav} />
        <main>{children}</main>
      </div>
    </>
  );
}

function Brand() {
  return (
    <header className="brand-bar">
      <span className="brand">Analysis System</span>
      <span className="tagline">bảng điều khiển</span>
    </header>
  );
}
