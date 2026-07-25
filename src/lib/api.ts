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
};

type TokenCache = { token: string; expiresAt: number };

let tokenCache: TokenCache | null = null;

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "";
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

export async function fetchHealth(): Promise<{
  ok: boolean;
  model?: string;
  vlm_model?: string;
  openrouter_configured?: boolean;
  tts_configured?: boolean;
  manim_render_enabled?: boolean;
  manim_available?: boolean;
  manim_version?: string;
  auth_configured?: boolean;
  supabase_configured?: boolean;
}> {
  const res = await fetch(`${apiBase()}/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error("API health check failed");
  return res.json();
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

export async function fetchMe(): Promise<{
  user: {
    id: string;
    email?: string | null;
    name?: string | null;
    image?: string | null;
  };
  usage: UsageSnapshot | null;
  supabase_configured: boolean;
}> {
  const res = await fetch(`${apiBase()}/api/me`, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to load account usage");
  return res.json();
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

export async function streamGenerate(
  prompt: string,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${apiBase()}/api/generate/stream`, {
    method: "POST",
    headers: await authHeaders({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    }),
    body: JSON.stringify({ prompt, skip_render: false }),
    signal,
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Generate failed (${res.status})`);
  }

  if (!res.body) throw new Error("No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by blank lines
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

  // Flush trailing frame if present
  const trailing = buffer
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.startsWith("data:"));
  if (trailing) {
    onEvent(JSON.parse(trailing.replace(/^data:\s*/, "")) as PipelineEvent);
  }
}
