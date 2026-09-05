import type { NextConfig } from "next";

const LOCAL_API = "http://127.0.0.1:8000";

/** Proxy FastAPI on this machine. Vercel uses vercel.json instead. */
function shouldProxyLocalApi(): boolean {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) return false;
  if (process.env.VERCEL) return false;
  return true;
}

const nextConfig: NextConfig = {
  async rewrites() {
    // Keep /api/auth/* and /api/mcp on Next.js.
    // /api/jobs/:jobId/file/* is the App Router disk media route.
    if (!shouldProxyLocalApi()) return [];
    return [
      { source: "/api/health", destination: `${LOCAL_API}/api/health` },
      { source: "/api/generate", destination: `${LOCAL_API}/api/generate` },
      {
        source: "/api/generate/:path*",
        destination: `${LOCAL_API}/api/generate/:path*`,
      },
      { source: "/api/jobs", destination: `${LOCAL_API}/api/jobs` },
      { source: "/api/jobs/:jobId", destination: `${LOCAL_API}/api/jobs/:jobId` },
      {
        source: "/api/jobs/:jobId/scenes/:path*",
        destination: `${LOCAL_API}/api/jobs/:jobId/scenes/:path*`,
      },
      {
        source: "/api/jobs/:jobId/continue/:path*",
        destination: `${LOCAL_API}/api/jobs/:jobId/continue/:path*`,
      },
      {
        source: "/api/jobs/:jobId/events/:path*",
        destination: `${LOCAL_API}/api/jobs/:jobId/events/:path*`,
      },
      {
        source: "/api/jobs/:jobId/status",
        destination: `${LOCAL_API}/api/jobs/:jobId/status`,
      },
      {
        source: "/api/jobs/:jobId/plan",
        destination: `${LOCAL_API}/api/jobs/:jobId/plan`,
      },
      { source: "/api/me", destination: `${LOCAL_API}/api/me` },
      { source: "/api/me/:path*", destination: `${LOCAL_API}/api/me/:path*` },
      { source: "/api/documents", destination: `${LOCAL_API}/api/documents` },
      {
        source: "/api/documents/:path*",
        destination: `${LOCAL_API}/api/documents/:path*`,
      },
      { source: "/api/tts/:path*", destination: `${LOCAL_API}/api/tts/:path*` },
      { source: "/api/video/:path*", destination: `${LOCAL_API}/api/video/:path*` },
    ];
  },
};

export default nextConfig;
