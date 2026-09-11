import type { NextConfig } from "next";

/**
 * Proxy moi `/api/*` sang FastAPI (:8020). Có thể đổi bằng ASYS_BACKEND_URL
 * trong service Next; mặc định này giữ đúng môi trường dev.
 *
 * Trinh duyet chi thay mot origin (Next :3000) nen cookie session cua
 * auth.py lanh origin — khong CORS, khong tao CSRF moi. Backend phan tich
 * (Workspace, agents, services) van chay o Python, khong doi gi.
 */
const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  experimental: {
    // Next 15 cat than request o 10 MB khi chuyen qua proxy. Tep bankruptcy
    // 11,4 MB bi cat cut, may chu cho phan con lai mai khong toi, va trang bao
    // "qua thoi gian cho" - sai nguyen nhan. Phai KHOP voi MAX_UPLOAD_BYTES o
    // backend (web/app.py) va o frontend/src/lib/api.ts.
    middlewareClientMaxBodySize: "200mb",
    // Proxy ngam cat moi request o 30 giay (proxyTimeout || 30000). Dat cau hoi
    // mat 1-2 phut, nen phai dai hon LONG_REQUEST_TIMEOUT_MS (15 phut) cua
    // trinh duyet.
    proxyTimeout: 20 * 60 * 1000,
  },
  async rewrites() {
    const backend = process.env.ASYS_BACKEND_URL ?? "http://127.0.0.1:8020";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
