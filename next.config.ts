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
        // NOTE: /api/jobs/:jobId/file/* is handled by the Next.js App Router
        // (serves artifacts from disk so video isn't blocked by Manim on :8000).
        {
          source: "/api/jobs/:jobId",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId",
        },
        {
          source: "/api/jobs/:jobId/scenes/:path*",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId/scenes/:path*",
        },
        {
          source: "/api/jobs/:jobId/continue/:path*",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId/continue/:path*",
        },
        {
          source: "/api/jobs/:jobId/events/:path*",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId/events/:path*",
        },
        {
          source: "/api/jobs/:jobId/status",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId/status",
        },
        {
          source: "/api/jobs/:jobId/plan",
          destination: "http://127.0.0.1:8000/api/jobs/:jobId/plan",
        },
        {
          source: "/api/me",
          destination: "http://127.0.0.1:8000/api/me",
        },
        {
          source: "/api/documents",
          destination: "http://127.0.0.1:8000/api/documents",
        },
        {
          source: "/api/documents/:path*",
          destination: "http://127.0.0.1:8000/api/documents/:path*",
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
