import type { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { UI, widgetMeta } from "./config";
import { ApiError, apiBytes, apiJson, signedMediaUrl, startSse } from "./fastapi";
import { resourceResult, WIDGETS } from "./widgets";

const ASK_ACTIONS = [
  "explain",
  "explain_figure",
  "comment",
  "simplify",
  "translate",
  "quiz",
  "deepen",
  "relate",
  "critique",
  "summarize_slide",
  "summarize_document",
  "outline_document",
  "extract_formula",
  "key_takeaways",
  "misconceptions",
  "turn_into_video_prompt",
  "freeform",
] as const;

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_EMBED_IMAGE_BYTES = 400_000;
const MAX_EMBED_IMAGES = 4;

type ImagePart = { type: "image"; data: string; mimeType: string };

const JOB_OUTPUT = z.looseObject({
  job_id: z.string(),
  title: z.string(),
  status: z.string(),
  next_step: z.string(),
  message: z.string(),
  error: z.string().nullable(),
  poll_again: z.boolean(),
  awaiting_user: z.boolean(),
  awaiting_render: z.boolean(),
  has_final_video: z.boolean(),
  video_url: z.string().nullable(),
  scenes: z.array(z.looseObject({ id: z.string(), title: z.string() })),
});

const SCENE_OUTPUT = z.looseObject({
  job_id: z.string(),
  id: z.string(),
  title: z.string(),
  narration: z.string(),
  has_code: z.boolean(),
  code: z.string().nullable(),
});

const DOCUMENT_OUTPUT = z.looseObject({
  doc_id: z.string(),
  title: z.string(),
  status: z.string(),
  slide_count: z.number(),
  current_slide_id: z.string().nullable(),
  slides: z.array(z.looseObject({ id: z.string(), index: z.number(), title: z.string() })),
});

const JOB_LIST_OUTPUT = z.looseObject({ jobs: z.array(z.looseObject({})) });
const DOCUMENT_LIST_OUTPUT = z.looseObject({ documents: z.array(z.looseObject({})) });
const USAGE_OUTPUT = z.looseObject({ storage_mode: z.string(), note: z.string() });
const SEARCH_OUTPUT = z.looseObject({
  results: z.array(z.looseObject({ id: z.string(), title: z.string(), url: z.string() })),
});

function fail(err: unknown) {
  const message =
    err instanceof ApiError
      ? err.message
      : err instanceof Error
        ? err.message
        : String(err);
  const quota =
    err instanceof ApiError && (err.status === 402 || (err.code && err.code.includes("LIMIT")));
  const text = quota
    ? `Monthly limit reached: ${message}. Tell the user their Now I Get It generation or token quota is used up.`
    : message;
  return {
    isError: true as const,
    content: [{ type: "text" as const, text }],
  };
}

/**
 * `structuredContent` carries the full payload. The text block is the fallback for
 * hosts that ignore structured output, so pass `textData` to put a digest there
 * rather than a second copy of everything.
 */
function ok(
  data: Record<string, unknown>,
  widgetUri?: string,
  textExtra?: string,
  images?: ImagePart[],
  textData?: Record<string, unknown>,
) {
  const body = JSON.stringify(textData ?? data);
  const text = textExtra ? `${textExtra}\n\n${body}` : body;
  return {
    structuredContent: data,
    content: [
      { type: "text" as const, text },
      ...(images || []),
    ],
    _meta: widgetUri ? widgetMeta(widgetUri) : undefined,
  };
}

async function embedImage(
  origin: string,
  path: string | null | undefined,
): Promise<ImagePart | null> {
  if (!path) return null;
  try {
    const { bytes, mimeType } = await apiBytes(origin, path);
    if (!mimeType.startsWith("image/") || bytes.byteLength === 0) return null;
    if (bytes.byteLength > MAX_EMBED_IMAGE_BYTES) return null;
    return {
      type: "image",
      data: bytes.toString("base64"),
      mimeType,
    };
  } catch {
    return null;
  }
}

async function embedImages(
  origin: string,
  paths: Array<string | null | undefined>,
): Promise<ImagePart[]> {
  const out: ImagePart[] = [];
  for (const path of paths) {
    if (out.length >= MAX_EMBED_IMAGES) break;
    const part = await embedImage(origin, path);
    if (part) out.push(part);
  }
  return out;
}

function sceneSummaries(
  plan: Record<string, unknown> | null | undefined,
  artifacts?: Array<Record<string, unknown>>,
) {
  const scenes = Array.isArray(plan?.scenes) ? (plan.scenes as Record<string, unknown>[]) : [];
  const byId = new Map<string, Record<string, unknown>>();
  for (const art of artifacts || []) {
    const id = String(art.scene_id || "");
    if (id) byId.set(id, art);
  }
  return scenes.map((scene, i) => {
    const beats = Array.isArray(scene.beats)
      ? (scene.beats as Array<Record<string, unknown>>).map((beat) => ({
          visual_action: String(beat.visual_action || ""),
          narration: String(beat.narration || ""),
        }))
      : [];
    const narration =
      typeof scene.narration === "string" && scene.narration.trim()
        ? scene.narration
        : beats.map((b) => b.narration).filter(Boolean).join(" ");
    const id = String(scene.id || scene.scene_id || `scene_${i + 1}`);
    const art = byId.get(id) || {};
    const reviews = Array.isArray(art.vlm_reviews)
      ? (art.vlm_reviews as Array<Record<string, unknown>>)
      : [];
    const lastReview = reviews.length ? reviews[reviews.length - 1] : null;
    const previewPath =
      (typeof lastReview?.frame_url === "string" && lastReview.frame_url) ||
      (typeof art.video_url === "string" ? null : null);
    return {
      id,
      title: String(scene.title || `Scene ${i + 1}`),
      duration_seconds: Number(scene.duration_seconds) || null,
      visual_description: typeof scene.visual_description === "string" ? scene.visual_description : "",
      narration,
      beats,
      has_code: typeof art.code_final === "string" && art.code_final.length > 40,
      clip_path: typeof art.video_url === "string" ? art.video_url : null,
      preview_path:
        typeof lastReview?.frame_url === "string" ? lastReview.frame_url : previewPath,
      vlm: lastReview
        ? {
            approved: Boolean(lastReview.approved),
            issues: Array.isArray(lastReview.issues)
              ? (lastReview.issues as unknown[]).map(String).slice(0, 8)
              : [],
            clarity_score:
              typeof lastReview.clarity_score === "number" ? lastReview.clarity_score : null,
          }
        : null,
    };
  });
}

function storyboardStop(payload: Record<string, unknown>): Record<string, unknown> {
  const options = (payload.options || {}) as Record<string, unknown>;
  const optionsConfirmed = Boolean(options.production_options_confirmed);
  return {
    ...payload,
    next_step: optionsConfirmed
      ? "present_storyboard_to_user"
      : "ask_production_options",
    poll_again: false,
    awaiting_user: true,
    do_not_call: [
      "render_video",
      "continue_video",
      "video_codegen_spec",
      "submit_scene_code",
      "list_jobs",
    ],
    ask_after_plan: optionsConfirmed
      ? []
      : [
          { id: "include_audio", question: "Spoken narration on or off?" },
          { id: "include_subtitles", question: "Burned-in subtitles on or off?" },
          { id: "tts_voice", question: "Which narrator voice?" },
        ],
  };
}

const PRODUCTION_OPTIONS_HINT =
  "Ask the user: (1) spoken narration on or off? (2) burned-in subtitles on or off? (3) which narrator voice? Then call update_video_options with those answers. Do not write Manim or render until that tool returns production_options_confirmed true.";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollJobUntilSettled(
  origin: string,
  jobId: string,
  timeoutMs = 150_000,
) {
  const deadline = Date.now() + timeoutMs;
  let job = await apiJson<Record<string, unknown>>(
    origin,
    `/api/jobs/${encodeURIComponent(jobId)}`,
  );
  let payload = await jobPayload(origin, job);
  while (Date.now() < deadline) {
    if (payload.has_final_video || payload.status === "complete") {
      return { payload, settled: true as const };
    }
    if (payload.status === "error" || payload.error) {
      return { payload, settled: true as const };
    }
    if (!payload.running && payload.status === "awaiting_plan") {
      return { payload, settled: false as const };
    }
    await sleep(6_000);
    job = await apiJson<Record<string, unknown>>(
      origin,
      `/api/jobs/${encodeURIComponent(jobId)}`,
    );
    payload = await jobPayload(origin, job);
  }
  return { payload, settled: false as const };
}

async function jobPayload(origin: string, job: Record<string, unknown>) {
  const runtime = (job.runtime || {}) as Record<string, unknown>;
  const meta = (job.meta || {}) as Record<string, unknown>;
  const plan = (job.scene_plan || {}) as Record<string, unknown>;
  const settings = (meta.settings || {}) as Record<string, unknown>;
  const status = String(runtime.status || meta.status || "unknown");
  const error =
    typeof runtime.error === "string" && runtime.error.trim() ? runtime.error : null;
  const videoPath =
    (typeof job.final_video_url === "string" && job.final_video_url) ||
    (runtime.has_final_video ? `/api/jobs/${job.job_id}/file/final.mp4` : null);
  const video_url = videoPath ? await signedMediaUrl(origin, videoPath) : "";
  const awaiting =
    status === "awaiting_plan" ||
    Boolean((job.result as Record<string, unknown> | undefined)?.awaiting_plan_confirm);
  const awaitingRender = status === "awaiting_render";
  const running = Boolean(runtime.running) || status === "running";
  const done = status === "complete" || Boolean(video_url);
  const failed = Boolean(error) || status === "error";
  const optionsConfirmed = Boolean(settings.production_options_confirmed);
  const includeAudio =
    typeof settings.include_audio === "boolean" ? settings.include_audio : null;
  const includeSubtitles =
    typeof settings.include_subtitles === "boolean" ? settings.include_subtitles : null;
  let message: string;
  let next_step: string;
  if (failed) {
    message =
      `Render failed: ${error || "unknown error"}. If this is a Manim error, fix that scene with submit_scene_code, then call render_video once. Do not retry the same call unchanged.`;
    next_step = "fix_and_rerender";
  } else if (awaiting && !optionsConfirmed) {
    message =
      "STOP. Show the numbered storyboard (title + narration per scene). Then ask whether they want spoken audio, burned-in subtitles, and which voice. Call update_video_options with their answers. Do not write Manim or render until production_options_confirmed is true.";
    next_step = "ask_production_options";
  } else if (awaiting) {
    message =
      "STOP. Show the numbered storyboard to the user (title + narration per scene) and wait for approval or edit requests. They can change any scene with update_scene, or you can rewrite the plan with revise_plan / edit_storyboard. Do not render or write Manim yet.";
    next_step = "present_storyboard_to_user";
  } else if (awaitingRender) {
    message =
      "All scene code is saved. Call render_video with user_confirmed true, then poll get_job if poll_again is true.";
    next_step = "call_render_video";
  } else if (done) {
    message =
      "Video is ready. Show video_url and the scene preview images to the user. They can still retouch a scene or change narration.";
    next_step = "show_video";
  } else if (running) {
    message = "Still rendering. Wait poll_after_seconds, then call get_job with the same job_id. Do not start a new job.";
    next_step = "poll_get_job";
  } else if (status === "interrupted") {
    message =
      "Generation stopped mid-render. Call render_video once with user_confirmed true to resume. If it fails again, wait — do not keep retrying the same call.";
    next_step = "call_render_video";
  } else {
    message = "Job is not finished. Call get_job again or fix scene code if render failed.";
    next_step = "poll_get_job";
  }
  const rawScenes = sceneSummaries(
    plan,
    Array.isArray(job.scenes) ? (job.scenes as Array<Record<string, unknown>>) : [],
  );
  const scenes = await Promise.all(
    rawScenes.map(async (scene) => ({
      ...scene,
      preview_url: scene.preview_path
        ? await signedMediaUrl(origin, scene.preview_path)
        : "",
      clip_url: scene.clip_path ? await signedMediaUrl(origin, scene.clip_path) : "",
      preview_path: undefined,
      clip_path: undefined,
    })),
  );
  const result = (job.result || {}) as Record<string, unknown>;
  const resultScenes = Array.isArray(result.scenes)
    ? (result.scenes as Array<Record<string, unknown>>).map((item) => ({
        id: String(item.id || item.scene_id || ""),
        title: String(item.title || ""),
        approved: item.vlm_approved ?? item.approved ?? null,
        frame_url: typeof item.frame_url === "string" ? item.frame_url : null,
      }))
    : [];
  return {
    job_id: String(job.job_id || ""),
    title: String(plan.title || meta.title || "Untitled"),
    status,
    running,
    error,
    awaiting_plan: awaiting,
    awaiting_user: awaiting,
    awaiting_render: awaitingRender,
    poll_again: running && !done && !failed,
    poll_after_seconds: running ? 8 : 0,
    next_step,
    message,
    prompt: typeof meta.prompt === "string" ? meta.prompt : null,
    concept_summary: typeof plan.concept_summary === "string" ? plan.concept_summary : null,
    options: {
      tts_voice: typeof settings.tts_voice === "string" ? settings.tts_voice : null,
      language: typeof settings.language === "string" ? settings.language : "en",
      include_audio: includeAudio,
      include_subtitles: includeSubtitles,
      production_options_confirmed: optionsConfirmed,
    },
    ask_after_plan: optionsConfirmed
      ? []
      : awaiting
        ? [
            { id: "include_audio", question: "Spoken narration on or off?" },
            { id: "include_subtitles", question: "Burned-in subtitles on or off?" },
            { id: "tts_voice", question: "Which narrator voice?" },
          ]
        : [],
    scenes,
    results: resultScenes,
    video_url: video_url || null,
    library_url: `${origin}/library`,
    has_final_video: Boolean(runtime.has_final_video || video_url),
    editable: true,
    edit_tools: [
      "update_scene",
      "edit_storyboard",
      "revise_plan",
      "update_video_options",
      "get_scene",
      "submit_scene_code",
      "retouch_scene",
    ],
  };
}

/**
 * What goes in the text block. Structured content still carries everything; this
 * drops what the model does not need for the turn it is on — scene narration
 * while a render is in flight, review details before a clip exists.
 */
function jobDigest(payload: Record<string, unknown>): Record<string, unknown> {
  const scenes = Array.isArray(payload.scenes)
    ? (payload.scenes as Array<Record<string, unknown>>)
    : [];
  const polling = Boolean(payload.poll_again);
  const awaitingUser = Boolean(payload.awaiting_user);
  return {
    job_id: payload.job_id,
    title: payload.title,
    status: payload.status,
    next_step: payload.next_step,
    message: payload.message,
    error: payload.error ?? null,
    awaiting_user: awaitingUser,
    awaiting_render: Boolean(payload.awaiting_render),
    poll_again: polling,
    poll_after_seconds: payload.poll_after_seconds ?? 0,
    do_not_call: payload.do_not_call,
    ask_after_plan: payload.ask_after_plan,
    options: payload.options,
    video_url: payload.video_url ?? null,
    has_final_video: Boolean(payload.has_final_video),
    library_url: payload.library_url,
    scenes: scenes.map((scene, i) => {
      const base = {
        id: String(scene.id || `scene_${i + 1}`),
        title: String(scene.title || `Scene ${i + 1}`),
        has_code: Boolean(scene.has_code),
      };
      // Mid-render polls repeat every 8s and nothing per-scene has changed.
      if (polling) return base;
      // The storyboard turn is the one where narration has to be read out loud.
      if (awaitingUser) {
        return {
          ...base,
          duration_seconds: scene.duration_seconds ?? null,
          narration: String(scene.narration || ""),
        };
      }
      return {
        ...base,
        narration: String(scene.narration || ""),
        preview_url: scene.preview_url || "",
        clip_url: scene.clip_url || "",
        vlm: scene.vlm ?? null,
      };
    }),
  };
}

async function jobResult(origin: string, job: Record<string, unknown>, extraText?: string) {
  const payload = await jobPayload(origin, job);
  // Each frame is ~500 KB of base64. A render poll returns the same frames it
  // returned 8 seconds ago, so only pay for them once the job stops moving.
  const images = payload.poll_again
    ? []
    : await embedImages(
        origin,
        payload.scenes.map((scene) => {
          const match = (job.scenes as Array<Record<string, unknown>> | undefined)?.find(
            (art) => String(art.scene_id) === scene.id,
          );
          const reviews = Array.isArray(match?.vlm_reviews)
            ? (match?.vlm_reviews as Array<Record<string, unknown>>)
            : [];
          const last = reviews.length ? reviews[reviews.length - 1] : null;
          return typeof last?.frame_url === "string" ? last.frame_url : null;
        }),
      );
  const widget = payload.has_final_video ? UI.videoPlayer : UI.jobProgress;
  const text =
    extraText ||
    (payload.has_final_video
      ? "Video is ready. Show video_url and the preview images."
      : payload.message);
  return ok(payload, widget, text, images, jobDigest(payload));
}

async function documentPayload(
  origin: string,
  detail: {
    doc_id: string;
    manifest: {
      title?: string;
      status?: string;
      slides?: Array<{
        id: string;
        index: number;
        title?: string;
        html_url?: string | null;
        block_ids?: string[];
      }>;
      blocks?: Record<
        string,
        { id: string; slide_id: string; type?: string; text?: string; image_url?: string | null }
      >;
    };
  },
  currentSlideId?: string,
) {
  const blocks = detail.manifest.blocks || {};
  const slides = await Promise.all(
    (detail.manifest.slides || []).map(async (slide) => ({
      id: slide.id,
      index: slide.index,
      title: slide.title || `Slide ${slide.index + 1}`,
      html_url: slide.html_url
        ? await signedMediaUrl(origin, slide.html_url)
        : "",
      blocks: await Promise.all(
        (slide.block_ids || []).map(async (id) => {
          const block = blocks[id];
          const imagePath =
            typeof (block as { image_url?: string } | undefined)?.image_url === "string"
              ? (block as { image_url: string }).image_url
              : "";
          return {
            id,
            type: block?.type || "other",
            text: (block?.text || "").slice(0, 400),
            image_path: imagePath.includes("/file/") ? imagePath : "",
            image_url: imagePath.includes("/file/")
              ? await signedMediaUrl(origin, imagePath)
              : imagePath || "",
          };
        }),
      ),
    })),
  );
  return {
    doc_id: detail.doc_id,
    title: detail.manifest.title || "Document",
    status: detail.manifest.status || "ready",
    slide_count: slides.length,
    slides,
    current_slide_id: currentSlideId || slides[0]?.id || null,
    understand_url: `${origin}/understand`,
  };
}

async function documentResult(
  origin: string,
  detail: Parameters<typeof documentPayload>[1],
  currentSlideId?: string,
  extra?: Record<string, unknown>,
  textExtra?: string,
) {
  const doc = await documentPayload(origin, detail, currentSlideId);
  const slide =
    doc.slides.find((item) => item.id === currentSlideId) ||
    doc.slides.find((item) => item.id === doc.current_slide_id) ||
    doc.slides[0];
  const blocks = slide?.blocks || [];
  const wantedId = typeof extra?.block_id === "string" ? extra.block_id : "";
  const wanted = wantedId ? blocks.filter((block) => block.id === wantedId && block.image_path) : [];
  const figures = blocks.filter((block) => block.image_path);
  const paths = (wanted.length ? wanted : figures).map((block) => block.image_path);
  const images = await embedImages(origin, paths);
  const extras = { ...(extra || {}) };
  // The reply is already the text prefix — don't repeat it inside the digest.
  if (textExtra && extras.reply === textExtra) delete extras.reply;
  const digest = {
    doc_id: doc.doc_id,
    title: doc.title,
    status: doc.status,
    slide_count: doc.slide_count,
    current_slide_id: doc.current_slide_id,
    understand_url: doc.understand_url,
    ...extras,
    current_slide: slide
      ? {
          id: slide.id,
          index: slide.index,
          title: slide.title,
          html_url: slide.html_url,
          blocks: slide.blocks,
        }
      : null,
    // Ids and titles only — ask for a slide by id to get its blocks.
    slides: doc.slides.map((item) => ({
      id: item.id,
      index: item.index,
      title: item.title,
    })),
  };
  return ok({ ...doc, ...extra }, UI.slidesTutor, textExtra, images, digest);
}

export function registerNowIGetIt(server: McpServer, origin: string) {
  for (const widget of Object.values(WIDGETS)) {
    server.registerResource(
      widget.name,
      widget.uri,
      {
        title: widget.title,
        description: widget.title,
        mimeType: "text/html;profile=mcp-app",
      },
      async () => resourceResult(widget.uri, widget.html),
    );
  }

  server.registerTool(
    "video_planning_spec",
    {
      title: "Video planning spec",
      description:
        "Return the ScenePlan JSON schema. Next: YOU write the plan as a JSON object, then call create_video with a `plan` argument (not inside prompt).",
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const spec = await apiJson<Record<string, unknown>>(origin, "/api/video/planning-spec");
        return ok(
          spec,
          undefined,
          "Write ScenePlan JSON, then call create_video with arguments { prompt, plan } where plan is the object — never a string inside prompt.",
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "create_video",
    {
      title: "Submit video storyboard",
      description:
        "Save YOUR ScenePlan. `plan` is a required JSON object argument (title, concept_summary, scenes[] with beats). Do not put JSON inside prompt. Do not choose voice, audio, or subtitles here. After this tool returns, STOP, show the storyboard, and ask the user those production options. Wait for approval. Do not call render_video yet.",
      inputSchema: z.object({
        prompt: z.string().min(3).max(8000).describe("Short user request, e.g. explain backpropagation"),
        plan: z
          .object({
            title: z.string().min(1),
            concept_summary: z.string().min(1),
            style_notes: z.string().optional(),
            visual_identity: z.string().optional(),
            recurring_elements: z.array(z.string()).optional(),
            palette: z.record(z.string(), z.string()).optional(),
            scenes: z
              .array(
                z.object({
                  id: z.string().min(1),
                  title: z.string().min(1),
                  duration_seconds: z.number().optional(),
                  visual_description: z.string().optional(),
                  camera_notes: z.string().optional(),
                  visual_device: z.string().optional(),
                  beats: z
                    .array(
                      z.object({
                        visual_action: z.string().min(1),
                        narration: z.string().min(1),
                      }),
                    )
                    .optional(),
                  narration: z.string().optional(),
                  animation_beats: z.array(z.string()).optional(),
                }),
              )
              .min(1),
          })
          .describe("ScenePlan object. Required. Not a string. Not inside prompt."),
        length_preset: z.enum(["short", "standard", "deep"]).optional(),
        audience: z.enum(["hs", "undergrad", "general"]).optional(),
        language: z.string().min(2).max(16).optional(),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ prompt, plan, length_preset, audience, language }) => {
      try {
        const started = await startSse(
          origin,
          "/api/generate/stream",
          JSON.stringify({
            prompt,
            resolution: "720p",
            skip_render: false,
            length_preset: length_preset ?? "standard",
            scene_pacing: "balanced",
            audience: audience ?? "general",
            language: language ?? "en",
            plan_only: true,
            scene_plan: plan,
          }),
          { "Content-Type": "application/json" },
          {
            untilType: ["plan_ready", "plan", "error"],
            timeoutMs: 30_000,
          },
        );
        const jobId = started.jobId;
        if (!jobId) return fail(new Error("Video job did not start (no job_id)."));
        const job = await apiJson<Record<string, unknown>>(origin, `/api/jobs/${jobId}`);
        const payload = storyboardStop(await jobPayload(origin, job));
        return ok(
          payload,
          UI.jobProgress,
          "STOP AND SHOW THE USER THIS STORYBOARD. Numbered scenes with titles and narration. Then ask whether they want spoken audio, burned-in subtitles, and which voice. Call update_video_options with their answers. Do not render, do not write Manim, do not list_jobs until they reply.",
          undefined,
          jobDigest(payload),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "video_codegen_spec",
    {
      title: "Manim codegen spec",
      description:
        "Only after the user approved the storyboard AND you saved their audio/subtitle/voice choices with update_video_options. Returns Manim rules for one scene. You write Python, then submit_scene_code. Text() only — never MathTex.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1).describe("e.g. scene_1"),
      }),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ job_id, scene_id }) => {
      try {
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const preview = await jobPayload(origin, job);
        if (!preview.options.production_options_confirmed) {
          return fail(new Error(PRODUCTION_OPTIONS_HINT));
        }
        const spec = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}/scenes/${encodeURIComponent(scene_id)}/codegen-spec`,
        );
        return ok(
          spec,
          undefined,
          "Write one complete Manim Community Scene file, then call submit_scene_code with that code.",
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "submit_scene_code",
    {
      title: "Submit scene Manim code",
      description:
        "Save Manim for one scene after the user approved the storyboard and you saved audio/subtitle/voice with update_video_options. Repeat until every scene has code, then render_video with user_confirmed true.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1),
        code: z
          .string()
          .min(40)
          .max(120_000)
          .describe("Complete Python source: from manim import * and a Scene subclass."),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ job_id, scene_id, code }) => {
      try {
        const previewJob = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const preview = await jobPayload(origin, previewJob);
        if (!preview.options.production_options_confirmed) {
          return fail(new Error(PRODUCTION_OPTIONS_HINT));
        }
        const saved = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}/scenes/${encodeURIComponent(scene_id)}/code`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code }),
          },
        );
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = await jobPayload(origin, job);
        const ready = Boolean(saved.ready_to_render);
        const merged = { ...payload, ...saved };
        return ok(
          merged,
          UI.jobProgress,
          ready
            ? "All scenes have code. Call render_video with user_confirmed true, then keep polling get_job if poll_again is true."
            : `Saved ${scene_id}. Still missing: ${JSON.stringify(saved.scenes_missing_code)}.`,
          undefined,
          jobDigest(merged),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  async function startHostRender(job_id: string) {
    await startSse(
      origin,
      `/api/jobs/${encodeURIComponent(job_id)}/continue/stream`,
      JSON.stringify({
        resolution: "720p",
        skip_render: false,
        skip_codegen: true,
        skip_vlm: true,
      }),
      { "Content-Type": "application/json" },
      { untilType: ["status", "error", "complete"], timeoutMs: 25_000 },
    );
    const waited = await pollJobUntilSettled(origin, job_id);
    const job = await apiJson<Record<string, unknown>>(
      origin,
      `/api/jobs/${encodeURIComponent(job_id)}`,
    );
    if (waited.payload.error || waited.payload.status === "error") {
      return fail(
        new Error(
          String(
            waited.payload.error ||
              "Render failed with no details. Do not retry the same call unchanged — inspect the error, fix scene code if needed, then call render_video once.",
          ),
        ),
      );
    }
    if (waited.payload.has_final_video) {
      return jobResult(
        origin,
        job,
        "Video is ready. Play the video and show the scene preview images.",
      );
    }
    if (waited.payload.poll_again) {
      const payload = { ...(await jobPayload(origin, job)), poll_again: true, poll_after_seconds: 8 };
      return ok(
        payload,
        UI.jobProgress,
        "Still rendering. Wait 8 seconds, then call get_job with this same job_id. Do not start a new job.",
        undefined,
        jobDigest(payload),
      );
    }
    if (waited.payload.status === "awaiting_render") {
      return jobResult(
        origin,
        job,
        "Code is saved but render has not started. Call render_video with user_confirmed true.",
      );
    }
    return jobResult(origin, job);
  }

  server.registerTool(
    "render_video",
    {
      title: "Render video",
      description:
        "Render ONLY after (1) the user approved the storyboard, (2) update_video_options saved audio/subtitles/voice, and (3) every scene has submit_scene_code. You MUST pass user_confirmed=true. This waits on the worker; if poll_again, keep calling get_job.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        user_confirmed: z
          .boolean()
          .describe("Must be true. Confirms the user already approved the storyboard in chat."),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ job_id, user_confirmed }) => {
      try {
        if (user_confirmed !== true) {
          return fail(
            new Error(
              "user_confirmed must be true. First show the storyboard, wait for the user to approve, save production options with update_video_options, submit Manim for every scene, then call render_video again.",
            ),
          );
        }
        const previewJob = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const preview = await jobPayload(origin, previewJob);
        if (!preview.options.production_options_confirmed) {
          return fail(new Error(PRODUCTION_OPTIONS_HINT));
        }
        return await startHostRender(job_id);
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "continue_video",
    {
      title: "Continue video render",
      description:
        "Alias of render_video. Do not call until the user approved the storyboard and all scene code is submitted. Pass user_confirmed true. Prefer render_video.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        user_confirmed: z.boolean().optional(),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({ job_id, user_confirmed }) => {
      try {
        if (user_confirmed !== true) {
          return fail(
            new Error(
              "The user has not confirmed. Show the storyboard, save audio/subtitles/voice with update_video_options, wait for approval, then submit_scene_code for every scene, then render_video with user_confirmed true.",
            ),
          );
        }
        const previewJob = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const preview = await jobPayload(origin, previewJob);
        if (!preview.options.production_options_confirmed) {
          return fail(new Error(PRODUCTION_OPTIONS_HINT));
        }
        return await startHostRender(job_id);
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "revise_plan",
    {
      title: "Replace storyboard",
      description:
        "Replace the storyboard after the user asked for edits. Pass the full plan object (not instructions). Then STOP and show the new storyboard; wait for approval.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        plan: z
          .object({
            title: z.string().min(1),
            concept_summary: z.string().min(1),
            scenes: z.array(z.record(z.string(), z.unknown())).min(1),
          })
          .describe("Full ScenePlan JSON object. There is no instructions field."),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ job_id, plan }) => {
      try {
        await apiJson(origin, `/api/jobs/${encodeURIComponent(job_id)}/plan`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plan }),
        });
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = storyboardStop(await jobPayload(origin, job));
        return ok(
          payload,
          UI.jobProgress,
          "STOP. Show the updated storyboard to the user and wait for approval. They can still change any scene. Do not render yet.",
          undefined,
          jobDigest(payload),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "edit_storyboard",
    {
      title: "Edit storyboard from instructions",
      description:
        "Apply the user's requested storyboard changes in plain English (add/remove/rewrite scenes, change narration). Then STOP and show the new storyboard.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        instructions: z
          .string()
          .min(2)
          .max(2000)
          .describe("What the user wants changed, in their own words."),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ job_id, instructions }) => {
      try {
        await apiJson(origin, `/api/jobs/${encodeURIComponent(job_id)}/plan/revise`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instructions }),
        });
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = storyboardStop(await jobPayload(origin, job));
        return ok(
          payload,
          UI.jobProgress,
          "STOP. Show the revised storyboard and wait for approval. Do not render yet.",
          undefined,
          jobDigest(payload),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "update_scene",
    {
      title: "Edit one scene",
      description:
        "Change one scene's title, narration, visuals, or beats without rewriting the whole plan. Use this when the user wants to tweak a specific scene.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1),
        title: z.string().min(1).max(200).optional(),
        narration: z.string().min(1).max(8000).optional(),
        visual_description: z.string().max(4000).optional(),
        duration_seconds: z.number().min(2).max(120).optional(),
        visual_device: z.string().max(200).optional(),
        camera_notes: z.string().max(2000).optional(),
        beats: z
          .array(
            z.object({
              visual_action: z.string().min(1),
              narration: z.string().min(1),
            }),
          )
          .optional(),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ job_id, scene_id, ...patch }) => {
      try {
        const body = Object.fromEntries(
          Object.entries(patch).filter(([, value]) => value !== undefined),
        );
        if (Object.keys(body).length === 0) {
          return fail(new Error("Provide at least one field to change on this scene."));
        }
        await apiJson(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}/scenes/${encodeURIComponent(scene_id)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
        );
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = storyboardStop(await jobPayload(origin, job));
        return ok(
          payload,
          UI.jobProgress,
          `Updated ${scene_id}. Show the new storyboard and wait — do not render until they approve.`,
          undefined,
          jobDigest(payload),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "update_video_options",
    {
      title: "Save audio, subtitles, voice",
      description:
        "Required after the storyboard. Record the user's choices: spoken audio on/off, burned-in subtitles on/off, and narrator voice. Call this before video_codegen_spec or render_video. Do not invent defaults — ask first.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        include_audio: z
          .boolean()
          .describe("User's choice: spoken narration on or off."),
        include_subtitles: z
          .boolean()
          .describe("User's choice: burned-in subtitles on or off."),
        tts_voice: z.string().min(1).max(64).optional().describe("Narrator voice the user picked."),
        language: z.string().min(2).max(16).optional(),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ job_id, tts_voice, language, include_audio, include_subtitles }) => {
      try {
        await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}/settings`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              tts_voice,
              language,
              include_audio,
              include_subtitles,
            }),
          },
        );
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = storyboardStop(await jobPayload(origin, job));
        return ok(
          payload,
          UI.jobProgress,
          "Production options saved. Show the storyboard, wait for them to approve the plan, then write Manim. Do not invent a different voice or subtitle setting.",
          undefined,
          jobDigest(payload),
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "get_scene",
    {
      title: "Get scene details",
      description:
        "Load one scene: narration, Manim code, preview image, clip URL, and VLM notes so you can show it or edit it.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: SCENE_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ job_id, scene_id }) => {
      try {
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = await jobPayload(origin, job);
        const scene = payload.scenes.find((item) => item.id === scene_id);
        if (!scene) return fail(new Error(`Scene ${scene_id} not found.`));
        const art = (
          Array.isArray(job.scenes) ? (job.scenes as Array<Record<string, unknown>>) : []
        ).find((item) => String(item.scene_id) === scene_id);
        const code = typeof art?.code_final === "string" ? art.code_final : "";
        const reviews = Array.isArray(art?.vlm_reviews)
          ? (art.vlm_reviews as Array<Record<string, unknown>>)
          : [];
        const last = reviews.length ? reviews[reviews.length - 1] : null;
        const framePath = typeof last?.frame_url === "string" ? last.frame_url : null;
        const images = await embedImages(origin, [framePath]);
        const detail = {
          job_id,
          ...scene,
          code: code || null,
          vlm_reviews: reviews.map((review) => ({
            approved: review.approved,
            issues: review.issues,
            clarity_score: review.clarity_score,
            frame_url: review.frame_url,
          })),
        };
        return ok(
          detail,
          UI.jobProgress,
          code
            ? "Scene details plus Manim. The user can change narration with update_scene or the code with submit_scene_code / retouch_scene."
            : "Scene details. No Manim yet — wait for storyboard approval before writing code.",
          images,
          // Only the newest review informs the next edit; earlier ones are history.
          { ...detail, vlm_reviews: detail.vlm_reviews.slice(-1) },
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "retouch_scene",
    {
      title: "Retouch a rendered scene",
      description:
        "After a scene has code (and usually a clip), apply the user's change request: rewrite Manim and re-render that scene. Use this instead of starting a new job.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1),
        comment: z
          .string()
          .min(2)
          .max(2000)
          .describe("What the user wants changed in this scene."),
      }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
    },
    async ({ job_id, scene_id, comment }) => {
      try {
        await startSse(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}/scenes/${encodeURIComponent(scene_id)}/retouch/stream`,
          JSON.stringify({ comment }),
          { "Content-Type": "application/json" },
          { untilType: ["complete", "error"], timeoutMs: 90_000 },
        );
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        return jobResult(
          origin,
          job,
          `Retouched ${scene_id}. Show the new preview image and ask if they want more changes.`,
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "get_job",
    {
      title: "Get video job",
      description:
        "Poll one job. If poll_again is true, wait poll_after_seconds and call again with the SAME job_id. If awaiting_user, show the storyboard and wait — do not render. If video_url is set, play it. Never start a new job because a poll is still running.",
      inputSchema: z.object({ job_id: z.string().min(4) }),
      _meta: widgetMeta(UI.jobProgress),
      outputSchema: JOB_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ job_id }) => {
      try {
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = await jobPayload(origin, job);
        const note = payload.has_final_video
          ? "Video is ready. Show video_url and the preview images."
          : payload.error || payload.status === "error"
            ? `Render failed: ${payload.error || "unknown error"}. Fix scene code if needed, then call render_video once. Do not retry unchanged.`
            : payload.awaiting_user
              ? "STOP. Show the storyboard to the user and wait. They can change scenes with update_scene or edit_storyboard."
              : payload.awaiting_render
                ? "All scene code is saved. Call render_video with user_confirmed true."
                : payload.poll_again
                  ? `Still rendering. Wait ${payload.poll_after_seconds} seconds, then call get_job again with job_id ${payload.job_id}.`
                  : payload.message;
        return jobResult(origin, job, note);
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "list_jobs",
    {
      title: "List videos",
      description: "List recent Now I Get It video jobs created through this connector.",
      inputSchema: z.object({
        limit: z.number().int().min(1).max(50).optional(),
      }),
      outputSchema: JOB_LIST_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ limit }) => {
      try {
        const data = await apiJson<{ jobs: Array<Record<string, unknown>> }>(
          origin,
          `/api/jobs?limit=${limit ?? 20}`,
        );
        const jobs = (data.jobs || []).map((job) => ({
          job_id: job.job_id,
          title: job.title,
          status: job.status,
          has_final_video: job.has_final_video,
          created_at: job.created_at,
        }));
        return ok({ jobs });
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "upload_document",
    {
      title: "Upload document for slide study",
      description:
        "Convert a PDF/PPTX/DOCX (or similar) into interactive study slides. Pass file_url (public HTTPS) or file_base64+filename. If the user already uploaded on the website, use list_documents instead. Conversion continues in the background — poll get_document.",
      inputSchema: z.object({
        file_url: z.string().url().optional(),
        file_base64: z.string().optional(),
        filename: z.string().optional(),
      }),
      _meta: widgetMeta(UI.slidesTutor),
      outputSchema: DOCUMENT_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ file_url, file_base64, filename }) => {
      try {
        let bytes: Uint8Array;
        let name = filename || "document.pdf";
        if (file_url) {
          const res = await fetch(file_url, { cache: "no-store" });
          if (!res.ok) throw new Error(`Could not download file (${res.status}).`);
          const buf = new Uint8Array(await res.arrayBuffer());
          bytes = buf;
          const urlName = new URL(file_url).pathname.split("/").pop();
          if (!filename && urlName) name = urlName;
        } else if (file_base64) {
          bytes = Buffer.from(file_base64, "base64");
        } else {
          return fail(
            new Error(
              "Provide file_url or file_base64. ChatGPT/Claude file pickers are limited — a public URL works best.",
            ),
          );
        }
        if (bytes.byteLength > MAX_UPLOAD_BYTES) {
          return fail(new Error("File is larger than 25 MB. Upload it on the website instead."));
        }
        const form = new FormData();
        const copy = new Uint8Array(bytes.byteLength);
        copy.set(bytes);
        form.append("file", new Blob([copy]), name);
        const started = await startSse(origin, "/api/documents/upload/stream", form, {}, {
          untilType: ["status", "slide_ready", "complete", "error"],
          timeoutMs: 25_000,
        });
        const docId = started.docId;
        if (!docId) return fail(new Error("Upload started but no doc_id was returned."));
        const detail = await apiJson<{
          doc_id: string;
          manifest: Parameters<typeof documentPayload>[1]["manifest"];
        }>(origin, `/api/documents/${encodeURIComponent(docId)}`);
        return documentResult(
          origin,
          detail,
          undefined,
          undefined,
          (detail.manifest.status || "ready") === "ready"
            ? "Document is ready. Use ask_document to explain, quiz, or deepen a slide/block. Show any figure images."
            : "Conversion is still running. Poll get_document until status is ready.",
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "list_documents",
    {
      title: "List study documents",
      description: "List converted documents available to this connector.",
      inputSchema: z.object({
        limit: z.number().int().min(1).max(50).optional(),
      }),
      outputSchema: DOCUMENT_LIST_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ limit }) => {
      try {
        const data = await apiJson<{ documents: Array<Record<string, unknown>> }>(
          origin,
          `/api/documents?limit=${limit ?? 20}`,
        );
        return ok({
          documents: (data.documents || []).map((doc) => ({
            doc_id: doc.doc_id,
            title: doc.title,
            source_filename: doc.source_filename,
            status: doc.status,
            slide_count: doc.slide_count,
            created_at: doc.created_at,
          })),
        });
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "get_document",
    {
      title: "Get study document",
      description:
        "Load slide titles, block ids, and signed slide HTML URLs (not full HTML). Use this to poll an in-progress upload.",
      inputSchema: z.object({
        doc_id: z.string().min(4),
        slide_id: z.string().optional(),
      }),
      _meta: widgetMeta(UI.slidesTutor),
      outputSchema: DOCUMENT_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ doc_id, slide_id }) => {
      try {
        const detail = await apiJson<{
          doc_id: string;
          manifest: Parameters<typeof documentPayload>[1]["manifest"];
        }>(origin, `/api/documents/${encodeURIComponent(doc_id)}`);
        return documentResult(origin, detail, slide_id);
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "ask_document",
    {
      title: "Study a slide or block",
      description:
        "Run a Now I Get It study action on a slide or selected block: explain, quiz, simplify, deepen, translate, formulas, misconceptions, turn_into_video_prompt, or freeform follow-up.",
      inputSchema: z.object({
        doc_id: z.string().min(4),
        slide_id: z.string().min(1),
        block_id: z.string().optional(),
        action: z.enum(ASK_ACTIONS).optional(),
        message: z.string().max(4000).optional(),
        language: z.string().max(16).optional(),
        scope: z.enum(["slide", "document"]).optional(),
        conversation: z
          .array(
            z.object({
              role: z.enum(["user", "assistant"]),
              content: z.string().min(1).max(20000),
            }),
          )
          .max(12)
          .optional(),
      }),
      _meta: widgetMeta(UI.slidesTutor),
      outputSchema: DOCUMENT_OUTPUT,
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
    },
    async ({
      doc_id,
      slide_id,
      block_id,
      action,
      message,
      language,
      scope,
      conversation,
    }) => {
      try {
        const result = await apiJson<Record<string, unknown>>(
          origin,
          `/api/documents/${encodeURIComponent(doc_id)}/ask`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: action ?? "explain",
              slide_id,
              block_id: block_id || null,
              message: message || "",
              language: language || "en",
              scope: scope || "slide",
              conversation: conversation || [],
            }),
          },
        );
        const detail = await apiJson<{
          doc_id: string;
          manifest: Parameters<typeof documentPayload>[1]["manifest"];
        }>(origin, `/api/documents/${encodeURIComponent(doc_id)}`);
        return documentResult(
          origin,
          detail,
          slide_id,
          {
            action: result.action,
            reply: result.reply,
            video_prompt: result.video_prompt || null,
            block_id: result.block_id || block_id || null,
          },
          typeof result.reply === "string" ? String(result.reply) : undefined,
        );
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "get_usage",
    {
      title: "Get usage",
      description: "Show remaining generation/token/storage quota for this connector identity.",
      outputSchema: USAGE_OUTPUT,
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () => {
      try {
        const me = await apiJson<{
          usage: Record<string, unknown> | null;
          supabase_configured: boolean;
          storage_mode?: string;
        }>(origin, "/api/me");
        const local = me.storage_mode === "local";
        const mongo = me.storage_mode === "mongo";
        return ok({
          usage: me.usage,
          storage_mode: me.storage_mode || "local",
          supabase_configured: me.supabase_configured,
          note: mongo
            ? "Library and usage are in MongoDB Atlas. Video files stay on disk. Monthly quotas are off."
            : local || !me.supabase_configured
              ? "Jobs are saved in SQLite plus files on the server disk. Monthly quotas are off."
              : "Quota is shared by this connector identity, not by the ChatGPT/Claude account.",
        });
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "search",
    {
      title: "Search library",
      description: "Search this connector's videos and documents by title or prompt.",
      inputSchema: z.object({ query: z.string() }),
      annotations: { readOnlyHint: true, openWorldHint: false },
      outputSchema: SEARCH_OUTPUT,
    },
    async ({ query }) => {
      try {
        const q = query.trim().toLowerCase();
        const [jobs, docs] = await Promise.all([
          apiJson<{ jobs: Array<Record<string, unknown>> }>(origin, "/api/jobs?limit=50"),
          apiJson<{ documents: Array<Record<string, unknown>> }>(
            origin,
            "/api/documents?limit=50",
          ),
        ]);
        const results: Array<{ id: string; title: string; url: string }> = [];
        for (const job of jobs.jobs || []) {
          const title = String(job.title || job.prompt || job.job_id || "");
          const hay = `${title} ${job.prompt || ""}`.toLowerCase();
          if (!q || hay.includes(q)) {
            results.push({
              id: `job:${job.job_id}`,
              title: title || String(job.job_id),
              url: `${origin}/library`,
            });
          }
        }
        for (const doc of docs.documents || []) {
          const title = String(doc.title || doc.source_filename || doc.doc_id || "");
          if (!q || title.toLowerCase().includes(q)) {
            results.push({
              id: `doc:${doc.doc_id}`,
              title,
              url: `${origin}/understand`,
            });
          }
        }
        return {
          structuredContent: { results: results.slice(0, 20) },
          content: [
            {
              type: "text" as const,
              text: JSON.stringify({ results: results.slice(0, 20) }),
            },
          ],
        };
      } catch (err) {
        return fail(err);
      }
    },
  );

  server.registerTool(
    "fetch",
    {
      title: "Fetch library item",
      description: "Fetch a search result by id (job:<id> or doc:<id>).",
      inputSchema: z.object({ id: z.string() }),
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async ({ id }) => {
      try {
        if (id.startsWith("job:")) {
          const jobId = id.slice(4);
          const job = await apiJson<Record<string, unknown>>(
            origin,
            `/api/jobs/${encodeURIComponent(jobId)}`,
          );
          const payload = await jobPayload(origin, job);
          return {
            structuredContent: payload,
            content: [{ type: "text" as const, text: JSON.stringify(payload) }],
          };
        }
        const docId = id.startsWith("doc:") ? id.slice(4) : id;
        const detail = await apiJson<{
          doc_id: string;
          manifest: Parameters<typeof documentPayload>[1]["manifest"];
        }>(origin, `/api/documents/${encodeURIComponent(docId)}`);
        const payload = await documentPayload(origin, detail);
        return {
          structuredContent: payload,
          content: [{ type: "text" as const, text: JSON.stringify(payload) }],
        };
      } catch (err) {
        return fail(err);
      }
    },
  );
}
