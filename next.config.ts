import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Local dev: proxy /api/* to uvicorn when NEXT_PUBLIC_API_BASE_URL is unset
    // and the Python server is on :8000. On Vercel, api/index.py serves /api directly.
    if (process.env.NODE_ENV === "development" && !process.env.NEXT_PUBLIC_API_BASE_URL) {
      return [
        {
          source: "/api/:path*",
          destination: "http://127.0.0.1:8000/api/:path*",
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
