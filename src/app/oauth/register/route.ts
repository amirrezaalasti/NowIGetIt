import {
  oauthCorsHeaders,
  oauthError,
  oauthJson,
  registerClient,
} from "@/lib/mcp/oauth";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let body: Record<string, unknown> = {};
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return oauthError("invalid_client_metadata", "JSON body required");
  }
  try {
    const client = await registerClient({
      client_name: typeof body.client_name === "string" ? body.client_name : undefined,
      redirect_uris: body.redirect_uris,
      token_endpoint_auth_method:
        typeof body.token_endpoint_auth_method === "string"
          ? body.token_endpoint_auth_method
          : undefined,
    });
    return oauthJson(
      {
        client_id: client.client_id,
        client_name: client.client_name,
        redirect_uris: client.redirect_uris,
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        token_endpoint_auth_method: client.token_endpoint_auth_method,
        client_id_issued_at: Math.floor(Date.now() / 1000),
        ...(client.client_secret ? { client_secret: client.client_secret } : {}),
      },
      201,
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Invalid client metadata";
    return oauthError("invalid_client_metadata", message);
  }
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: oauthCorsHeaders() });
}
