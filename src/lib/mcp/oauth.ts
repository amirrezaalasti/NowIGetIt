import { createHash, randomBytes } from "node:crypto";
import { SignJWT, jwtVerify, type JWTPayload } from "jose";
import { MCP_SCOPES, publicOriginFrom } from "./config";

export const MCP_OAUTH_SCOPE = MCP_SCOPES[0];
const CLIENT_TYP = "mcp-oauth-client";
const PENDING_TYP = "mcp-oauth-pending";
const CODE_TYP = "mcp-oauth-code";
const ACCESS_TYP = "mcp-oauth-at";
const REFRESH_TYP = "mcp-oauth-rt";

export type OauthClient = {
  client_id: string;
  client_name: string;
  redirect_uris: string[];
  token_endpoint_auth_method: "none" | "client_secret_post";
  client_secret?: string;
};

export type AuthCode = {
  sub: string;
  email?: string | null;
  name?: string | null;
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  resource: string;
  scope: string;
};

export type AccessClaims = {
  sub: string;
  email?: string | null;
  name?: string | null;
  client_id: string;
  resource: string;
  scope: string;
};

function secretBytes(): Uint8Array {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) throw new Error("AUTH_SECRET is not configured");
  return new TextEncoder().encode(secret);
}

export function oauthCorsHeaders(): Headers {
  return new Headers({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
    "Access-Control-Max-Age": "86400",
  });
}

export function oauthJson(data: unknown, status = 200): Response {
  const headers = oauthCorsHeaders();
  headers.set("Content-Type", "application/json");
  headers.set("Cache-Control", "no-store");
  return new Response(JSON.stringify(data), { status, headers });
}

export function oauthError(
  error: string,
  description: string,
  status = 400,
): Response {
  return oauthJson({ error, error_description: description }, status);
}

export function issuerFrom(req: Request): string {
  return publicOriginFrom(req);
}

export function mcpResourceUrl(origin: string): string {
  return `${origin.replace(/\/$/, "")}/api/mcp`;
}

export function authorizationServerMetadata(origin: string) {
  const iss = origin.replace(/\/$/, "");
  return {
    issuer: iss,
    authorization_endpoint: `${iss}/oauth/authorize`,
    token_endpoint: `${iss}/oauth/token`,
    registration_endpoint: `${iss}/oauth/register`,
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: ["none", "client_secret_post", "client_secret_basic"],
    client_id_metadata_document_supported: true,
    scopes_supported: [MCP_OAUTH_SCOPE],
    authorization_response_iss_parameter_supported: true,
  };
}

export function protectedResourceMetadata(origin: string) {
  const iss = origin.replace(/\/$/, "");
  return {
    resource: mcpResourceUrl(iss),
    authorization_servers: [iss],
    bearer_methods_supported: ["header"],
    scopes_supported: [MCP_OAUTH_SCOPE],
  };
}

export function googleAuthConfigured(): boolean {
  return Boolean(
    process.env.AUTH_GOOGLE_ID?.trim() && process.env.AUTH_GOOGLE_SECRET?.trim(),
  );
}

export function isAllowedRedirectUri(uri: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(uri);
  } catch {
    return false;
  }
  const protocol = parsed.protocol.toLowerCase();
  if (protocol === "http:" || protocol === "https:") {
    const host = parsed.hostname.toLowerCase();
    if (host === "localhost" || host === "127.0.0.1" || host === "[::1]") {
      return true;
    }
    const exact = new Set([
      "claude.ai",
      "www.claude.ai",
      "claude.com",
      "chatgpt.com",
      "chat.openai.com",
      "platform.openai.com",
      "vscode.dev",
    ]);
    if (exact.has(host)) return true;
    if (host.endsWith(".claude.ai")) return true;
    if (host.endsWith(".claude.com")) return true;
    if (host.endsWith(".chatgpt.com")) return true;
    if (host.endsWith(".openai.com")) return true;
    if (host.endsWith(".cursor.sh")) return true;
    if (host.endsWith(".anthropic.com")) return true;
    return false;
  }
  return ["cursor:", "vscode:", "vscode-insiders:"].includes(protocol);
}

export function resourcesMatch(a: string, b: string): boolean {
  return a.replace(/\/$/, "") === b.replace(/\/$/, "");
}

