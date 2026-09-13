"use client";

import { useEffect, useState } from "react";
import { otherTheme, readTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

function Moon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>;
}

function Sun() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>;
}

/** Cong tac Sang/Toi. Bat (aria-checked) nghia la dang o giao dien toi. */
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    let stored: string | null = null;
    try { stored = localStorage.getItem(THEME_STORAGE_KEY); } catch { stored = null; }
    setTheme(readTheme(stored));
  }, []);

  function flip() {
    const next = otherTheme(theme);
    setTheme(next);
    document.documentElement.dataset.theme = next;
    // Khong luu duoc (che do rieng tu) thi van doi trong phien nay.
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch { /* bo qua */ }
  }

  const dark = theme === "dark";
  const label = dark ? "Giao diện tối" : "Giao diện sáng";
  return (
    <button type="button" role="switch" aria-checked={dark} aria-label="Giao diện tối" className="theme-toggle" onClick={flip} title={dark ? "Đổi sang giao diện sáng" : "Đổi sang giao diện tối"}>
      <span className="theme-track" aria-hidden="true"><span className="theme-thumb">{dark ? <Moon /> : <Sun />}</span></span>
      <span className="nav-copy theme-label">{label}</span>
    </button>
  );
}
