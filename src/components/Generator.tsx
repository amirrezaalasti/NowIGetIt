"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DebugInspector } from "@/components/DebugInspector";
import {
  assetUrl,
  fetchHealth,
  streamGenerate,
  type PipelineEvent,
} from "@/lib/api";

type ScenePreview = {
  id: string;
  title: string;
  narration?: string;
  approved?: boolean;
  frameUrl?: string;
  videoUrl?: string;
  status?: string;
};

const EXAMPLES = [
  "Explain gradient descent on a simple parabola",
  "Show why the Pythagorean theorem works visually",
  "Animate how sine and cosine relate on the unit circle",
];

export function Generator() {
  const [prompt, setPrompt] = useState("");
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [planTitle, setPlanTitle] = useState<string | null>(null);
  const [scenes, setScenes] = useState<ScenePreview[]>([]);
  const [finalNotes, setFinalNotes] = useState<string | null>(null);
  const [finalVideoUrl, setFinalVideoUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<string>("Checking API…");
  const [liveMessage, setLiveMessage] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

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
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const statusLabel = useMemo(() => {
    if (error) return "Failed";
    if (!running && events.length === 0) return "Idle";
    const last = events[events.length - 1];
    if (last?.type === "complete") return "Done";
    if (running) return "Generating";
    return "Idle";
  }, [events, running, error]);

  async function onGenerate() {
    if (!prompt.trim() || running) return;
    setRunning(true);
    setError(null);
    setEvents([]);
    setPlanTitle(null);
    setScenes([]);
    setFinalNotes(null);
    setFinalVideoUrl(null);
    setJobId(null);
    setLiveMessage("Starting…");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamGenerate(
        prompt.trim(),
        (event) => {
          setEvents((prev) => [...prev, event]);
          setLiveMessage(event.message);
          if (event.data?.job_id && typeof event.data.job_id === "string") {
            setJobId(event.data.job_id);
          }
          if (event.type === "plan" && event.data) {
            setPlanTitle(String(event.data.title || "Untitled"));
            const list =
              (event.data.scenes as Array<Record<string, string>>) || [];
            setScenes(
              list.map((s) => ({
                id: s.id,
                title: s.title,
                narration: s.narration,
                status: "queued",
              })),
            );
          }
          if (event.type === "scene_start" && event.data?.scene_id) {
            setScenes((prev) =>
              prev.map((s) =>
                s.id === event.data?.scene_id
                  ? { ...s, status: "building" }
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
                      videoUrl:
                        typeof event.data?.video_url === "string"
                          ? event.data.video_url
                          : s.videoUrl,
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
                      status: event.data?.approved ? "approved" : "revising",
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
                  const match = completed.find((c) => c.scene_id === s.id);
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
          }
          if (event.type === "error") {
            setError(event.message);
          }
        },
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

  return (
    <>
      <section className="relative mx-auto w-full max-w-3xl px-6 pb-16 pt-6">
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
          className="w-full resize-none rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-5 py-4 text-lg leading-relaxed text-[var(--ink)] outline-none transition focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_var(--glow)] placeholder:text-[var(--ink-muted)] animate-rise-delay-2"
        />

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
            className="group relative overflow-hidden rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[#062016] transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="relative z-10">
              {running ? "Building scenes…" : "Generate explanation"}
            </span>
          </button>
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

        {running && liveMessage && (
          <p className="mt-4 text-sm text-[var(--accent)] animate-rise">
            {liveMessage}
          </p>
        )}

        {error && (
          <p className="mt-6 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </p>
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
              <a
                href={assetUrl(finalVideoUrl)}
                download
                className="text-sm text-[var(--accent)] underline-offset-4 hover:underline"
              >
                Download mp4
              </a>
            </div>
            <video
              key={finalVideoUrl}
              className="mt-4 w-full rounded-2xl border border-[var(--line)] bg-black"
              src={assetUrl(finalVideoUrl)}
              controls
              playsInline
              preload="metadata"
            />
          </div>
        )}

        {(planTitle || events.length > 0) && (
          <div className="mt-12 grid gap-8 lg:grid-cols-[1.05fr_0.95fr]">
            <div>
              <h2 className="font-[family-name:var(--font-display)] text-2xl text-[var(--ink)]">
                {planTitle || "Pipeline"}
              </h2>
              <ul className="mt-5 space-y-6">
                {scenes.map((scene, i) => (
                  <li key={scene.id} className="border-l-2 border-[var(--line)] pl-4">
                    <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--ink-muted)]">
                      <span className="progress-dot inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                      Scene {i + 1}
                      {scene.status && <span>· {scene.status}</span>}
                      {scene.approved === true && (
                        <span className="text-[var(--accent)]">· VLM ok</span>
                      )}
                      {scene.approved === false && (
                        <span className="text-[var(--accent-hot)]">
                          · needs work
                        </span>
                      )}
                    </div>
                    <p className="mt-1 font-medium">{scene.title}</p>
                    {scene.narration && (
                      <p className="mt-1 line-clamp-2 text-sm text-[var(--ink-muted)]">
                        {scene.narration}
                      </p>
                    )}
                    {scene.videoUrl ? (
                      <video
                        className="mt-3 w-full rounded-xl border border-[var(--line)] bg-black"
                        src={assetUrl(scene.videoUrl)}
                        controls
                        playsInline
                        preload="metadata"
                      />
                    ) : scene.frameUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        className="mt-3 w-full rounded-xl border border-[var(--line)]"
                        src={assetUrl(scene.frameUrl)}
                        alt={`${scene.title} preview`}
                      />
                    ) : null}
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
              <div className="max-h-[28rem] overflow-y-auto rounded-2xl border border-[var(--line)] bg-[rgba(0,0,0,0.25)] p-4 font-mono text-xs leading-relaxed text-[var(--ink-muted)]">
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
                <div ref={logEndRef} />
              </div>
            </div>
          </div>
        )}
      </section>

      <DebugInspector activeJobId={jobId} live={running} />
    </>
  );
}
