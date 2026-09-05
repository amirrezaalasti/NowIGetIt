import { createMcpHandler, withMcpAuth } from "mcp-handler";
import type { AuthInfo } from "@modelcontextprotocol/server";
import {
  connectorToken,
  mcpCorsHeaders,
  MCP_SCOPES,
  publicOriginFrom,
} from "@/lib/mcp/config";
import {
  googleAuthConfigured,
  issuerFrom,
  mcpResourceUrl,
  verifyAccessToken,
} from "@/lib/mcp/oauth";
import { registerNowIGetIt } from "@/lib/mcp/tools";
import { runWithMcpUser } from "@/lib/mcp/user-context";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

function withCors(res: Response): Response {
  const headers = new Headers(res.headers);
  mcpCorsHeaders().forEach((value, key) => {
    headers.set(key, value);
  });
  return new Response(res.body, {
    status: res.status,
    statusText: res.statusText,
    headers,
  });
}

function mcpFor(origin: string) {
  return createMcpHandler(
    (server) => {
      registerNowIGetIt(server, origin);
    },
    {
      serverInfo: {
        name: "nowigetit",
        version: "0.1.0",
      },
      instructions:
        "Now I Get It renders educational Manim videos and turns PDFs into study slides. " +
        "The user is already signed in with Google. Jobs are saved to their Now I Get It library. " +
        "YOU write the storyboard and Manim Community code; this server only validates, renders, narrates, and stitches. " +
        "HARD RULES FOR VIDEO: " +
        "1) create_video takes a JSON object argument named plan (title, concept_summary, scenes). Never put the plan inside prompt. " +
        "2) After create_video or revise_plan, STOP. Show the numbered storyboard (titles + narration) in chat and wait for the user to approve or request edits. Do not render yet. Do not write Manim yet. Do not list_jobs. " +
        "3) If they want changes, rewrite the full plan yourself and call revise_plan with {job_id, plan}. " +
        "4) Only after they approve: video_codegen_spec + submit_scene_code for every scene, then render_video with user_confirmed true. " +
        "5) Render takes minutes. If get_job/render_video returns poll_again, wait poll_after_seconds and call get_job again with the same job_id. Do not start a new job. Do not tell the user it failed while status is running. " +
        "6) status awaiting_render means code is saved — call render_video. status error includes the worker message; fix code or wait, do not hammer the same call. " +
        "Never MathTex — Text() only. Documents: upload_document, poll get_document, ask_document.",
    },
  );
}

async function verifyToken(req: Request, bearerToken?: string): Promise<AuthInfo | undefined> {
  if (!bearerToken) return undefined;
  const origin = issuerFrom(req);
  const resource = mcpResourceUrl(origin);
  const oauth = await verifyAccessToken(bearerToken, resource);
  if (oauth) {
    return {
      token: bearerToken,
      clientId: oauth.client_id,
      scopes: [...MCP_SCOPES],
      extra: {
        userId: oauth.sub,
        email: oauth.email,
        name: oauth.name,
      },
    };
  }
  const expected = connectorToken();
  if (expected && bearerToken === expected) {
    return {
      token: bearerToken,
      clientId: "mcp-connector",
      scopes: [...MCP_SCOPES],
      extra: { userId: "mcp-connector", name: "MCP connector" },
    };
  }
  return undefined;
}

async function handle(req: Request): Promise<Response> {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: mcpCorsHeaders() });
  }
  const origin = publicOriginFrom(req);
  const inner = mcpFor(origin);
  const authed = withMcpAuth(
    async (incoming) => {
      const extra = incoming.auth?.extra as
        | { userId?: string; email?: string | null; name?: string | null }
        | undefined;
      const user = {
        id: extra?.userId || "mcp-connector",
        email: extra?.email ?? null,
        name: extra?.name ?? "MCP connector",
      };
      return runWithMcpUser(user, () => inner(incoming));
    },
    verifyToken,
    {
      required: googleAuthConfigured() || Boolean(connectorToken()),
      requiredScopes: [...MCP_SCOPES],
      resourceMetadataPath: "/.well-known/oauth-protected-resource",
      resourceUrl: mcpResourceUrl(origin),
    },
  );
  return withCors(await authed(req));
}

export { handle as GET, handle as POST, handle as DELETE };
export function OPTIONS() {
  return new Response(null, { status: 204, headers: mcpCorsHeaders() });
}
