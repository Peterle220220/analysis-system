"use client";

import Sidebar, { NAV_STORAGE_KEY } from "@/components/sidebar";
import SignInForm from "@/components/sign-in";
import { getSession, signOut } from "@/lib/session";
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
  const [sessionError, setSessionError] = useState("");
  const [navCollapsed, setNavCollapsed] = useState(false);

  useEffect(() => {
    let alive = true;
    getSession()
      .then((state) => {
        if (alive) setSignedIn(state.signed_in);
      })
      .catch(() => {
        if (alive) setSessionError("Máy chủ không trả lời.");
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

  async function logout() {
    await signOut();
    setSignedIn(false);
  }

  if (signedIn === null) {
    return (
      <>
        <Brand />
        <main>
          {sessionError ? (
            <div className="card err">
              <p>{sessionError}</p>
              <button type="button" onClick={() => window.location.reload()}>Thử lại</button>
            </div>
          ) : <p className="status-line">Đang kiểm tra phiên…</p>}
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
      <Brand signedIn onSignOut={logout} />
      <div className={`with-aside${navCollapsed ? " nav-off" : ""}`}>
        <Sidebar collapsed={navCollapsed} onToggle={rememberNav} />
        <main>{children}</main>
      </div>
    </>
  );
}

function Brand({ signedIn = false, onSignOut }: { signedIn?: boolean; onSignOut?: () => void }) {
  return (
    <header className="brand-bar">
      <span className="brand">Analysis System</span>
      <span className="tagline">bảng điều khiển</span>
      {signedIn && onSignOut && <button type="button" onClick={onSignOut}>Đăng xuất</button>}
    </header>
  );
}
