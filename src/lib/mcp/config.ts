import { getPublicOrigin } from "mcp-handler";

/** Shared FastAPI identity for ChatGPT/Claude — no Google profile, no extra user rows. */
export const MCP_USER_ID = "mcp-connector";

export const MCP_SCOPES = ["nowigetit"] as const;

export const UI = {
  jobProgress: "ui://nowigetit/job-progress",
  videoPlayer: "ui://nowigetit/video-player",
  slidesTutor: "ui://nowigetit/slides-tutor",
} as const;

export const MCP_APP_MIME = "text/html;profile=mcp-app";

export function connectorToken(): string | null {
  const value = process.env.MCP_CONNECTOR_TOKEN?.trim();
  return value || null;
}

export function fallbackPublicOrigin(): string {
  const authUrl = process.env.AUTH_URL?.trim() || process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (authUrl) return authUrl.replace(/\/$/, "");
  const railway = process.env.RAILWAY_PUBLIC_DOMAIN?.trim();
  if (railway) {
    return railway.startsWith("http") ? railway.replace(/\/$/, "") : `https://${railway}`;
  }
  const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL?.trim() || process.env.VERCEL_URL?.trim();
  if (vercel) {
    return vercel.startsWith("http") ? vercel.replace(/\/$/, "") : `https://${vercel}`;
  }
  return "http://localhost:3000";
}

export function publicOriginFrom(req?: Request): string {
  if (req) {
    try {
      return getPublicOrigin(req).replace(/\/$/, "");
    } catch {
      /* fall through */
    }
  }
  return fallbackPublicOrigin();
}

/** FastAPI origin. Local: uvicorn. Production: same-origin Python rewrites. */
export function apiOrigin(publicOrigin: string): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");
  // Local + Railway app container: FastAPI is on loopback (see next.config rewrites).
  if (!process.env.VERCEL) return "http://127.0.0.1:8000";
  return publicOrigin;
}

export function mcpCorsHeaders(): Headers {
  return new Headers({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers":
      "Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Session-Id, Mcp-Method, Mcp-Name, Last-Event-ID",
    "Access-Control-Expose-Headers":
      "MCP-Protocol-Version, Mcp-Session-Id, Content-Type, Content-Length",
    "Access-Control-Max-Age": "86400",
  });
}

export function widgetMeta(resourceUri: string): Record<string, unknown> {
  return {
    ui: { resourceUri },
    "openai/outputTemplate": resourceUri,
  };
}
