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
    files?: string[];
  }>;
  events?: Array<Record<string, unknown>>;
  urls?: Record<string, string>;
};

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "";
}

export function assetUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return `${apiBase()}${path}`;
}

export async function fetchHealth(): Promise<{
  ok: boolean;
  model?: string;
  openrouter_configured?: boolean;
  tts_configured?: boolean;
  manim_render_enabled?: boolean;
  manim_available?: boolean;
  manim_version?: string;
}> {
  const res = await fetch(`${apiBase()}/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error("API health check failed");
  return res.json();
}

export async function listJobs(): Promise<JobSummary[]> {
  const res = await fetch(`${apiBase()}/api/jobs`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to list jobs");
  const data = await res.json();
  return data.jobs || [];
}

export async function fetchJob(jobId: string): Promise<JobDetail> {
  const res = await fetch(`${apiBase()}/api/jobs/${jobId}`, { cache: "no-store" });
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
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
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
