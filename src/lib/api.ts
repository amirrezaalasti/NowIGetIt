export type PipelineEvent = {
  type: string;
  message: string;
  data?: Record<string, unknown> | null;
};

export type JobSummary = {
  job_id: string;
  title?: string | null;
  prompt?: string | null;
  created_at?: string | null;
  has_result?: boolean;
};

export type HumanComment = {
  id: string;
  job_id: string;
  scene_id: string;
  comment: string;
  timestamp?: number | null;
  author: string;
  created_at: string;
};

export type JobRuntimeStatus = {
  job_id: string;
  status: "complete" | "running" | "awaiting_plan" | "interrupted" | "unknown" | string;
  running: boolean;
  event_count: number;
  has_result: boolean;
  has_final_video: boolean;
  error?: string | null;
};

export type JobDetail = {
  job_id: string;
  meta?: Record<string, unknown> | null;
  scene_plan?: Record<string, unknown> | null;
  final_debug?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  final_video_url?: string | null;
  scenes: Array<{
    scene_id: string;
    section?: Record<string, unknown>;
    code_final?: string;
    video_url?: string;
    vlm_reviews?: Array<Record<string, unknown>>;
    human_comments?: HumanComment[];
    files?: string[];
  }>;
  events?: Array<Record<string, unknown>>;
  urls?: Record<string, string>;
  runtime?: JobRuntimeStatus;
};

const ACTIVE_JOB_KEY = "nowigetit:activeJobId";

export function getStoredActiveJobId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(ACTIVE_JOB_KEY);
  } catch {
    return null;
  }
}

export function setStoredActiveJobId(jobId: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (jobId) sessionStorage.setItem(ACTIVE_JOB_KEY, jobId);
    else sessionStorage.removeItem(ACTIVE_JOB_KEY);
  } catch {
    /* ignore quota / private mode */
  }
}

type TokenCache = { token: string; expiresAt: number };

let tokenCache: TokenCache | null = null;

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "";
}

/** Public alias for API origin (non-media calls). */
export function apiBasePath(): string {
  return apiBase();
}

/**
 * Same-origin URL for job media files.
 * Served by Next.js from disk so playback is not blocked by Manim on :8000.
 */
export function mediaUrl(
  path: string | null | undefined,
  cacheBust?: number | string,
): string {
  if (!path) return "";
  let pathname = path;
  if (path.startsWith("http://") || path.startsWith("https://")) {
    try {
      const u = new URL(path);
      pathname = u.pathname;
    } catch {
      return "";
    }
  }
  if (!pathname.startsWith("/")) pathname = `/${pathname}`;

  const params = new URLSearchParams();
  if (tokenCache?.token) {
    params.set("access_token", tokenCache.token);
  }
  if (cacheBust !== undefined) {
    params.set("cb", String(cacheBust));
  }
  const q = params.toString();
  return q ? `${pathname}?${q}` : pathname;
}

export function clearApiToken() {
  tokenCache = null;
}

export async function getApiToken(): Promise<string> {
  if (tokenCache && tokenCache.expiresAt > Date.now() + 60_000) {
    return tokenCache.token;
  }
  const res = await fetch("/api/auth/api-token", { cache: "no-store" });
  if (!res.ok) {
    tokenCache = null;
    throw new Error("Sign in required");
  }
  const data = (await res.json()) as { accessToken: string; expiresAt: number };
  tokenCache = { token: data.accessToken, expiresAt: data.expiresAt };
  return data.accessToken;
}

async function authHeaders(
  extra?: Record<string, string>,
): Promise<Record<string, string>> {
  const token = await getApiToken();
  return {
    Authorization: `Bearer ${token}`,
    ...extra,
  };
}

export function assetUrl(path: string | null | undefined): string {
  if (!path) return "";
  // Job files: always same-origin (Next disk serve) — never hit busy :8000.
  const pathname =
    path.startsWith("http://") || path.startsWith("https://")
      ? (() => {
          try {
            return new URL(path).pathname;
          } catch {
            return path;
          }
        })()
      : path;
  if (pathname.includes("/api/jobs/") && pathname.includes("/file/")) {
    return mediaUrl(pathname);
  }
  const base = path.startsWith("http") ? path : `${apiBase()}${path}`;
  if (!tokenCache?.token) return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}access_token=${encodeURIComponent(tokenCache.token)}`;
}

/** Prefetch a token so media URLs can include access_token. */
export async function ensureApiToken(): Promise<string | null> {
  try {
    return await getApiToken();
  } catch {
    return null;
  }
}

export async function addSceneComment(
  jobId: string,
  sceneId: string,
  comment: string,
  timestamp?: number,
): Promise<HumanComment> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/comments`,
    {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ comment, timestamp }),
    },
  );
  if (!res.ok) throw new Error("Failed to post comment");
  return res.json();
}