/** HTTPS URL with a path — ChatGPT Apps send this as `client_id` (CIMD). */
export function isCimdClientId(clientId: string): boolean {
  try {
    const url = new URL(clientId);
    return url.protocol === "https:" && url.pathname.length > 1 && !url.hash;
  } catch {
    return false;
  }
}

function isBlockedCimdHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (!host || host === "localhost" || host.endsWith(".localhost")) return true;
  if (host === "127.0.0.1" || host === "0.0.0.0" || host === "::1") return true;
  if (host.endsWith(".local") || host.endsWith(".internal") || host === "metadata.google.internal") {
    return true;
  }
  if (host.startsWith("169.254.")) return true;
  if (/^10\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) {
    return true;
  }
  return false;
}

function isAllowedCimdHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  const exact = new Set([
    "chatgpt.com",
    "openai.com",
    "chat.openai.com",
    "platform.openai.com",
    "claude.ai",
    "www.claude.ai",
    "claude.com",
    "vscode.dev",
  ]);
  if (exact.has(host)) return true;
  return (
    host.endsWith(".chatgpt.com") ||
    host.endsWith(".openai.com") ||
    host.endsWith(".claude.ai") ||
    host.endsWith(".claude.com") ||
    host.endsWith(".cursor.sh") ||
    host.endsWith(".anthropic.com")
  );
}

const CIMD_TIMEOUT_MS = 5000;
const CIMD_MAX_BYTES = 64 * 1024;
const cimdCache = new Map<string, { client: OauthClient; expires: number }>();

export function clientAuthFrom(
  req: Request,
  form: URLSearchParams,
): { clientId: string; clientSecret: string } {
  const header = req.headers.get("authorization") || "";
  if (header.toLowerCase().startsWith("basic ")) {
    try {
      const decoded = Buffer.from(header.slice(6).trim(), "base64").toString("utf8");
      const colon = decoded.indexOf(":");
      if (colon >= 0) {
        return {
          clientId: decodeURIComponent(decoded.slice(0, colon)),
          clientSecret: decodeURIComponent(decoded.slice(colon + 1)),
        };
      }
    } catch {
      /* fall through to body */
    }
  }
  return {
    clientId: form.get("client_id") || "",
    clientSecret: form.get("client_secret") || "",
  };
}

export function s256(verifier: string): string {
  const digest = createHash("sha256").update(verifier).digest();
  return digest.toString("base64url");
}

async function sign(
  claims: Record<string, unknown>,
  typ: string,
  expires: string,
): Promise<string> {
  return new SignJWT({ ...claims, typ })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuedAt()
    .setExpirationTime(expires)
    .setIssuer("nowigetit-mcp")
    .sign(secretBytes());
}

async function read(token: string): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, secretBytes(), {
    algorithms: ["HS256"],
    issuer: "nowigetit-mcp",
  });
  return payload;
}

export async function registerClient(input: {
  client_name?: string;
  redirect_uris?: unknown;
  token_endpoint_auth_method?: string;
}): Promise<OauthClient> {
  const redirect_uris = Array.isArray(input.redirect_uris)
    ? input.redirect_uris.filter((u): u is string => typeof u === "string" && isAllowedRedirectUri(u))
    : [];
  if (!redirect_uris.length) {
    throw new Error("redirect_uris must include at least one allowed URI");
  }
  const method =
    input.token_endpoint_auth_method === "client_secret_post"
      ? "client_secret_post"
      : "none";
  const client_secret =
    method === "client_secret_post" ? randomBytes(24).toString("base64url") : undefined;
  const client_id = await sign(
    {
      client_name: String(input.client_name || "MCP client").slice(0, 80),
      redirect_uris,
      token_endpoint_auth_method: method,
      client_secret: client_secret || null,
    },
    CLIENT_TYP,
    "365d",
  );
  return {
    client_id,
    client_name: String(input.client_name || "MCP client").slice(0, 80),
    redirect_uris,
    token_endpoint_auth_method: method,
    client_secret,
  };
}

