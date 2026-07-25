"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { AuthMedia } from "@/components/AuthMedia";
import { DebugInspector } from "@/components/DebugInspector";
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
        setHealth(
          h.openrouter_configured
            ? `Ready · ${short(h.model) || "llm"} · VLM ${short(h.vlm_model) || "flash-lite"}${manim}`
            : "API up · set OPENROUTER_API_KEY",
        );
      })
      .catch(() => setHealth("API offline — start FastAPI on :8000"));
  }, []);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events]);

  const statusLabel = useMemo(() => {
    if (error) return "Failed";
    if (awaitingPlan) return "Edit storyboard";
    if (!running && events.length === 0) return "Idle";
    const last = events[events.length - 1];
    if (last?.type === "complete") return "Done";
    if (running) return "Generating";
    return "Idle";
  }, [events, running, error, awaitingPlan]);

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
                // Wait for scene_done (muxed + faststart) before attaching video.
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
      const completed = event.data.scenes as
        | Array<Record<string, unknown>>
        | undefined;
      if (completed?.length) {
        setScenes((prev) =>
          prev.map((s) => {
            const match = completed.find(
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
      // Single-scene regenerate complete payload
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
      <section className="relative mx-auto w-full max-w-3xl px-6 pb-16 pt-6">
        <p className="text-sm text-[var(--ink-muted)]">Checking session…</p>
      </section>
    );
  }

  if (!signedIn) {
    return (
      <section className="relative mx-auto w-full max-w-3xl px-6 pb-16 pt-6">
        <div className="animate-rise-delay-2 rounded-2xl border border-[var(--line)] bg-[var(--surface)] px-6 py-10 text-center">
          <h2 className="font-[family-name:var(--font-display)] text-2xl text-[var(--ink)]">
            Sign in to generate
          </h2>
          <p className="mx-auto mt-3 max-w-md text-sm text-[var(--ink-muted)]">
            Google sign-in keeps your scene plans, videos, and revisions private
            to your account.
          </p>
          <Link
            href="/login"
            className="mt-8 inline-flex rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
          >
            Continue with Google
          </Link>
        </div>
      </section>
    );
  }

  return (
    <>
      <section className="relative mx-auto w-full max-w-4xl px-6 pb-16 pt-6">
        <div className="mb-4 flex items-center justify-between text-sm text-[var(--ink-muted)] animate-rise-delay-2">
          <span className="tracking-wide">{health}</span>
          <span className="rounded-full border border-[var(--line)] px-3 py-1 text-xs uppercase tracking-[0.14em]">
            {statusLabel}
          </span>
        </div>

        <label className="sr-only" htmlFor="prompt">
          Prompt
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder="What should click? Describe the concept you want animated…"
          className="w-full resize-none rounded-2xl border border-[var(--line)] bg-[var(--surface)] px-5 py-4 text-lg leading-relaxed text-[var(--ink)] outline-none transition focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_var(--glow)] placeholder:text-[var(--ink-muted)] animate-rise-delay-2"
          disabled={running && !awaitingPlan}
        />

        <div className="mt-4 flex flex-wrap items-center gap-4 animate-rise-delay-2">
          <div className="flex flex-wrap gap-1.5">
            {LENGTH_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setLengthPreset(opt.id)}
                disabled={running}
                title={opt.hint}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  lengthPreset === opt.id
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--ink)]"
                    : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {AUDIENCE_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setAudience(opt.id)}
                disabled={running}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  audience === opt.id
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--ink)]"
                    : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2 animate-rise-delay-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setPrompt(example)}
              className="border-b border-transparent text-left text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent-hot)] hover:text-[var(--ink)]"
            >
              {example}
            </button>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-4 animate-rise-delay-2">
          <button
            type="button"
            disabled={running || !prompt.trim()}
            onClick={onGenerate}
            className="group relative overflow-hidden rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="relative z-10">
              {running && !awaitingPlan
                ? "Working…"
                : awaitingPlan
                  ? "Re-plan storyboard"
                  : "Plan storyboard"}
            </span>
          </button>
          {awaitingPlan && (
            <button
              type="button"
              disabled={running || !editingPlan}
              onClick={onConfirmPlan}
              className="rounded-full border border-[var(--accent)] px-6 py-3 text-base font-semibold text-[var(--accent)] transition hover:bg-[var(--accent)]/10 disabled:opacity-40"
            >
              Confirm & generate video
            </button>
          )}
          {running && (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
            >
              Cancel
            </button>
          )}
          {jobId && (
            <span className="font-mono text-xs text-[var(--ink-muted)]">
              job {jobId}
            </span>
          )}
        </div>

        {(running || awaitingPlan) && liveMessage && (
          <p className="mt-4 text-sm text-[var(--accent)] animate-rise">
            {liveMessage}
          </p>
        )}

        {error && (
          <p className="mt-6 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-ink)]">
            {error}
          </p>
        )}

        {awaitingPlan && editingPlan && (
          <div className="mt-10 animate-rise">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="font-[family-name:var(--font-display)] text-2xl">
                  Storyboard
                </h2>
                <p className="mt-1 max-w-xl text-sm text-[var(--ink-muted)]">
                  Tweak the script, then confirm to render.
                  {editingPlan.visual_identity
                    ? ` ${editingPlan.visual_identity}`
                    : ""}
                </p>
              </div>
              <p className="text-xs text-[var(--ink-muted)]">
                {editingPlan.scenes.length} scenes
              </p>
            </div>

            <input
              value={editingPlan.title}
              onChange={(e) => {
                setEditingPlan({ ...editingPlan, title: e.target.value });
                setPlanTitle(e.target.value);
              }}
              className="mt-6 w-full border-b border-[var(--line)] bg-transparent pb-2 font-[family-name:var(--font-display)] text-2xl text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              placeholder="Video title"
            />

            <ol className="mt-8 space-y-8">
              {editingPlan.scenes.map((scene, i) => (
                <li key={scene.id} className="grid gap-4 sm:grid-cols-[3rem_1fr]">
                  <div className="pt-1 font-mono text-sm text-[var(--accent)]">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="min-w-0 space-y-4 border-t border-[var(--line)] pt-4 sm:border-t-0 sm:pt-0">
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
          </div>
        )}

        {finalVideoUrl && (
          <div className="mt-10">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="font-[family-name:var(--font-display)] text-2xl">
                  Final video
                </h2>
                <p className="mt-1 text-sm text-[var(--ink-muted)]">
                  Full explanation with narration audio attached
                </p>
              </div>
            </div>
            <AuthMedia
              src={finalVideoUrl}
              className="mt-4 w-full overflow-hidden rounded-2xl border border-[var(--line)]"
            />
          </div>
        )}

        {(planTitle || events.length > 0) && !awaitingPlan && (
          <div className="mt-12 grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
            <div>
              <h2 className="font-[family-name:var(--font-display)] text-2xl text-[var(--ink)]">
                {planTitle || "Pipeline"}
              </h2>
              <p className="mt-1 text-sm text-[var(--ink-muted)]">
                Clips unlock as each scene finishes — you don’t need to wait for the end.
              </p>
              <ul className="mt-5 space-y-8">
                {scenes.map((scene, i) => (
                  <li key={scene.id} className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-muted)]">
                      <span className="progress-dot inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                      Scene {i + 1}
                      {scene.visualDevice && (
                        <span>· {scene.visualDevice.replaceAll("_", " ")}</span>
                      )}
                      {scene.status && <span>· {scene.status}</span>}
                      {typeof scene.clarity === "number" && (
                        <span>· clarity {Math.round(scene.clarity * 100)}%</span>
                      )}
                      {scene.approved === true && (
                        <span className="text-[var(--accent)]">· VLM ok</span>
                      )}
                      {scene.approved === false && (
                        <span className="text-[var(--accent-hot)]">
                          · needs work
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-lg font-medium">{scene.title}</p>
                    {scene.narration && (
                      <p className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]">
                        {scene.narration}
                      </p>
                    )}
                    {scene.beats && scene.beats.length > 0 && (
                      <ul className="mt-2 space-y-0.5 text-sm text-[var(--ink-muted)]">
                        {scene.beats.map((b) => (
                          <li key={b}>· {b}</li>
                        ))}
                      </ul>
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
                    {jobId && scene.status === "done" && (
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
              {finalNotes && (
                <div className="mt-6 text-sm text-[var(--ink-muted)]">
                  <p className="mb-1 text-xs uppercase tracking-[0.14em]">
                    Final debug
                  </p>
                  <p className="text-[var(--ink)]">{finalNotes}</p>
                </div>
              )}
            </div>

            <div>
              <p className="mb-2 text-xs uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                Live log
              </p>
              <div
                ref={logContainerRef}
                className="max-h-[28rem] overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--surface-inset)] p-4 font-mono text-xs leading-relaxed text-[var(--ink-muted)]"
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
            </div>
          </div>
        )}
      </section>

      <DebugInspector activeJobId={jobId} live={running} />
    </>
  );
}
