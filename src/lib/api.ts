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

export type LanguageOption = {
  id: string;
  label: string;
  native_label: string;
};

export type LengthPreset = "short" | "standard" | "deep";
export type Audience = "hs" | "undergrad" | "general";

export async function fetchHealth(): Promise<{
  ok: boolean;
  model?: string;
  manim_model?: string;
  vlm_model?: string;
  openrouter_configured?: boolean;
  tts_configured?: boolean;
  tts_model?: string;
  tts_voice?: string;
  tts_voices?: TtsVoiceOption[];
  languages?: LanguageOption[];
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
  language?: string;
  tts_voice?: string;
  /** Generate spoken narration (default true). */
  include_audio?: boolean;
  /** Burn narration as on-screen subtitles (default true). */
  include_subtitles?: boolean;
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
        language: opts.language ?? "en",
        tts_voice: opts.tts_voice ?? "Kore",
        include_audio: opts.include_audio ?? true,
        include_subtitles: opts.include_subtitles ?? true,
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

export async function revisePlanWithAI(
  jobId: string,
  instructions: string,
  signal?: AbortSignal,
): Promise<ScenePlanDraft> {
  try {
    const res = await fetch(`${apiBase()}/api/jobs/${jobId}/plan/revise`, {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ instructions }),
      signal,
      cache: "no-store",
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(detail || `Revise plan failed (${res.status})`);
    }
    const data = (await res.json()) as { plan: Record<string, unknown> };
    return planDraftFromRecord(data.plan);
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw friendlyFetchError(err, "Revise storyboard");
  }
}

function planDraftFromRecord(data: Record<string, unknown>): ScenePlanDraft {
  const scenes = (data.scenes as Array<Record<string, unknown>>) || [];
  return {
    title: String(data.title || "Untitled"),
    concept_summary: String(data.concept_summary || ""),
    style_notes: String(data.style_notes || ""),
    visual_identity: String(data.visual_identity || ""),
    palette: (data.palette as Record<string, string>) || {},
    scenes: scenes.map((s, i) => ({
      id: String(s.id || s.scene_id || `scene_${i + 1}`),
      title: String(s.title || `Scene ${i + 1}`),
      narration: String(s.narration || ""),
      visual_description: String(s.visual_description || ""),
      animation_beats: Array.isArray(s.animation_beats)
        ? (s.animation_beats as string[])
        : [],
      duration_seconds: Number(s.duration_seconds) || 8,
      camera_notes: String(s.camera_notes || ""),
      visual_device: String(s.visual_device || ""),
      style_tags: Array.isArray(s.style_tags) ? (s.style_tags as string[]) : [],
    })),
  };
}

export async function streamContinue(
  jobId: string,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
  opts?: {
    resolution?: string;
    skip_render?: boolean;
    language?: string;
    tts_voice?: string;
    include_audio?: boolean;
    include_subtitles?: boolean;
  },
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
        language: opts?.language,
        tts_voice: opts?.tts_voice,
        include_audio: opts?.include_audio,
        include_subtitles: opts?.include_subtitles,
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

export type DocumentAskAction =
  | "explain"
  | "explain_figure"
  | "comment"
  | "simplify"
  | "translate"
  | "quiz"
  | "deepen"
  | "relate"
  | "critique"
  | "summarize_slide"
  | "extract_formula"
  | "key_takeaways"
  | "misconceptions"
  | "turn_into_video_prompt"
  | "freeform";

export type DocumentBlock = {
  id: string;
  slide_id: string;
  type: string;
  text: string;
  html_snippet?: string;
  image_path?: string | null;
  image_url?: string | null;
};

export type DocumentSlide = {
  id: string;
  index: number;
  title: string;
  html?: string;
  html_url?: string | null;
  plain_text?: string;
  block_ids: string[];
};

export type DocumentManifest = {
  doc_id: string;
  title: string;
  source_filename: string;
  source_ext: string;
  status: string;
  slide_count: number;
  slides: DocumentSlide[];
  blocks: Record<string, DocumentBlock>;
  markdown_url?: string | null;
  created_at?: string;
};

export type DocumentListItem = {
  doc_id: string;
  title?: string | null;
  source_filename?: string | null;
  created_at?: string | null;
  status?: string | null;
  slide_count?: number;
  kind?: string;
};

export type DocumentAnnotation = {
  id: string;
  doc_id: string;
  slide_id: string;
  block_id?: string | null;
  action: string;
  message: string;
  reply: string;
  author: string;
  created_at: string;
  pinned?: boolean;
};

export type DocumentDetail = {
  doc_id: string;
  manifest: DocumentManifest;
  annotations: DocumentAnnotation[];
  urls?: Record<string, string>;
};

export type DocumentAskTurn = {
  role: "user" | "assistant";
  content: string;
};

export type DocumentAskResult = {
  doc_id: string;
  slide_id: string;
  block_id?: string | null;
  action: DocumentAskAction;
  reply: string;
  comment_id?: string | null;
  video_prompt?: string | null;
  user_message?: string;
};

export async function listDocuments(limit = 50): Promise<DocumentListItem[]> {
  const res = await fetch(`${apiBase()}/api/documents?limit=${limit}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to list documents");
  const data = (await res.json()) as { documents: DocumentListItem[] };
  return data.documents || [];
}

export async function getDocument(docId: string): Promise<DocumentDetail> {
  const res = await fetch(`${apiBase()}/api/documents/${docId}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to load document");
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${apiBase()}/api/documents/${docId}`, {
    method: "DELETE",
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Delete failed (${res.status})`);
  }
}

