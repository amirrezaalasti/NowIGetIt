import { auth } from "@/auth";
import {
  clientAllowsRedirect,
  googleAuthConfigured,
  isAllowedRedirectUri,
  issuerFrom,
  issuePendingAuthorize,
  loadClient,
  parseAuthorizeQuery,
} from "@/lib/mcp/oauth";
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const PENDING_COOKIE = "mcp_oauth_pending";

function denyRedirect(redirectUri: string, state: string, error: string, description: string) {
  if (!isAllowedRedirectUri(redirectUri)) {
    return NextResponse.json({ error, error_description: description }, { status: 400 });
  }
  const next = new URL(redirectUri);
  next.searchParams.set("error", error);
  next.searchParams.set("error_description", description);
  if (state) next.searchParams.set("state", state);
  return NextResponse.redirect(next);
}

export async function GET(req: NextRequest) {
  const origin = issuerFrom(req);
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
  const client = await loadClient(parsed.value.client_id);
  if (!client || !clientAllowsRedirect(client, parsed.value.redirect_uri)) {
    return denyRedirect(
      parsed.value.redirect_uri,
      parsed.value.state,
      "invalid_client",
      "Unknown or unregistered chat client",
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
