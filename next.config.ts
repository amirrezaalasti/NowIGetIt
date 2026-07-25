import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Local dev: proxy API routes to uvicorn when NEXT_PUBLIC_API_BASE_URL is unset.
    // Keep /api/auth/* on Next.js (Auth.js). On Vercel, api/index.py serves Python /api.
    if (
      process.env.NODE_ENV === "development" &&
      !process.env.NEXT_PUBLIC_API_BASE_URL
    ) {
      return [
        {
          source: "/api/health",
          destination: "http://127.0.0.1:8000/api/health",
        },
        {
          source: "/api/generate",
          destination: "http://127.0.0.1:8000/api/generate",
        },
        {
          source: "/api/generate/:path*",
          destination: "http://127.0.0.1:8000/api/generate/:path*",
        },
        {
          source: "/api/jobs",
          destination: "http://127.0.0.1:8000/api/jobs",
        },
        {
          source: "/api/jobs/:path*",
          destination: "http://127.0.0.1:8000/api/jobs/:path*",
        },
        {
          source: "/api/me",
          destination: "http://127.0.0.1:8000/api/me",
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
