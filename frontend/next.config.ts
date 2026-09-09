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