async function loadCimdClient(clientId: string): Promise<OauthClient | null> {
  const cached = cimdCache.get(clientId);
  if (cached && cached.expires > Date.now()) return cached.client;

  let url: URL;
  try {
    url = new URL(clientId);
  } catch {
    return null;
  }
  if (isBlockedCimdHost(url.hostname) || !isAllowedCimdHost(url.hostname)) return null;

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), CIMD_TIMEOUT_MS);
  try {
    const res = await fetch(clientId, {
      method: "GET",
      redirect: "error",
      headers: { Accept: "application/json" },
      signal: ac.signal,
      cache: "no-store",
    });
    if (!res.ok) return null;
    const declaredLength = Number(res.headers.get("content-length") || "0");
    if (declaredLength > CIMD_MAX_BYTES) return null;
    const text = await res.text();
    if (text.length > CIMD_MAX_BYTES) return null;
    const meta = JSON.parse(text) as Record<string, unknown>;
    if (meta.client_id !== clientId) return null;
    const redirect_uris = Array.isArray(meta.redirect_uris)
      ? meta.redirect_uris.filter(
          (item): item is string => typeof item === "string" && isAllowedRedirectUri(item),
        )
      : [];
    if (!redirect_uris.length) return null;
    const method =
      meta.token_endpoint_auth_method === "client_secret_post" ? "client_secret_post" : "none";
    const client: OauthClient = {
      client_id: clientId,
      client_name:
        typeof meta.client_name === "string" ? meta.client_name.slice(0, 80) : "MCP client",
      redirect_uris,
      token_endpoint_auth_method: method,
    };
    const maxAge = res.headers.get("cache-control")?.match(/max-age=(\d+)/);
    const ttl = maxAge ? Math.min(Number(maxAge[1]) * 1000, 60 * 60 * 1000) : 5 * 60 * 1000;
    cimdCache.set(clientId, { client, expires: Date.now() + Math.max(ttl, 30_000) });
    return client;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function loadClient(clientId: string): Promise<OauthClient | null> {
  if (isCimdClientId(clientId)) return loadCimdClient(clientId);
  try {
    const payload = await read(clientId);
    if (payload.typ !== CLIENT_TYP) return null;
    const redirect_uris = Array.isArray(payload.redirect_uris)
      ? payload.redirect_uris.filter((u): u is string => typeof u === "string")
      : [];
    if (!redirect_uris.length) return null;
    const method =
      payload.token_endpoint_auth_method === "client_secret_post"
        ? "client_secret_post"
        : "none";
    return {
      client_id: clientId,
      client_name: typeof payload.client_name === "string" ? payload.client_name : "MCP client",
      redirect_uris,
      token_endpoint_auth_method: method,
      client_secret:
        typeof payload.client_secret === "string" ? payload.client_secret : undefined,
    };
  } catch {
    return null;
  }
}

export function clientAllowsRedirect(client: OauthClient, redirectUri: string): boolean {
  return client.redirect_uris.includes(redirectUri);
}

export async function issueAuthorizationCode(code: AuthCode): Promise<string> {
  return sign(
    {
      sub: code.sub,
      email: code.email || null,
      name: code.name || null,
      client_id: code.client_id,
      redirect_uri: code.redirect_uri,
      code_challenge: code.code_challenge,
      resource: code.resource,
      scope: code.scope || MCP_OAUTH_SCOPE,
    },
    CODE_TYP,
    "10m",
  );
}

export async function consumeAuthorizationCode(code: string): Promise<AuthCode | null> {
  try {
    const payload = await read(code);
    if (payload.typ !== CODE_TYP || typeof payload.sub !== "string") return null;
    if (typeof payload.client_id !== "string") return null;
    if (typeof payload.redirect_uri !== "string") return null;
    if (typeof payload.code_challenge !== "string") return null;
    if (typeof payload.resource !== "string") return null;
    return {
      sub: payload.sub,
      email: typeof payload.email === "string" ? payload.email : null,
      name: typeof payload.name === "string" ? payload.name : null,
      client_id: payload.client_id,
      redirect_uri: payload.redirect_uri,
      code_challenge: payload.code_challenge,
      resource: payload.resource,
      scope: typeof payload.scope === "string" ? payload.scope : MCP_OAUTH_SCOPE,
    };
  } catch {
    return null;
  }
}

export async function issueTokenPair(claims: AccessClaims): Promise<{
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
  scope: string;
}> {
  const access_token = await sign(
    {
      sub: claims.sub,
      email: claims.email || null,
      name: claims.name || null,
      client_id: claims.client_id,
      resource: claims.resource,
      scope: claims.scope,
      aud: claims.resource,
    },
    ACCESS_TYP,
    "24h",
  );
  const refresh_token = await sign(
    {
      sub: claims.sub,
      email: claims.email || null,
      name: claims.name || null,
      client_id: claims.client_id,
      resource: claims.resource,
      scope: claims.scope,
    },
    REFRESH_TYP,
    "30d",
  );
  return {
    access_token,
    refresh_token,
    token_type: "Bearer",
    expires_in: 60 * 60 * 24,
    scope: claims.scope,
  };
}

export async function verifyAccessToken(
  token: string,
  expectedResource: string,
): Promise<AccessClaims | null> {
  try {
    const payload = await read(token);
    if (payload.typ !== ACCESS_TYP || typeof payload.sub !== "string") return null;
    const resource = typeof payload.resource === "string" ? payload.resource : "";
    if (resource && !resourcesMatch(resource, expectedResource)) return null;
    return {
      sub: payload.sub,
      email: typeof payload.email === "string" ? payload.email : null,
      name: typeof payload.name === "string" ? payload.name : null,
      client_id: typeof payload.client_id === "string" ? payload.client_id : "mcp-oauth",
      resource: resource || expectedResource,
      scope: typeof payload.scope === "string" ? payload.scope : MCP_OAUTH_SCOPE,
    };
  } catch {
    return null;
  }
}

export async function verifyRefreshToken(token: string): Promise<AccessClaims | null> {
  try {
    const payload = await read(token);
    if (payload.typ !== REFRESH_TYP || typeof payload.sub !== "string") return null;
    if (typeof payload.client_id !== "string") return null;
    if (typeof payload.resource !== "string") return null;
    return {
      sub: payload.sub,
      email: typeof payload.email === "string" ? payload.email : null,
      name: typeof payload.name === "string" ? payload.name : null,
      client_id: payload.client_id,
      resource: payload.resource,
      scope: typeof payload.scope === "string" ? payload.scope : MCP_OAUTH_SCOPE,
    };
  } catch {
    return null;
  }
}

export type AuthorizeQuery = {
  client_id: string;
  redirect_uri: string;
  state: string;
  code_challenge: string;
  resource: string;
  scope: string;
};

export function parseAuthorizeQuery(
  params: URLSearchParams,
  origin: string,
): { ok: true; value: AuthorizeQuery } | { ok: false; error: string; description: string } {
  const responseType = params.get("response_type") || "";
  if (responseType && responseType !== "code") {
    return { ok: false, error: "unsupported_response_type", description: "Only response_type=code is supported" };
  }
  const client_id = params.get("client_id") || "";
  const redirect_uri = params.get("redirect_uri") || "";
  const code_challenge = params.get("code_challenge") || "";
  const method = params.get("code_challenge_method") || "S256";
  if (!client_id || !redirect_uri || !code_challenge) {
    return {
      ok: false,
      error: "invalid_request",
      description: "client_id, redirect_uri, and code_challenge are required",
    };
  }
  if (method !== "S256") {
    return { ok: false, error: "invalid_request", description: "code_challenge_method must be S256" };
  }
  return {
    ok: true,
    value: {
      client_id,
      redirect_uri,
      state: params.get("state") || "",
      code_challenge,
      resource: params.get("resource") || mcpResourceUrl(origin),
      scope: params.get("scope") || MCP_OAUTH_SCOPE,
    },
  };
}

export async function issuePendingAuthorize(query: AuthorizeQuery): Promise<string> {
  return sign({ ...query }, PENDING_TYP, "15m");
}

export async function readPendingAuthorize(token: string): Promise<AuthorizeQuery | null> {
  try {
    const payload = await read(token);
    if (payload.typ !== PENDING_TYP) return null;
    if (typeof payload.client_id !== "string") return null;
    if (typeof payload.redirect_uri !== "string") return null;
    if (typeof payload.code_challenge !== "string") return null;
    return {
      client_id: payload.client_id,
      redirect_uri: payload.redirect_uri,
      state: typeof payload.state === "string" ? payload.state : "",
      code_challenge: payload.code_challenge,
      resource: typeof payload.resource === "string" ? payload.resource : "",
      scope: typeof payload.scope === "string" ? payload.scope : MCP_OAUTH_SCOPE,
    };
  } catch {
    return null;
  }
}

export function pkceMatches(verifier: string, challenge: string): boolean {
  if (!verifier || !challenge) return false;
  return s256(verifier) === challenge;
}
