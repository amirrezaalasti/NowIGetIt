import { createReadStream, existsSync, statSync } from "fs";
import { readFile } from "fs/promises";
import path from "path";
import { Readable } from "stream";
import { jwtVerify } from "jose";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Serve job artifacts from the local filesystem (repo/artifacts).
 * Runs in the Next.js process so playback is not blocked while the
 * Python/Manim worker is busy rendering the next scene.
 */
function artifactsRoot(): string {
  return (
    process.env.ARTIFACTS_ROOT?.trim() ||
    path.join(process.cwd(), "artifacts")
  );
}

async function userIdFromRequest(req: NextRequest): Promise<string | null> {
  const secret = process.env.AUTH_SECRET?.trim();
  if (!secret) return null;

  const header = req.headers.get("authorization");
  const bearer =
    header?.toLowerCase().startsWith("bearer ")
      ? header.slice(7).trim()
      : null;
  const queryToken = req.nextUrl.searchParams.get("access_token");
  const token = bearer || queryToken;
  if (!token) return null;

  try {
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(secret),
      { audience: "nowigetit-api", issuer: "nowigetit" },
    );
    return typeof payload.sub === "string" ? payload.sub : null;
  } catch {
    return null;
  }
}

function contentTypeFor(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  const map: Record<string, string> = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".py": "text/x-python",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
  };
  return map[ext] || "application/octet-stream";
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ jobId: string; filePath: string[] }> },
) {
  const { jobId, filePath } = await ctx.params;
  if (!jobId || !filePath?.length) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (jobId.includes("..") || filePath.some((p) => p.includes(".."))) {
    return NextResponse.json({ error: "Invalid path" }, { status: 400 });
  }

  const userId = await userIdFromRequest(req);
  if (!userId) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const root = artifactsRoot();
  const jobRoot = path.resolve(root, jobId);
  const metaPath = path.join(jobRoot, "meta.json");
  if (!existsSync(metaPath)) {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  try {
    const meta = JSON.parse(await readFile(metaPath, "utf8")) as {
      user_id?: string;
    };
    if (meta.user_id && meta.user_id !== userId) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }
  } catch {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  const abs = path.resolve(jobRoot, ...filePath);
  if (!abs.startsWith(jobRoot + path.sep) && abs !== jobRoot) {
    return NextResponse.json({ error: "Invalid path" }, { status: 400 });
  }
  if (!existsSync(abs) || !statSync(abs).isFile()) {
    return NextResponse.json({ error: "File not found" }, { status: 404 });
  }

  const stat = statSync(abs);
  const contentType = contentTypeFor(abs);
  const range = req.headers.get("range");

  const headers = new Headers({
    "Content-Type": contentType,
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=30",
  });

  if (range) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (m) {
      const start = m[1] ? parseInt(m[1], 10) : 0;
      const end = m[2] ? parseInt(m[2], 10) : stat.size - 1;
      if (
        Number.isFinite(start) &&
        Number.isFinite(end) &&
        start >= 0 &&
        end >= start &&
        end < stat.size
      ) {
        const chunkSize = end - start + 1;
        headers.set("Content-Range", `bytes ${start}-${end}/${stat.size}`);
        headers.set("Content-Length", String(chunkSize));
        const nodeStream = createReadStream(abs, { start, end });
        const webStream = Readable.toWeb(nodeStream) as ReadableStream;
        return new NextResponse(webStream, { status: 206, headers });
      }
    }
  }

  headers.set("Content-Length", String(stat.size));
  const nodeStream = createReadStream(abs);
  const webStream = Readable.toWeb(nodeStream) as ReadableStream;
  return new NextResponse(webStream, { status: 200, headers });
}
