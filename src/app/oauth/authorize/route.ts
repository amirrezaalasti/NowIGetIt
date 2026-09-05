import { auth } from "@/auth";
import {
  googleAuthConfigured,
  issuePendingAuthorize,
  parseAuthorizeQuery,
} from "@/lib/mcp/oauth";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const PENDING_COOKIE = "mcp_oauth_pending";

function originOf(req: NextRequest): string {
  const host = req.headers.get("x-forwarded-host") || req.headers.get("host") || "localhost:3000";
  const proto =
    req.headers.get("x-forwarded-proto") ||
    (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  return `${proto}://${host}`;
}

export async function GET(req: NextRequest) {
  const origin = originOf(req);
  if (!googleAuthConfigured()) {
    return NextResponse.redirect(new URL("/connect", origin));
  }
  const parsed = parseAuthorizeQuery(req.nextUrl.searchParams, origin);
  if (!parsed.ok) {
    return NextResponse.json(
      { error: parsed.error, error_description: parsed.description },
      { status: 400 },
    );
  }
  const pending = await issuePendingAuthorize(parsed.value);
  const session = await auth();
  const next = session?.user?.id
    ? new URL("/oauth/consent", origin)
    : new URL("/login?callbackUrl=/oauth/consent", origin);
  const res = NextResponse.redirect(next);
  res.cookies.set(PENDING_COOKIE, pending, {
    httpOnly: true,
    sameSite: "lax",
    secure: origin.startsWith("https"),
    path: "/",
    maxAge: 15 * 60,
  });
  return res;
}
