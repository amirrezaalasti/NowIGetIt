import type { NextConfig } from "next";

const LOCAL_API = "http://127.0.0.1:8000";

function isLoopbackApiUrl(value: string | undefined): boolean {
  if (!value) return false;
  try {
    const host = new URL(value).hostname.replace(/^\[|\]$/g, "").toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host === "::1";
  } catch {
    return false;
  }
}

/**
 * Never bake a developer-machine API URL into a hosted client bundle.
 * Vercel CLI / prebuilt deploys can otherwise inline `.env`.
 */
if (process.env.VERCEL && isLoopbackApiUrl(process.env.NEXT_PUBLIC_API_BASE_URL)) {
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
}

/** Proxy FastAPI on this machine. Vercel uses vercel.json instead. */
function shouldProxyLocalApi(): boolean {
  if (process.env.VERCEL) return false;
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured && !isLoopbackApiUrl(configured)) return false;
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
      {
        source: "/api/jobs/:jobId/plan/:path*",
        destination: `${LOCAL_API}/api/jobs/:jobId/plan/:path*`,
      },
      {
        source: "/api/jobs/:jobId/settings",
        destination: `${LOCAL_API}/api/jobs/:jobId/settings`,
      },
      { source: "/api/me", destination: `${LOCAL_API}/api/me` },
      { source: "/api/me/:path*", destination: `${LOCAL_API}/api/me/:path*` },
      { source: "/api/documents", destination: `${LOCAL_API}/api/documents` },
      {
        source: "/api/documents/:path*",
        destination: `${LOCAL_API}/api/documents/:path*`,
      },
      { source: "/api/source", destination: `${LOCAL_API}/api/source` },
      {
        source: "/api/source/:path*",
        destination: `${LOCAL_API}/api/source/:path*`,
      },
      { source: "/api/tts/:path*", destination: `${LOCAL_API}/api/tts/:path*` },
      { source: "/api/video/:path*", destination: `${LOCAL_API}/api/video/:path*` },
      { source: "/api/learn", destination: `${LOCAL_API}/api/learn` },
      { source: "/api/learn/:path*", destination: `${LOCAL_API}/api/learn/:path*` },
      {
        source: "/api/jobs/:jobId/publish/:path*",
        destination: `${LOCAL_API}/api/jobs/:jobId/publish/:path*`,
      },
      {
        source: "/api/pipelines/:path*",
        destination: `${LOCAL_API}/api/pipelines/:path*`,
      },
    ];
  },
};

export default nextConfig;