export async function uploadDocument(file: File): Promise<{
  doc_id: string;
  title: string;
  slide_count: number;
  status: string;
  manifest: DocumentManifest;
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBase()}/api/documents/upload`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

/** Progressive upload: emits status / slide_ready / complete as pages convert. */
export async function uploadDocumentStream(
  file: File,
  onEvent: (event: PipelineEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBase()}/api/documents/upload/stream`, {
    method: "POST",
    headers: await authHeaders({ Accept: "text/event-stream" }),
    body: form,
    signal,
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  await readSseStream(res, onEvent);
}

export async function askDocument(
  docId: string,
  body: {
    action: DocumentAskAction;
    slide_id: string;
    block_id?: string | null;
    message?: string;
    language?: string;
    save_as_comment?: boolean;
    prior_reply?: string | null;
    conversation?: DocumentAskTurn[];
  },
): Promise<DocumentAskResult> {
  const res = await fetch(`${apiBase()}/api/documents/${docId}/ask`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Ask failed (${res.status})`);
  }
  return res.json();
}

export async function saveDocumentComment(
  docId: string,
  body: {
    slide_id: string;
    block_id?: string | null;
    action?: string;
    message?: string;
    reply: string;
    author?: string;
  },
): Promise<DocumentAnnotation> {
  const res = await fetch(`${apiBase()}/api/documents/${docId}/comments`, {
    method: "POST",
    headers: await authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Save comment failed (${res.status})`);
  }
  return res.json();
}

export async function deleteDocumentComment(
  docId: string,
  commentId: string,
): Promise<void> {
  const res = await fetch(
    `${apiBase()}/api/documents/${docId}/comments/${commentId}`,
    {
      method: "DELETE",
      headers: await authHeaders(),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Delete comment failed (${res.status})`);
  }
}

// ── Interactive Scene Editor ──────────────────────────────────────────────

export type SceneElementPoint = { x: number; y: number };

export type SceneElement = {
  id: string;
  type: string;
  variable_name: string;
  line_number: number;
  x: number;
  y: number;
  width: number;
  height: number;
  radius?: number;
  fill_color: string | null;
  fill_opacity: number;
  stroke_color: string | null;
  stroke_width: number;
  rotation: number;
  scale: number;
  text?: string | null;
  font_size?: number | null;
  points?: SceneElementPoint[];
  start_point?: SceneElementPoint;
  end_point?: SceneElementPoint;
};

export type SceneElementEdit = Partial<SceneElement> & {
  variable_name: string;
  line_number: number;
};

export async function fetchSceneElements(
  jobId: string,
  sceneId: string,
): Promise<{ elements: SceneElement[]; scene_id: string; job_id: string }> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/elements`,
    {
      headers: await authHeaders(),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Fetch elements failed (${res.status})`);
  }
  return res.json();
}

export async function saveSceneElements(
  jobId: string,
  sceneId: string,
  edits: SceneElementEdit[],
): Promise<{ ok: boolean; edit_count: number }> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/elements`,
    {
      method: "PUT",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ edits }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Save elements failed (${res.status})`);
  }
  return res.json();
}

export async function applySceneEdits(
  jobId: string,
  sceneId: string,
  edits: SceneElementEdit[],
): Promise<{
  ok: boolean;
  scene_id: string;
  video_url: string | null;
  elements: SceneElement[];
  render_log: string | null;
}> {
  const res = await fetch(
    `${apiBase()}/api/jobs/${jobId}/scenes/${sceneId}/apply-edits`,
    {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ edits }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Apply edits failed (${res.status})`);
  }
  return res.json();
}
