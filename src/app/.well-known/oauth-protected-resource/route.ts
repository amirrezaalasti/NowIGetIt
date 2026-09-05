import { issuerFrom, oauthCorsHeaders, oauthJson, protectedResourceMetadata } from "@/lib/mcp/oauth";

export const dynamic = "force-dynamic";

export function GET(req: Request) {
  return oauthJson(protectedResourceMetadata(issuerFrom(req)));
}

export function OPTIONS() {
  return new Response(null, { status: 204, headers: oauthCorsHeaders() });
}