export async function streamRetouch(
  jobId: string,
  sceneId: string,
  comment: string,
  timestamp: number | undefined,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/retouch/stream`,
    {
      method: "POST",
      headers: await authHeaders({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      }),
      body: JSON.stringify({ comment, timestamp }),
      signal,
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Retouch failed (${res.status})`);
  }
  if (!res.body) throw new Error("No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.startsWith("data: ") ? part.slice(6) : part;
      if (!line.trim()) continue;
      try {
        onEvent(JSON.parse(line) as PipelineEvent);
      } catch {
        /* non-JSON line */
      }
    }
  }
}

export async function approveScene(
  jobId: string,
  sceneId: string,
): Promise<{
  ok: boolean;
  final_video_url: string | null;
  scene_video_url: string | null;
  note?: string;
}> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/approve`,
    {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Approve failed (${res.status})`);
  }
  return res.json();
}

export type TtsVoiceOption = {
  id: string;
  gender: string;
  label: string;
};

export type LengthPreset = "short" | "standard" | "deep";
export type Audience = "hs" | "undergrad" | "general";

export async function fetchHealth(): Promise<{
  ok: boolean;
  model?: string;
  vlm_model?: string;
  openrouter_configured?: boolean;
  tts_configured?: boolean;
  tts_model?: string;
  tts_voice?: string;
  tts_voices?: TtsVoiceOption[];
  manim_render_enabled?: boolean;
  manim_available?: boolean;
  manim_version?: string;
  auth_configured?: boolean;
  supabase_configured?: boolean;
  render_worker_configured?: boolean;
  render_worker_ok?: boolean | null;
  render_worker_detail?: string | null;
}> {
  try {
    const res = await fetch(`${apiBase()}/api/health`, { cache: "no-store" });
    if (!res.ok) throw new Error("API health check failed");
    return res.json();
  } catch (err) {
    throw friendlyFetchError(err, "Health check");
  }
}

export type UsageSnapshot = {
  user_id: string;
  period_start: string;
  llm: {
    tokens_used: number;
    tokens_limit: number;
    requests_used: number;
    requests_limit: number;
  };
  storage: {
    bytes_used: number;
    bytes_limit: number;
  };
};

