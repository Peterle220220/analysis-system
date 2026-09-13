// Giao dien Sang/Toi. Mac dinh la TOI: doc so lieu lau thi do moi mat. Chi mot
// lua chon "light" da luu moi cho ra giao dien sang. Khong import gi, de test
// duoc bang Node tran.

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "asys.theme";

/** Giao dien tu gia tri da luu; thieu hay la thi ve mac dinh la toi. */
export function readTheme(stored: string | null | undefined): Theme {
  return stored === "light" ? "light" : "dark";
}

export function otherTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}

/**
 * Chay trong <head> truoc khi trang ve, de khong nhay trang roi moi toi.
 * Khong doc duoc localStorage (che do rieng tu, bi chan) thi van la toi.
 */
export const THEME_BOOT_SCRIPT =
  `try{document.documentElement.dataset.theme=` +
  `localStorage.getItem("${THEME_STORAGE_KEY}")==="light"?"light":"dark"}` +
  `catch(e){document.documentElement.dataset.theme="dark"}`;
