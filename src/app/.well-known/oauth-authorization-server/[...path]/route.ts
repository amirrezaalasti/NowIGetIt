import { authorizationServerMetadata, issuerFrom, oauthCorsHeaders, oauthJson } from "@/lib/mcp/oauth";

export const dynamic = "force-dynamic";

export function GET(req: Request) {
  return oauthJson(authorizationServerMetadata(issuerFrom(req)));
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: oauthCorsHeaders() });
}
