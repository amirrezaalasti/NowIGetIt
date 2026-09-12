import { SignJWT } from "jose";
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { resolveServerApiOrigin } from "@/lib/api-origin";

export const dynamic = "force-dynamic";

function requestOrigin(req: NextRequest): string {
  const host =
    req.headers.get("x-forwarded-host") || req.headers.get("host") || "";
  const proto =
    req.headers.get("x-forwarded-proto") ||
    (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  if (!host) return new URL(req.url).origin;
  return `${proto}://${host}`;
}

async function mintApiToken(user: {
  id: string;
  email?: string | null;
  name?: string | null;
  image?: string | null;
}): Promise<string> {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) {
    throw new Error("AUTH_SECRET is not configured");
  }
  return new SignJWT({
    email: user.email ?? null,
    name: user.name ?? null,
    image: user.image ?? null,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(user.id)
    .setIssuedAt()
    .setExpirationTime("10m")
    .setAudience("nowigetit-api")
    .setIssuer("nowigetit")
    .sign(new TextEncoder().encode(secret));
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const oauthError = url.searchParams.get("error");
  const origin = requestOrigin(req);
  const fallback = new URL("/settings", origin);

  if (oauthError) {
    fallback.searchParams.set("youtube", "denied");
    return NextResponse.redirect(fallback);
  }
  if (!code || !state) {
    fallback.searchParams.set("youtube", "missing");
    return NextResponse.redirect(fallback);
  }

  const session = await auth();
  if (!session?.user?.id) {
    const login = new URL("/login", origin);
    login.searchParams.set("callbackUrl", `/api/youtube/callback?${url.searchParams.toString()}`);
    return NextResponse.redirect(login);
  }

  try {
    const token = await mintApiToken({
      id: session.user.id,
      email: session.user.email,
      name: session.user.name,
      image: session.user.image,
    });
    const apiOrigin = resolveServerApiOrigin(origin, process.env.NEXT_PUBLIC_API_BASE_URL);
    const res = await fetch(`${apiOrigin}/api/me/youtube/complete`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ code, state, origin }),
    });
    const body = (await res.json().catch(() => ({}))) as {
      return_to?: string;
      detail?: unknown;
    };
    if (!res.ok) {
      const message =
        typeof body.detail === "string" ? body.detail : "YouTube connect failed";
      fallback.searchParams.set("youtube", "error");
      fallback.searchParams.set("reason", message.slice(0, 160));
      return NextResponse.redirect(fallback);
    }
    const dest =
      typeof body.return_to === "string" && body.return_to.startsWith("/")
        ? body.return_to
        : "/settings";
    const next = new URL(dest, origin);
    next.searchParams.set("youtube", "connected");
    return NextResponse.redirect(next);
  } catch {
    fallback.searchParams.set("youtube", "error");
    return NextResponse.redirect(fallback);
  }
}
