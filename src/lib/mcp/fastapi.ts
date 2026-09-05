import { apiOrigin } from "./config";
import { absoluteUrl, mintApiToken, mintMediaToken, withAccessToken } from "./tokens";

export type PipelineEvent = {
  type: string;
  message: string;
  data?: Record<string, unknown> | null;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function parseDetail(text: string, fallback: string): { message: string; code: string | null } {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    const detail = parsed?.detail;
    if (typeof detail === "string") return { message: detail, code: null };
    if (detail && typeof detail === "object") {
      const obj = detail as Record<string, unknown>;
      const message = typeof obj.message === "string" ? obj.message : fallback;
      const code = typeof obj.code === "string" ? obj.code : null;
      return { message, code };
    }
  } catch {
    /* not JSON */
  }
  return { message: text || fallback, code: null };
}

async function apiFetch(
  publicOrigin: string,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await mintApiToken();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const url = `${apiOrigin(publicOrigin)}${path}`;
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers, cache: "no-store" });
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    throw new ApiError(
      `Cannot reach the Now I Get It API at ${url} (${why}). Start it with npm run dev:api, or set NEXT_PUBLIC_API_BASE_URL.`,
      503,
    );
  }
  if (!res.ok) {
    const text = await res.text();
    const { message, code } = parseDetail(text, `API ${res.status}`);
    if (res.status === 402 || code) {
      throw new ApiError(
        message || "Monthly generation or token limit reached.",
        res.status,
        code,
      );
    }
    throw new ApiError(message, res.status, code);
  }
  return res;
}

export async function apiJson<T>(
  publicOrigin: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await apiFetch(publicOrigin, path, init);
  return (await res.json()) as T;
}

function parseSseBlock(block: string): PipelineEvent | null {
  const dataLine = block
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.startsWith("data:"));
  if (!dataLine) return null;
  const raw = dataLine.replace(/^data:\s*/, "");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PipelineEvent;
  } catch {
    return null;
  }
}

export type SseWaitOptions = {
  /** Stop once an event of this type arrives (or any of these types). */
  untilType?: string | string[];
  timeoutMs?: number;
};

/**
 * POST an SSE endpoint, keep reading until `untilType` (or timeout).
 * The FastAPI job thread continues after this fetch is aborted.
 */
export async function startSse(
  publicOrigin: string,
  path: string,
  body: BodyInit | null,
  extraHeaders: Record<string, string>,
  opts: SseWaitOptions = {},
): Promise<{ events: PipelineEvent[]; jobId: string | null; docId: string | null }> {
  const until = new Set(
    Array.isArray(opts.untilType)
      ? opts.untilType
      : opts.untilType
        ? [opts.untilType]
        : [],
  );
  const timeoutMs = opts.timeoutMs ?? 90_000;
  const res = await apiFetch(publicOrigin, path, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      ...extraHeaders,
    },
    body,
  });
  if (!res.body) throw new ApiError("No response stream", 500);

  const events: PipelineEvent[] = [];
  let jobId: string | null = null;
  let docId: string | null = null;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const deadline = Date.now() + timeoutMs;

  const take = (event: PipelineEvent) => {
    events.push(event);
    const data = event.data || {};
    if (typeof data.job_id === "string") jobId = data.job_id;
    if (typeof data.doc_id === "string") docId = data.doc_id;
    if (event.type === "error") {
      const code = typeof data.code === "string" ? data.code : null;
      throw new ApiError(event.message || "Pipeline error", 500, code);
    }
  };

  try {
    while (Date.now() < deadline) {
      const remaining = Math.max(1, deadline - Date.now());
      const read = await Promise.race([
        reader.read(),
        new Promise<{ done: true; value: undefined }>((resolve) =>
          setTimeout(() => resolve({ done: true, value: undefined }), remaining),
        ),
      ]);
      if (read.done) break;
      buffer += decoder.decode(read.value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const event = parseSseBlock(part);
        if (!event) continue;
        take(event);
        if (until.size && until.has(event.type)) {
          await reader.cancel().catch(() => undefined);
          return { events, jobId, docId };
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }

  return { events, jobId, docId };
}

export async function signedMediaUrl(
  publicOrigin: string,
  path: string | null | undefined,
): Promise<string> {
  if (!path) return "";
  const token = await mintMediaToken();
  return withAccessToken(absoluteUrl(publicOrigin, path), token);
}

export function lastEvent(
  events: PipelineEvent[],
  type?: string,
): PipelineEvent | null {
  if (type) {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      if (events[i].type === type) return events[i];
    }
    return null;
  }
  return events[events.length - 1] ?? null;
}
