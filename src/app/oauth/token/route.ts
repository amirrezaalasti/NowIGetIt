import {
  clientAllowsRedirect,
  consumeAuthorizationCode,
  issueTokenPair,
  loadClient,
  oauthCorsHeaders,
  oauthError,
  oauthJson,
  pkceMatches,
  verifyRefreshToken,
} from "@/lib/mcp/oauth";

export const dynamic = "force-dynamic";

async function readForm(req: Request): Promise<URLSearchParams> {
  const contentType = req.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const body = (await req.json()) as Record<string, unknown>;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(body)) {
      if (typeof value === "string") params.set(key, value);
    }
    return params;
  }
  const text = await req.text();
  return new URLSearchParams(text);
}

export async function POST(req: Request) {
  const form = await readForm(req);
  const grant = form.get("grant_type") || "";
  const clientId = form.get("client_id") || "";
  const clientSecret = form.get("client_secret") || "";
  const client = clientId ? await loadClient(clientId) : null;
  if (!client) {
    return oauthError("invalid_client", "Unknown client_id", 401);
  }
  if (
    client.token_endpoint_auth_method === "client_secret_post" &&
    client.client_secret &&
    client.client_secret !== clientSecret
  ) {
    return oauthError("invalid_client", "Invalid client secret", 401);
  }

  if (grant === "refresh_token") {
    const refresh = form.get("refresh_token") || "";
    const claims = await verifyRefreshToken(refresh);
    if (!claims || claims.client_id !== client.client_id) {
      return oauthError("invalid_grant", "Invalid refresh token");
    }
    return oauthJson(await issueTokenPair(claims));
  }

  if (grant !== "authorization_code") {
    return oauthError("unsupported_grant_type", "Use authorization_code or refresh_token");
  }

  const code = form.get("code") || "";
  const redirectUri = form.get("redirect_uri") || "";
  const verifier = form.get("code_verifier") || "";
  const parsed = await consumeAuthorizationCode(code);
  if (!parsed || parsed.client_id !== client.client_id) {
    return oauthError("invalid_grant", "Invalid authorization code");
  }
  if (parsed.redirect_uri !== redirectUri || !clientAllowsRedirect(client, redirectUri)) {
    return oauthError("invalid_grant", "redirect_uri does not match");
  }
  if (!pkceMatches(verifier, parsed.code_challenge)) {
    return oauthError("invalid_grant", "PKCE verification failed");
  }

  return oauthJson(
    await issueTokenPair({
      sub: parsed.sub,
      email: parsed.email,
      name: parsed.name,
      client_id: parsed.client_id,
      resource: parsed.resource,
      scope: parsed.scope,
    }),
  );
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: oauthCorsHeaders() });
}
