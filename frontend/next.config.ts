import type { NextConfig } from "next";

/**
 * Proxy moi `/api/*` sang FastAPI (:8000).
 *
 * Trinh duyet chi thay mot origin (Next :3000) nen cookie session cua
 * auth.py lanh origin — khong CORS, khong tao CSRF moi. Backend phan tich
 * (Workspace, agents, services) van chay o Python, khong doi gi.
 */
const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
