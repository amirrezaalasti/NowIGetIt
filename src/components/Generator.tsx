"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { AuthMedia } from "@/components/AuthMedia";
import { SegmentedControl } from "@/components/SegmentedControl";
import {
  ensureApiToken,
  fetchHealth,
  streamContinue,
  streamGenerate,
  streamRegenerateScene,
  updateJobPlan,
  type Audience,
  type LengthPreset,
  type PipelineEvent,
  type ScenePlanDraft,
  type SceneSectionDraft,
} from "@/lib/api";

function AutoTextarea({
  value,
  onChange,
  placeholder,
  className,
  minRows = 2,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  minRows?: number;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(el.scrollHeight, minRows * 22)}px`;
  }, [value, minRows]);
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={minRows}
      className={`block w-full resize-none overflow-hidden bg-transparent outline-none ${className || ""}`}
    />
  );
}

type ScenePreview = {
  id: string;
  title: string;
  narration?: string;
  visualDescription?: string;
  beats?: string[];
  visualDevice?: string;
  duration?: number;
  approved?: boolean;
  clarity?: number;
  frameUrl?: string;
  videoUrl?: string;
  status?: string;
};

type FlowMode = "compose" | "storyboard" | "building" | "result";

const EXAMPLES = [
  "Explain gradient descent on a simple parabola",
  "Show why the Pythagorean theorem works visually",
  "Animate how sine and cosine relate on the unit circle",
];

const LENGTH_OPTIONS: { id: LengthPreset; label: string; hint: string }[] = [
  { id: "short", label: "60s", hint: "Quick intuition" },
  { id: "standard", label: "90s", hint: "Balanced" },
  { id: "deep", label: "3 min", hint: "Deep dive" },
];

const AUDIENCE_OPTIONS: { id: Audience; label: string }[] = [
  { id: "general", label: "General" },
  { id: "hs", label: "High school" },
  { id: "undergrad", label: "Undergrad" },
];

function planFromEvent(data: Record<string, unknown>): ScenePlanDraft {
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
      style_tags: Array.isArray(s.style_tags)
        ? (s.style_tags as string[])
        : [],
    })),
  };
}

function scenesFromPlan(plan: ScenePlanDraft): ScenePreview[] {
  return plan.scenes.map((s) => ({
    id: s.id,
    title: s.title,
    narration: s.narration,
    visualDescription: s.visual_description,
    beats: s.animation_beats,
    visualDevice: s.visual_device,
    duration: s.duration_seconds,
    status: "queued",
  }));
}

function sceneStatusTone(status?: string, approved?: boolean) {
  if (approved === false || status === "needs work" || status === "render failed") {
    return "text-[var(--accent-hot)]";
  }
  if (approved === true || status === "done" || status === "approved") {
    return "text-[var(--accent)]";
  }
  return "text-[var(--ink-muted)]";
}

export function Generator() {
  const { status: authStatus } = useSession();
  const [prompt, setPrompt] = useState("");
  const [lengthPreset, setLengthPreset] = useState<LengthPreset>("standard");
  const [audience, setAudience] = useState<Audience>("general");
  const [running, setRunning] = useState(false);
  const [awaitingPlan, setAwaitingPlan] = useState(false);
  const [editingPlan, setEditingPlan] = useState<ScenePlanDraft | null>(null);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [planTitle, setPlanTitle] = useState<string | null>(null);
  const [scenes, setScenes] = useState<ScenePreview[]>([]);
  const [finalNotes, setFinalNotes] = useState<string | null>(null);
  const [finalVideoUrl, setFinalVideoUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<string>("Checking API…");
  const [liveMessage, setLiveMessage] = useState<string>("");
  const [regenDirection, setRegenDirection] = useState<Record<string, string>>(
    {},
  );
  const [promptFocused, setPromptFocused] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const logContainerRef = useRef<HTMLDivElement | null>(null);
  const signedIn = authStatus === "authenticated";

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        const manim = h.manim_available
          ? ` · Manim ${h.manim_version || "ok"}`
          : "";
        const short = (id?: string) =>
          id?.includes("/") ? id.split("/").pop() : id;
        const worker =
          h.render_worker_configured && h.render_worker_ok === false
            ? " · worker URL invalid (using local)"
            : h.render_worker_ok
              ? " · remote worker"
              : "";
        setHealth(
          h.openrouter_configured
            ? `Ready · ${short(h.model) || "llm"} · VLM ${short(h.vlm_model) || "flash-lite"}${manim}${worker}`
            : "API up · set OPENROUTER_API_KEY",
        );
      })
      .catch(() => setHealth("API offline — start FastAPI on :8000"));
  }, []);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events, logOpen]);

  const hasSceneOutput = scenes.some(
    (s) => s.videoUrl || s.frameUrl || s.status === "done",
  );
  const completed = events.some((e) => e.type === "complete") || Boolean(finalVideoUrl);

  const mode: FlowMode = useMemo(() => {
    if (awaitingPlan && editingPlan) return "storyboard";
    if (finalVideoUrl || (completed && hasSceneOutput && !awaitingPlan)) {
      return "result";
    }
    if (running || (scenes.length > 0 && !awaitingPlan && !completed)) {
      return "building";
    }
    return "compose";
  }, [
    awaitingPlan,
    editingPlan,
    finalVideoUrl,
    completed,
    hasSceneOutput,
    running,
    scenes.length,
  ]);

  const doneCount = scenes.filter((s) => s.status === "done").length;
  const showExamples = promptFocused || !prompt.trim();

  function applyPipelineEvent(event: PipelineEvent) {
    setEvents((prev) => [...prev, event]);
    setLiveMessage(event.message);
    if (event.data?.job_id && typeof event.data.job_id === "string") {
      setJobId(event.data.job_id);
    }
    if (
      (event.type === "plan" || event.type === "plan_ready") &&
      event.data
    ) {
      const plan = planFromEvent(event.data as Record<string, unknown>);
      setPlanTitle(plan.title);
      setEditingPlan(plan);
      setScenes(scenesFromPlan(plan));
      if (event.type === "plan_ready" || event.data.awaiting_confirm) {
        setAwaitingPlan(true);
        setRunning(false);
      }
    }
    if (event.type === "scene_start" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id ? { ...s, status: "building" } : s,
        ),
      );
    }
    if (event.type === "scene_tts" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                status: "narrating",
                duration:
                  typeof event.data?.target_duration === "number"
                    ? event.data.target_duration
                    : s.duration,
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_render" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                status: event.data?.ok ? "rendered" : "render failed",
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_vlm" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                approved: Boolean(event.data?.approved),
                clarity:
                  typeof event.data?.clarity_score === "number"
                    ? event.data.clarity_score
                    : s.clarity,
                status: event.data?.approved ? "approved" : "needs work",
                frameUrl:
                  typeof event.data?.frame_url === "string"
                    ? event.data.frame_url
                    : s.frameUrl,
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_done" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                status: "done",
                approved: Boolean(event.data?.vlm_approved),
                clarity:
                  typeof event.data?.clarity_score === "number"
                    ? event.data.clarity_score
                    : s.clarity,
                videoUrl:
                  typeof event.data?.video_url === "string"
                    ? event.data.video_url
                    : s.videoUrl,
                frameUrl:
                  typeof event.data?.frame_url === "string"
                    ? event.data.frame_url
                    : s.frameUrl,
              }
            : s,
        ),
      );
    }
    if (event.type === "final_debug" && event.data) {
      setFinalNotes(String(event.data.notes || ""));
    }
    if (event.type === "complete" && event.data) {
      if (typeof event.data.final_video_url === "string") {
        setFinalVideoUrl(event.data.final_video_url);
      }
      const completedScenes = event.data.scenes as
        | Array<Record<string, unknown>>
        | undefined;
      if (completedScenes?.length) {
        setScenes((prev) =>
          prev.map((s) => {
            const match = completedScenes.find(
              (c) => c.scene_id === s.id || c.id === s.id,
            );
            if (!match) return s;
            return {
              ...s,
              status: "done",
              approved: Boolean(match.vlm_approved),
              videoUrl:
                typeof match.video_url === "string"
                  ? match.video_url
                  : s.videoUrl,
              frameUrl:
                typeof match.frame_url === "string"
                  ? match.frame_url
                  : s.frameUrl,
            };
          }),
        );
      }
      if (
        typeof event.data.scene_id === "string" &&
        typeof event.data.video_url === "string"
      ) {
        setScenes((prev) =>
          prev.map((s) =>
            s.id === event.data?.scene_id
              ? {
                  ...s,
                  status: "done",
                  videoUrl: event.data?.video_url as string,
                  frameUrl:
                    typeof event.data?.frame_url === "string"
                      ? event.data.frame_url
                      : s.frameUrl,
                  approved:
                    event.data?.vlm_approved !== undefined
                      ? Boolean(event.data.vlm_approved)
                      : s.approved,
                }
              : s,
          ),
        );
        if (typeof event.data.final_video_url === "string") {
          setFinalVideoUrl(event.data.final_video_url);
        }
      }
    }
    if (event.type === "error") {
      setError(event.message);
    }
  }

  function resetToCompose() {
    abortRef.current?.abort();
    setRunning(false);
    setAwaitingPlan(false);
    setEditingPlan(null);
    setEvents([]);
    setPlanTitle(null);
    setScenes([]);
    setFinalNotes(null);
    setFinalVideoUrl(null);
    setJobId(null);
    setError(null);
    setLiveMessage("");
    setRegenDirection({});
    setLogOpen(false);
  }

  async function onGenerate() {
    if (!prompt.trim() || running) return;
    if (!signedIn) {
      window.location.href = "/login";
      return;
    }
    setRunning(true);
    setAwaitingPlan(false);
    setEditingPlan(null);
    setError(null);
    setEvents([]);
    setPlanTitle(null);
    setScenes([]);
    setFinalNotes(null);
    setFinalVideoUrl(null);
    setJobId(null);
    setLiveMessage("Planning storyboard…");
    setLogOpen(false);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await ensureApiToken();
      await streamGenerate(
        {
          prompt: prompt.trim(),
          length_preset: lengthPreset,
          audience,
          plan_only: true,
          skip_render: false,
        },
        applyPipelineEvent,
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setRunning(false);
    }
  }

  function updateSceneField(
    sceneId: string,
    patch: Partial<SceneSectionDraft>,
  ) {
    setEditingPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        scenes: prev.scenes.map((s) =>
          s.id === sceneId ? { ...s, ...patch } : s,
        ),
      };
    });
    setScenes((prev) =>
      prev.map((s) => {
        if (s.id !== sceneId) return s;
        return {
          ...s,
          title: patch.title ?? s.title,
          narration: patch.narration ?? s.narration,
          visualDescription:
            patch.visual_description ?? s.visualDescription,
          beats: patch.animation_beats ?? s.beats,
          visualDevice: patch.visual_device ?? s.visualDevice,
          duration: patch.duration_seconds ?? s.duration,
        };
      }),
    );
  }

  async function onConfirmPlan() {
    if (!jobId || !editingPlan || running) return;
    setRunning(true);
    setAwaitingPlan(false);
    setError(null);
    setLiveMessage("Saving storyboard…");
    setLogOpen(false);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await ensureApiToken();
      await updateJobPlan(jobId, editingPlan);
      setScenes((prev) => prev.map((s) => ({ ...s, status: "queued" })));
      setLiveMessage("Building scenes…");
      await streamContinue(jobId, applyPipelineEvent, controller.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setAwaitingPlan(true);
      }
    } finally {
      setRunning(false);
    }
  }

  async function onRegenerateScene(sceneId: string) {
    if (!jobId || running) return;
    setRunning(true);
    setError(null);
    setLiveMessage(`Regenerating ${sceneId}…`);
    setScenes((prev) =>
      prev.map((s) =>
        s.id === sceneId ? { ...s, status: "regenerating" } : s,
      ),
    );
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const section = editingPlan?.scenes.find((s) => s.id === sceneId);
    try {
      await ensureApiToken();
      await streamRegenerateScene(jobId, sceneId, applyPipelineEvent, {
        direction: regenDirection[sceneId] || "more visual, clearer beats",
        section,
        signal: controller.signal,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setRunning(false);
    }
  }

  if (authStatus === "loading") {
    return (
      <section className="relative mx-auto w-full max-w-3xl px-6 py-16">
        <p className="text-sm text-[var(--ink-muted)]">Checking session…</p>
      </section>
    );
  }

  if (!signedIn) {
    return (
      <section className="relative mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 py-16 text-center">
        <p className="font-[family-name:var(--font-display)] text-4xl tracking-tight text-[var(--ink)] sm:text-5xl">
          NowIGetIt
        </p>
        <h1 className="mt-4 text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
          Prompt in. Scene plan, visual QA, voice — until the idea clicks.
        </h1>
        <p className="mx-auto mt-6 max-w-md text-sm text-[var(--ink-muted)]">
          Sign in to plan storyboards, generate videos, and keep every revision
          private to your account.
        </p>
        <Link
          href="/login"
          className="mt-10 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
        >
          Continue with Google
        </Link>
      </section>
    );
  }

  return (
    <>
      <section
        className={`relative mx-auto w-full max-w-3xl px-6 pt-8 sm:pt-10 ${
          mode === "storyboard" ? "pb-32" : "pb-16"
        }`}
      >
        {mode === "compose" && (
          <div className="animate-rise">
            <p className="font-[family-name:var(--font-display)] text-4xl tracking-tight text-[var(--ink)] sm:text-5xl">
              NowIGetIt
            </p>
            <h1 className="mt-3 max-w-xl text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
              Prompt in. Scene plan, visual QA, voice — until the idea clicks.
            </h1>

            <label className="sr-only" htmlFor="prompt">
              Prompt
            </label>
            <textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onFocus={() => setPromptFocused(true)}
              onBlur={() => setPromptFocused(false)}
              rows={4}
              placeholder="What should click? Describe the concept you want animated…"
              className="mt-10 w-full resize-none rounded-2xl border border-[var(--line)] bg-[var(--surface)] px-5 py-4 text-lg leading-relaxed text-[var(--ink)] outline-none transition focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_var(--glow)] placeholder:text-[var(--ink-muted)]"
              disabled={running}
            />

            <div className="mt-5 flex flex-wrap items-end gap-5">
              <SegmentedControl
                label="Length"
                value={lengthPreset}
                options={LENGTH_OPTIONS}
                onChange={setLengthPreset}
                disabled={running}
              />
              <SegmentedControl
                label="Audience"
                value={audience}
                options={AUDIENCE_OPTIONS}
                onChange={setAudience}
                disabled={running}
              />
            </div>

            {showExamples && (
              <div className="mt-5 animate-rise">
                <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Try an example
                </p>
                <ul className="space-y-1.5">
                  {EXAMPLES.map((example) => (
                    <li key={example}>
                      <button
                        type="button"
                        onClick={() => setPrompt(example)}
                        className="text-left text-sm text-[var(--ink-muted)] transition hover:text-[var(--ink)]"
                      >
                        {example}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-8 flex flex-wrap items-center gap-4">
              <button
                type="button"
                disabled={running || !prompt.trim()}
                onClick={onGenerate}
                className="rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Plan storyboard
              </button>
            </div>

            <details className="mt-10 group">
              <summary className="cursor-pointer list-none text-xs text-[var(--ink-muted)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                <span className="border-b border-transparent group-open:border-[var(--line)]">
                  System status
                </span>
              </summary>
              <p className="mt-2 font-mono text-xs leading-relaxed text-[var(--ink-muted)]">
                {health}
              </p>
            </details>
          </div>
        )}

        {mode === "storyboard" && editingPlan && (
          <div className="animate-rise">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Step 2 · Storyboard
                </p>
                <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
                  Edit the plan
                </h2>
                <p className="mt-2 max-w-xl text-sm text-[var(--ink-muted)]">
                  Tweak narration and visuals, then confirm to render.
                  {editingPlan.visual_identity
                    ? ` ${editingPlan.visual_identity}`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={resetToCompose}
                className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
              >
                Start over
              </button>
            </div>

            <input
              value={editingPlan.title}
              onChange={(e) => {
                setEditingPlan({ ...editingPlan, title: e.target.value });
                setPlanTitle(e.target.value);
              }}
              className="mt-8 w-full border-b border-[var(--line)] bg-transparent pb-2 font-[family-name:var(--font-display)] text-2xl text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              placeholder="Video title"
            />

            <ol className="mt-8 space-y-10">
              {editingPlan.scenes.map((scene, i) => (
                <li
                  key={scene.id}
                  className="grid gap-4 sm:grid-cols-[2.5rem_1fr]"
                >
                  <div className="pt-1 font-mono text-sm text-[var(--accent)]">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="min-w-0 space-y-4">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <input
                        value={scene.title}
                        onChange={(e) =>
                          updateSceneField(scene.id, { title: e.target.value })
                        }
                        className="min-w-0 flex-1 bg-transparent text-lg font-medium text-[var(--ink)] outline-none"
                      />
                      {scene.visual_device && (
                        <span className="text-xs uppercase tracking-[0.12em] text-[var(--ink-muted)]">
                          {scene.visual_device.replaceAll("_", " ")}
                        </span>
                      )}
                    </div>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        Narration
                      </span>
                      <AutoTextarea
                        value={scene.narration}
                        onChange={(v) =>
                          updateSceneField(scene.id, { narration: v })
                        }
                        minRows={3}
                        className="mt-1 text-[15px] leading-relaxed text-[var(--ink)]"
                        placeholder="What the voiceover says…"
                      />
                    </label>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        On screen
                      </span>
                      <AutoTextarea
                        value={scene.visual_description}
                        onChange={(v) =>
                          updateSceneField(scene.id, {
                            visual_description: v,
                          })
                        }
                        minRows={2}
                        className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]"
                        placeholder="What appears visually…"
                      />
                    </label>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        Beats
                      </span>
                      <AutoTextarea
                        value={scene.animation_beats.join("\n")}
                        onChange={(v) =>
                          updateSceneField(scene.id, {
                            animation_beats: v
                              .split("\n")
                              .map((b) => b.trim())
                              .filter(Boolean),
                          })
                        }
                        minRows={2}
                        className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]"
                        placeholder="One animation beat per line…"
                      />
                    </label>
                  </div>
                </li>
              ))}
            </ol>

            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={running || !prompt.trim()}
                onClick={onGenerate}
                className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline disabled:opacity-40"
              >
                Re-plan from prompt
              </button>
            </div>
          </div>
        )}

        {(mode === "building" || mode === "result") && (
          <div className="animate-rise">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  {mode === "building"
                    ? scenes.length === 0
                      ? "Step 1 · Planning"
                      : "Step 3 · Building"
                    : "Your video"}
                </p>
                <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
                  {planTitle ||
                    (mode === "building" && scenes.length === 0
                      ? "Planning storyboard"
                      : "Explanation")}
                </h2>
                <p className="mt-2 text-sm text-[var(--ink-muted)]">
                  {mode === "building"
                    ? liveMessage ||
                      (scenes.length === 0
                        ? "Sketching scenes from your prompt…"
                        : "Clips unlock as each scene finishes — you don’t need to wait for the end.")
                    : "Full explanation with narration. Tweak individual scenes below if needed."}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {running && (
                  <button
                    type="button"
                    onClick={() => abortRef.current?.abort()}
                    className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
                  >
                    Cancel
                  </button>
                )}
                <button
                  type="button"
                  onClick={resetToCompose}
                  className="rounded-md border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
                >
                  New explanation
                </button>
              </div>
            </div>

            {mode === "building" && scenes.length > 0 && (
              <div className="mt-6">
                <div className="mb-2 flex justify-between text-xs text-[var(--ink-muted)]">
                  <span>
                    {doneCount} of {scenes.length} scenes ready
                  </span>
                  {running && (
                    <span className="text-[var(--accent)]">Generating…</span>
                  )}
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-strong)]">
                  <div
                    className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
                    style={{
                      width: `${scenes.length ? (doneCount / scenes.length) * 100 : 8}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {mode === "result" && finalVideoUrl && (
              <div className="mt-8">
                <AuthMedia
                  src={finalVideoUrl}
                  className="w-full overflow-hidden rounded-2xl border border-[var(--line)]"
                />
                {jobId && (
                  <p className="mt-3 text-sm text-[var(--ink-muted)]">
                    Saved to your{" "}
                    <Link
                      href="/library"
                      className="text-[var(--accent)] underline-offset-4 hover:underline"
                    >
                      library
                    </Link>
                    .
                  </p>
                )}
              </div>
            )}

            {mode === "result" && running && liveMessage && (
              <p className="mt-4 text-sm text-[var(--accent)]">{liveMessage}</p>
            )}

            <ul className="mt-10 space-y-8">
              {scenes.map((scene, i) => (
                <li key={scene.id} className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <span className="font-mono text-xs text-[var(--accent)]">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="font-medium text-[var(--ink)]">
                      {scene.title}
                    </span>
                    {scene.status && (
                      <span className={sceneStatusTone(scene.status, scene.approved)}>
                        · {scene.status}
                      </span>
                    )}
                    {typeof scene.clarity === "number" && (
                      <span className="text-[var(--ink-muted)]">
                        · clarity {Math.round(scene.clarity * 100)}%
                      </span>
                    )}
                  </div>

                  {mode === "result" && scene.narration && (
                    <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">
                      {scene.narration}
                    </p>
                  )}

                  {scene.videoUrl ? (
                    <AuthMedia
                      src={scene.videoUrl}
                      poster={scene.frameUrl}
                      className="mt-3 w-full overflow-hidden rounded-xl border border-[var(--line)]"
                    />
                  ) : scene.frameUrl ? (
                    <AuthMedia
                      src={scene.frameUrl}
                      kind="image"
                      alt={`${scene.title} preview`}
                      className="mt-3 w-full overflow-hidden rounded-xl border border-[var(--line)]"
                    />
                  ) : scene.status &&
                    scene.status !== "queued" &&
                    scene.status !== "done" ? (
                    <div className="mt-3 flex aspect-video items-center justify-center rounded-xl border border-dashed border-[var(--line)] bg-[var(--surface)] text-sm text-[var(--ink-muted)]">
                      {scene.status}…
                    </div>
                  ) : null}

                  {mode === "result" && jobId && scene.status === "done" && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <input
                        value={regenDirection[scene.id] ?? ""}
                        onChange={(e) =>
                          setRegenDirection((prev) => ({
                            ...prev,
                            [scene.id]: e.target.value,
                          }))
                        }
                        placeholder="e.g. more visual, less text"
                        className="min-w-[12rem] flex-1 border-b border-[var(--line)] bg-transparent px-0 py-1.5 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                        disabled={running}
                      />
                      <button
                        type="button"
                        disabled={running}
                        onClick={() => onRegenerateScene(scene.id)}
                        className="text-sm font-medium text-[var(--accent)] underline-offset-4 hover:underline disabled:opacity-40"
                      >
                        Regenerate scene
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>

            {finalNotes && mode === "result" && (
              <details className="mt-8">
                <summary className="cursor-pointer text-sm text-[var(--ink-muted)] hover:text-[var(--ink)]">
                  Final notes
                </summary>
                <p className="mt-2 text-sm text-[var(--ink)]">{finalNotes}</p>
              </details>
            )}

            {(running || events.length > 0) && (
              <div className="mt-10">
                <button
                  type="button"
                  onClick={() => setLogOpen((v) => !v)}
                  className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
                >
                  {logOpen ? "Hide live log" : "Show live log"}
                  {events.length > 0 ? ` (${events.length})` : ""}
                </button>
                {logOpen && (
                  <div
                    ref={logContainerRef}
                    className="mt-3 max-h-64 overflow-y-auto rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-4 font-mono text-xs leading-relaxed text-[var(--ink-muted)]"
                  >
                    {events.length === 0 && (
                      <div className="opacity-60">Waiting for pipeline events…</div>
                    )}
                    {events.map((event, idx) => (
                      <div key={`${event.type}-${idx}`} className="mb-2">
                        <span className="text-[var(--accent)]">{event.type}</span>
                        {" — "}
                        {event.message}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <details className="mt-8 group">
              <summary className="cursor-pointer list-none text-xs text-[var(--ink-muted)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                System status
              </summary>
              <p className="mt-2 font-mono text-xs leading-relaxed text-[var(--ink-muted)]">
                {health}
                {jobId ? ` · job ${jobId}` : ""}
              </p>
            </details>
          </div>
        )}

        {error && (
          <p className="mt-6 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-ink)]">
            {error}
          </p>
        )}
      </section>

      {mode === "storyboard" && editingPlan && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--line)] bg-[var(--bg-deep)]/90 backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3 px-6 py-4">
            <p className="text-sm text-[var(--ink-muted)]">
              {editingPlan.scenes.length} scenes ready to render
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {running && (
                <button
                  type="button"
                  onClick={() => abortRef.current?.abort()}
                  className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                disabled={running || !editingPlan}
                onClick={onConfirmPlan}
                className="rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110 disabled:opacity-40"
              >
                {running ? "Working…" : "Confirm & generate video"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
