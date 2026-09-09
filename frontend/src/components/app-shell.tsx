"use client";

import Sidebar, { NAV_STORAGE_KEY } from "@/components/sidebar";
import SignInForm from "@/components/sign-in";
import { describeError } from "@/lib/api";
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
  const [logoutError, setLogoutError] = useState("");
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [sessionAttempt, setSessionAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    getSession()
      .then((state) => {
        if (alive) {
          setSessionError("");
          setSignedIn(state.signed_in);
        }
      })
      .catch((reason: unknown) => {
        if (alive) setSessionError(describeError(reason, "Máy chủ không trả lời. Kiểm tra kết nối rồi thử lại."));
      });
    return () => {
      alive = false;
    };
  }, [sessionAttempt]);

  // Khoi phuc trang thai thu/mo thanh dieu huong da nho truoc do.
  useEffect(() => {
    setNavCollapsed(localStorage.getItem(NAV_STORAGE_KEY) === "off");
  }, []);

  const rememberNav = (collapsed: boolean) => {
    setNavCollapsed(collapsed);
    localStorage.setItem(NAV_STORAGE_KEY, collapsed ? "off" : "on");
  };

  async function logout() {
    if (logoutBusy) return;
    const guard = new Event("asys:before-navigation", { cancelable: true });
    if (!window.dispatchEvent(guard)) return;
    setLogoutBusy(true);
    setLogoutError("");
    try {
      await signOut();
      setSignedIn(false);
    } catch (reason) {
      setLogoutError(describeError(reason, "Máy chủ không trả lời. Kiểm tra kết nối rồi thử lại."));
    } finally {
      setLogoutBusy(false);
    }
  }

  if (signedIn === null) {
    return (
      <>
        <Brand />
        <main>
          {sessionError ? (
            <div className="card err">
              <p>{sessionError}</p>
              <button type="button" onClick={() => { setSignedIn(null); setSessionAttempt((value) => value + 1); }}>Thử lại</button>
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
        <SignInForm onSignedIn={() => setSignedIn(true)} />
        </main>
      </>
    );
  }

  return (
    <>
      <div className={`with-aside${navCollapsed ? " nav-off" : ""}`}>
        <Sidebar collapsed={navCollapsed} onToggle={rememberNav} onSignOut={logout} signOutBusy={logoutBusy} />
        <main>
          {logoutError && <div className="card err" role="alert"><p>Chưa đăng xuất được: {logoutError}</p><button type="button" onClick={logout}>Thử lại</button></div>}
          {children}
        </main>
      </div>
    </>
  );
}

function Brand({ signedIn = false, onSignOut, signOutBusy = false }: { signedIn?: boolean; onSignOut?: () => void; signOutBusy?: boolean }) {
  return (
    <header className="brand-bar">
      <span className="brand">Analysis System</span>
      <span className="tagline">bảng điều khiển</span>
      {signedIn && onSignOut && <button className="brand-action" type="button" onClick={onSignOut} disabled={signOutBusy}>{signOutBusy ? "Đang đăng xuất…" : "Đăng xuất"}</button>}
    </header>
  );
}