export async function fetchMe(signal?: AbortSignal): Promise<{
  user: {
    id: string;
    email?: string | null;
    name?: string | null;
    image?: string | null;
  };
  usage: UsageSnapshot | null;
  supabase_configured: boolean;
}> {
  try {
    const res = await fetch(`${apiBase()}/api/me`, {
      cache: "no-store",
      headers: await authHeaders(),
      signal,
    });
    if (!res.ok) throw new Error("Failed to load account usage");
    return res.json();
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw friendlyFetchError(err, "Account usage");
  }
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await fetch(`${apiBase()}/api/jobs`, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to list jobs");
  const data = await res.json();
  return data.jobs || [];
}

export async function fetchJob(jobId: string): Promise<JobDetail> {
  const res = await fetch(`${apiBase()}/api/jobs/${jobId}`, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`Job not found: ${jobId}`);
  return res.json();
}

export async function fetchJobStatus(jobId: string): Promise<JobRuntimeStatus> {
  const res = await fetch(`${apiBase()}/api/jobs/${jobId}/status`, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`Job status unavailable: ${jobId}`);
  return res.json();
}

export async function streamJobEvents(
  jobId: string,
  onEvent: (event: PipelineEvent) => void,
  opts?: { after?: number; signal?: AbortSignal },
): Promise<void> {
  const after = opts?.after ?? 0;
  try {
    const res = await fetch(
      `${apiBase()}/api/jobs/${jobId}/events/stream?after=${after}`,
      {
        method: "GET",
        headers: await authHeaders({ Accept: "text/event-stream" }),
        signal: opts?.signal,
        cache: "no-store",
      },
    );
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Event stream failed (${res.status})`);
    }
    await readSseStream(res, onEvent);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw friendlyFetchError(err, "Job events");
  }
}

export type SceneSectionDraft = {
  id: string;
  title: string;
  narration: string;
  visual_description: string;
  animation_beats: string[];
  duration_seconds: number;
  camera_notes?: string;
  visual_device?: string;
  style_tags?: string[];
};

export type ScenePlanDraft = {
  title: string;
  concept_summary: string;
  style_notes?: string;
  visual_identity?: string;
  palette?: Record<string, string>;
  scenes: SceneSectionDraft[];
};

export type GenerateOptions = {
  prompt: string;
  resolution?: "480p" | "720p" | "1080p";
  skip_render?: boolean;
  length_preset?: LengthPreset;
  audience?: Audience;
  tts_voice?: string;
  plan_only?: boolean;
};

function friendlyFetchError(err: unknown, action: string): Error {
  const msg = err instanceof Error ? err.message : String(err);
  if (
    msg === "Failed to fetch" ||
    msg.includes("NetworkError") ||
    msg.includes("Load failed")
  ) {
    const base = apiBase() || "(same-origin / Next rewrite)";
    return new Error(
      `${action}: cannot reach API at ${base}. Start it with npm run dev:api (or npm run dev:all).`,
    );
  }
  return err instanceof Error ? err : new Error(msg);
}

async function readSseStream(
  res: Response,
  onEvent: (event: PipelineEvent) => void,
): Promise<void> {
  if (!res.body) throw new Error("No response stream");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const dataLine = part
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      const raw = dataLine.replace(/^data:\s*/, "");
      if (!raw) continue;
      onEvent(JSON.parse(raw) as PipelineEvent);
    }
  }

  const trailing = buffer
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.startsWith("data:"));
  if (trailing) {
    onEvent(JSON.parse(trailing.replace(/^data:\s*/, "")) as PipelineEvent);
  }
}

export async function streamGenerate(
  options: GenerateOptions | string,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const opts: GenerateOptions =
    typeof options === "string" ? { prompt: options } : options;
  try {
    const res = await fetch(`${apiBase()}/api/generate/stream`, {
      method: "POST",
      headers: await authHeaders({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      }),
      body: JSON.stringify({
        prompt: opts.prompt,
        skip_render: opts.skip_render ?? false,
        resolution: opts.resolution ?? "720p",
        length_preset: opts.length_preset ?? "standard",
        audience: opts.audience ?? "general",
        tts_voice: opts.tts_voice ?? "Kore",
        plan_only: opts.plan_only ?? true,
      }),
      signal,
      cache: "no-store",
    });

    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Generate failed (${res.status})`);
    }
    await readSseStream(res, onEvent);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw friendlyFetchError(err, "Generate");
  }
}

export async function updateJobPlan(
  jobId: string,
  plan: ScenePlanDraft,
): Promise<void> {
  const res = await fetch(`${apiBase()}/api/jobs/${jobId}/plan`, {
    method: "PUT",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to save plan");
  }
}

export async function streamContinue(
  jobId: string,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
  opts?: { resolution?: string; skip_render?: boolean; tts_voice?: string },
): Promise<void> {
  try {
    const res = await fetch(`${apiBase()}/api/jobs/${jobId}/continue/stream`, {
      method: "POST",
      headers: await authHeaders({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      }),
      body: JSON.stringify({
        resolution: opts?.resolution ?? "720p",
        skip_render: opts?.skip_render ?? false,
        tts_voice: opts?.tts_voice,
      }),
      signal,
      cache: "no-store",
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Continue failed (${res.status})`);
    }
    await readSseStream(res, onEvent);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw friendlyFetchError(err, "Continue");
  }
}

export async function streamRegenerateScene(
  jobId: string,
  sceneId: string,
  onEvent: (event: PipelineEvent) => void,
  opts?: {
    direction?: string;
    section?: SceneSectionDraft;
    signal?: AbortSignal;
  },
): Promise<void> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/regenerate/stream`,
    {
      method: "POST",
      headers: await authHeaders({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      }),
      body: JSON.stringify({
        direction: opts?.direction ?? "",
        section: opts?.section,
        skip_render: false,
      }),
      signal: opts?.signal,
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Regenerate failed (${res.status})`);
  }
  await readSseStream(res, onEvent);
}
