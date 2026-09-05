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
        "1) create_video takes a JSON object argument named plan (title, concept_summary, scenes). Never put the plan inside prompt. Do not pass voice, audio, or subtitles to create_video. " +
        "2) After create_video, revise_plan, edit_storyboard, or update_scene, STOP. Show the numbered storyboard in chat. Then ask the user whether they want spoken audio, burned-in subtitles, and which voice. Call update_video_options with their answers. Do not render yet. Do not write Manim yet. " +
        "3) The user can change anything: update_scene (one scene), edit_storyboard (plain-English edits), revise_plan (full JSON), update_video_options (voice/audio/subtitles — required after the plan), get_scene (code + preview image), retouch_scene (after a clip exists). " +
        "4) Show preview images and VLM notes when get_job / get_scene / render_video return them — they are in the tool result as images. " +
        "5) Only after they approve the storyboard AND update_video_options has production_options_confirmed: video_codegen_spec + submit_scene_code one scene at a time. Each submit returns a preview IMAGE — show it, write 1-2 sentences about what the frame shows (and any layout issues), then continue. Never dump a dozen submits with no commentary. " +
        "6) After every scene has code, render_video with user_confirmed true. Render takes minutes. If get_job/render_video returns poll_again, wait poll_after_seconds and call get_job again with the same job_id. Show new preview images as they arrive. Do not start a new job. " +
        "Never MathTex — Text() only. Documents: upload_document, poll get_document, ask_document. Show figure images from those tools.",
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
