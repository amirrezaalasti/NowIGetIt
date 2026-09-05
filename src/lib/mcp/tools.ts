import type { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { UI, widgetMeta } from "./config";
import { ApiError, apiJson, signedMediaUrl, startSse } from "./fastapi";
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

function ok(
  data: Record<string, unknown>,
  widgetUri?: string,
  textExtra?: string,
) {
  const text = textExtra ? `${textExtra}\n\n${JSON.stringify(data)}` : JSON.stringify(data);
  return {
    structuredContent: data,
    content: [{ type: "text" as const, text }],
    _meta: widgetUri ? widgetMeta(widgetUri) : undefined,
  };
}

function sceneSummaries(plan: Record<string, unknown> | null | undefined) {
  const scenes = Array.isArray(plan?.scenes) ? (plan.scenes as Record<string, unknown>[]) : [];
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
    return {
      id: String(scene.id || scene.scene_id || `scene_${i + 1}`),
      title: String(scene.title || `Scene ${i + 1}`),
      duration_seconds: Number(scene.duration_seconds) || null,
      visual_description: typeof scene.visual_description === "string" ? scene.visual_description : "",
      narration,
      beats,
    };
  });
}

function storyboardStop(payload: Record<string, unknown>) {
  const scenes = Array.isArray(payload.scenes) ? payload.scenes : [];
  return {
    ...payload,
    next_step: "present_storyboard_to_user",
    poll_again: false,
    awaiting_user: true,
    do_not_call: [
      "render_video",
      "continue_video",
      "video_codegen_spec",
      "submit_scene_code",
      "list_jobs",
    ],
    user_facing_storyboard: scenes,
  };
}

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
  let message: string;
  let next_step: string;
  if (failed) {
    message =
      `Render failed: ${error || "unknown error"}. If this is a Manim error, fix that scene with submit_scene_code, then call render_video once. Do not retry the same call unchanged.`;
    next_step = "fix_and_rerender";
  } else if (awaiting) {
    message =
      "STOP. Show the numbered storyboard to the user (title + narration per scene) and wait for approval or edit requests. Do not render or write Manim yet.";
    next_step = "present_storyboard_to_user";
  } else if (awaitingRender) {
    message =
      "All scene code is saved. Call render_video with user_confirmed true, then poll get_job if poll_again is true.";
    next_step = "call_render_video";
  } else if (done) {
    message = "Video is ready. Show video_url to the user.";
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
    scenes: sceneSummaries(plan),
    video_url: video_url || null,
    library_url: `${origin}/library`,
    has_final_video: Boolean(runtime.has_final_video || video_url),
  };
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
        { id: string; slide_id: string; type?: string; text?: string }
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
      blocks: (slide.block_ids || []).map((id) => ({
        id,
        type: blocks[id]?.type || "other",
        text: (blocks[id]?.text || "").slice(0, 400),
      })),
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
        "Save YOUR ScenePlan. `plan` is a required JSON object argument (title, concept_summary, scenes[] with beats). Do not put JSON inside prompt. After this tool returns, STOP and show the storyboard to the user. Wait for them to approve or request edits. Do not call render_video yet.",
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
            tts_voice: "alloy",
            include_audio: true,
            include_subtitles: true,
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
          "STOP AND SHOW THE USER THIS STORYBOARD. Numbered scenes with titles and narration. Ask if they want changes. Do not render, do not write Manim, do not list_jobs until they reply.",
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
        "Only after the user approved the storyboard in chat. Returns Manim rules for one scene. You write Python, then submit_scene_code. Text() only — never MathTex.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        scene_id: z.string().min(1).describe("e.g. scene_1"),
      }),
    },
    async ({ job_id, scene_id }) => {
      try {
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
        "Save Manim for one scene after the user approved the storyboard. Repeat until every scene has code, then render_video with user_confirmed true.",
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
    },
    async ({ job_id, scene_id, code }) => {
      try {
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
        return ok(
          { ...payload, ...saved },
          UI.jobProgress,
          ready
            ? "All scenes have code. Call render_video with user_confirmed true, then keep polling get_job if poll_again is true."
            : `Saved ${scene_id}. Still missing: ${JSON.stringify(saved.scenes_missing_code)}.`,
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
    const widget = waited.payload.has_final_video ? UI.videoPlayer : UI.jobProgress;
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
      return ok(waited.payload, widget, "Video is ready. Play video_url for the user.");
    }
    if (waited.payload.poll_again) {
      return ok(
        { ...waited.payload, poll_again: true, poll_after_seconds: 8 },
        widget,
        "Still rendering. Wait 8 seconds, then call get_job with this same job_id. Do not start a new job.",
      );
    }
    if (waited.payload.status === "awaiting_render") {
      return ok(
        waited.payload,
        widget,
        "Code is saved but render has not started. Call render_video with user_confirmed true.",
      );
    }
    return ok(waited.payload, widget);
  }

  server.registerTool(
    "render_video",
    {
      title: "Render video",
      description:
        "Render ONLY after (1) the user approved the storyboard in chat and (2) every scene has submit_scene_code. You MUST pass user_confirmed=true. This waits on the worker; if poll_again, keep calling get_job.",
      inputSchema: z.object({
        job_id: z.string().min(4),
        user_confirmed: z
          .boolean()
          .describe("Must be true. Confirms the user already approved the storyboard in chat."),
      }),
      _meta: widgetMeta(UI.jobProgress),
    },
    async ({ job_id, user_confirmed }) => {
      try {
        if (user_confirmed !== true) {
          return fail(
            new Error(
              "user_confirmed must be true. First show the storyboard, wait for the user to approve, submit Manim for every scene, then call render_video again.",
            ),
          );
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
    },
    async ({ job_id, user_confirmed }) => {
      try {
        if (user_confirmed !== true) {
          return fail(
            new Error(
              "The user has not confirmed. Show the storyboard and wait. Then submit_scene_code for every scene, then render_video with user_confirmed true.",
            ),
          );
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
        return ok(
          storyboardStop(await jobPayload(origin, job)),
          UI.jobProgress,
          "STOP. Show the updated storyboard to the user and wait for approval. Do not render yet.",
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
    },
    async ({ job_id }) => {
      try {
        const job = await apiJson<Record<string, unknown>>(
          origin,
          `/api/jobs/${encodeURIComponent(job_id)}`,
        );
        const payload = await jobPayload(origin, job);
        const note = payload.has_final_video
          ? "Video is ready. Play video_url."
          : payload.error || payload.status === "error"
            ? `Render failed: ${payload.error || "unknown error"}. Fix scene code if needed, then call render_video once. Do not retry unchanged.`
            : payload.awaiting_user
              ? "STOP. Show the storyboard to the user and wait. Do not render."
              : payload.awaiting_render
                ? "All scene code is saved. Call render_video with user_confirmed true."
                : payload.poll_again
                  ? `Still rendering. Wait ${payload.poll_after_seconds} seconds, then call get_job again with job_id ${payload.job_id}.`
                  : payload.message;
        return ok(
          payload,
          payload.has_final_video ? UI.videoPlayer : UI.jobProgress,
          note,
        );
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
        const payload = await documentPayload(origin, detail);
        return ok(
          payload,
          UI.slidesTutor,
          payload.status === "ready"
            ? "Document is ready. Use ask_document to explain, quiz, or deepen a slide/block."
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
    },
    async ({ doc_id, slide_id }) => {
      try {
        const detail = await apiJson<{
          doc_id: string;
          manifest: Parameters<typeof documentPayload>[1]["manifest"];
        }>(origin, `/api/documents/${encodeURIComponent(doc_id)}`);
        return ok(await documentPayload(origin, detail, slide_id), UI.slidesTutor);
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
        const doc = await documentPayload(origin, detail, slide_id);
        return ok(
          {
            ...doc,
            action: result.action,
            reply: result.reply,
            video_prompt: result.video_prompt || null,
            block_id: result.block_id || block_id || null,
          },
          UI.slidesTutor,
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
