/** Loopback hosts are valid only on this machine, never in a published browser bundle. */
export function isLoopbackHostname(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return (
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "0.0.0.0" ||
    host === "::1" ||
    host.endsWith(".localhost")
  );
}

export function isLoopbackOrigin(value: string): boolean {
  try {
    return isLoopbackHostname(new URL(value).hostname);
  } catch {
    return false;
  }
}

function trimOrigin(value: string | undefined | null): string {
  return value?.trim().replace(/\/$/, "") || "";
}

/**
 * Browser/API origin for the Next.js client.
 * Empty string = same-origin `/api` (Vercel Python or local/Railway rewrites).
 */
export function resolveBrowserApiBase(configured: string | undefined): string {
  const base = trimOrigin(configured);
  if (!base) return "";
  if (!isLoopbackOrigin(base)) return base;

  if (typeof window !== "undefined") {
    return isLoopbackHostname(window.location.hostname) ? base : "";
  }
  if (process.env.VERCEL || process.env.RAILWAY_ENVIRONMENT) return "";
  return base;
}

/**
 * Server-side FastAPI origin (MCP, Node fetch).
 * Vercel must not call 127.0.0.1 — Python is same-origin via vercel.json.
 */
export function resolveServerApiOrigin(
  publicOrigin: string,
  configured: string | undefined,
): string {
  const origin = trimOrigin(configured);
  if (origin && !(process.env.VERCEL && isLoopbackOrigin(origin))) {
    return origin;
  }
  if (!process.env.VERCEL) return "http://127.0.0.1:8000";
  return trimOrigin(publicOrigin) || publicOrigin;
}
