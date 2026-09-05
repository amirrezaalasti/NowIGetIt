import { SignJWT } from "jose";
import { currentMcpUser } from "./user-context";

const API_TTL_SECONDS = 60 * 60 * 24;
const MEDIA_TTL_SECONDS = 60 * 60 * 24;

function secretBytes(): Uint8Array {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) {
    throw new Error("AUTH_SECRET is not configured");
  }
  return new TextEncoder().encode(secret);
}

/** Mint the same HS256 JWT FastAPI already verifies (`aud=nowigetit-api`). */
export async function mintApiToken(): Promise<string> {
  const user = currentMcpUser();
  return new SignJWT({
    email: user.email ?? null,
    name: user.name ?? null,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(user.id)
    .setIssuedAt()
    .setExpirationTime(`${API_TTL_SECONDS}s`)
    .setAudience("nowigetit-api")
    .setIssuer("nowigetit")
    .sign(secretBytes());
}

/** Same token family so `<video src>` / iframe slide HTML can use `?access_token=`. */
export async function mintMediaToken(): Promise<string> {
  const user = currentMcpUser();
  return new SignJWT({
    email: user.email ?? null,
    name: user.name ?? null,
    mcp_media: true,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(user.id)
    .setIssuedAt()
    .setExpirationTime(`${MEDIA_TTL_SECONDS}s`)
    .setAudience("nowigetit-api")
    .setIssuer("nowigetit")
    .sign(secretBytes());
}

export function withAccessToken(url: string, token: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}access_token=${encodeURIComponent(token)}`;
}

export function absoluteUrl(origin: string, path: string | null | undefined): string {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const pathname = path.startsWith("/") ? path : `/${path}`;
  return `${origin.replace(/\/$/, "")}${pathname}`;
}
