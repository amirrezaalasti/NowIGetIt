"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  addSceneComment,
  approveScene,
  assetUrl,
  fetchJob,
  listJobs,
  streamRetouch,
  type HumanComment,
  type JobDetail,
  type PipelineEvent,
  type JobSummary,
} from "@/lib/api";

// ---- SceneVideoPlayer -------------------------------------------------------

type RetouchStep = { message: string; type: string; ts: number };

type AIReply = {
  commentId: string;
  steps: RetouchStep[];
  done: boolean;
  error: string | null;
  frameUrl: string | null;
  hasVideo: boolean;
  // approval flow
  approvalState: "pending" | "approving" | "approved" | "rejected" | null;
  approvalNote: string | null;
  finalVideoUrl: string | null;
};

function SceneVideoPlayer({
  jobId,
  sceneId,
  videoUrl,
  initialComments,
  onRefresh,
}: {
  jobId: string;
  sceneId: string;
  videoUrl: string;
  initialComments: HumanComment[];
  onRefresh?: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const [comments, setComments] = useState<HumanComment[]>(initialComments);
  const [newComment, setNewComment] = useState("");
  const [useTimestamp, setUseTimestamp] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  // Map of commentId → AI reply data
  const [aiReplies, setAiReplies] = useState<Record<string, AIReply>>({});
  // Stable cache-bust — only changes when a retouch with a new VIDEO succeeds
  const [videoCacheBust, setVideoCacheBust] = useState(() => Date.now());
  // Latest concept frame from retouch (when Manim not available)
  const [latestFrameUrl, setLatestFrameUrl] = useState<string | null>(null);

  useEffect(() => {
    setComments(initialComments);
  }, [initialComments]);

  // Auto-scroll chat box internally (without scrolling the browser window)
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [comments, aiReplies]);

  const upsertReply = (commentId: string, patch: Partial<AIReply>) => {
    setAiReplies((prev) => {
      const existing = prev[commentId] ?? {
        commentId, steps: [], done: false, error: null, frameUrl: null, hasVideo: false,
        approvalState: null, approvalNote: null, finalVideoUrl: null,
      };
      return { ...prev, [commentId]: { ...existing, ...patch } };
    });
  };

  const handleApprove = async (commentId: string) => {
    upsertReply(commentId, { approvalState: "approving" });
    try {
      const result = await approveScene(jobId, sceneId);
      upsertReply(commentId, {
        approvalState: "approved",
        finalVideoUrl: result.final_video_url,
        approvalNote: result.note ?? null,
      });
      if (result.final_video_url) {
        setVideoCacheBust(Date.now());
        onRefresh?.();
      }
    } catch (err) {
      upsertReply(commentId, { approvalState: "pending", error: "Approval failed: " + String(err) });
    }
  };

  const handleReject = (commentId: string) => {
    upsertReply(commentId, { approvalState: "rejected" });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim() || submitting) return;

    const commentText = newComment.trim();
    const currentTime =
      useTimestamp && videoRef.current ? videoRef.current.currentTime : undefined;

    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setSubmitting(true);
    setNewComment("");

    // Step 1: save comment immediately → get its ID
    let savedComment: HumanComment;
    try {
      savedComment = await addSceneComment(jobId, sceneId, commentText, currentTime);
      setComments((prev) => [...prev, savedComment]);
    } catch (err) {
      setSubmitting(false);
      return;
    }

    const cid = savedComment.id;
    upsertReply(cid, { steps: [], done: false, error: null, approvalState: null });
    // Step 2: stream AI retouch — append steps to that comment's reply
    try {
      await streamRetouch(
        jobId,
        sceneId,
        commentText,
        currentTime,
        (event: PipelineEvent) => {
          const step: RetouchStep = { message: event.message, type: event.type, ts: Date.now() };
          // Capture frame_url and video status from the "complete" payload
          const data = (event as PipelineEvent & { data?: Record<string, unknown> }).data;
          const frameUrl = typeof data?.frame_url === "string" ? data.frame_url : null;
          const hasVideo = typeof data?.video_url === "string" && Boolean(data.video_url);

          const isDone =
            event.type === "complete" ||
            event.type === "error" ||
            (event.type === "status" && event.message.toLowerCase().startsWith("retouch complete"));

          setAiReplies((prev) => {
            const existing = prev[cid] ?? {
              steps: [], done: false, error: null, frameUrl: null, hasVideo: false,
              approvalState: null, approvalNote: null, finalVideoUrl: null, commentId: cid,
            };
            return {
              ...prev,
              [cid]: {
                ...existing,
                steps: [...existing.steps, step],
                done: isDone || existing.done,
                frameUrl: frameUrl ?? existing.frameUrl,
                hasVideo: hasVideo || existing.hasVideo,
                // When retouch is done, set to "pending" so approval buttons appear
                approvalState: isDone ? "pending" : existing.approvalState,
              },
            };
          });

          if (isDone) {
            if (frameUrl) setLatestFrameUrl(frameUrl);
            setVideoCacheBust(Date.now());
            onRefresh?.();
          }
        },
        abort.signal
      );
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        upsertReply(cid, { error: String(err), done: true });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const seekTo = (seconds?: number | null) => {
    if (typeof seconds === "number" && videoRef.current) {
      videoRef.current.currentTime = seconds;
      videoRef.current.play().catch(() => {});
    }
  };

  const videoSrc = `${assetUrl(videoUrl)}${videoUrl.includes("?") ? "&" : "?"}cb=${videoCacheBust}`;

  return (
    <div className="mt-4 space-y-3">
      {/* ── Video or Updated Concept Frame ── */}
      <div className="relative">
        <video
          ref={videoRef}
          key={String(videoCacheBust)}
          className="w-full rounded-xl border border-[var(--line)] bg-black"
          src={videoSrc}
          controls
          playsInline
          preload="metadata"
        />
        {latestFrameUrl && (
          <div className="mt-2 rounded-xl border border-[var(--line)] overflow-hidden">
            <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--ink-muted)] bg-black/40">
              Updated Concept Preview (Manim rendering disabled — code is revised)
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={assetUrl(latestFrameUrl)}
              alt="Retouched concept preview"
              className="w-full object-contain bg-black/30"
            />
          </div>
        )}
      </div>

      {/* ── Chat Thread ── */}
      <div className="rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.02)] flex flex-col">
        <div className="px-4 pt-3 pb-2 border-b border-[var(--line)]">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
            Scene Feedback &amp; AI Retouch Chat
          </h4>
          <p className="text-[10px] text-[var(--ink-muted)] mt-0.5">
            Describe changes below — AI will revise this scene only.
          </p>
        </div>

        {/* Message thread */}
        <div ref={chatContainerRef} className="flex-1 overflow-auto max-h-[28rem] px-4 py-3 space-y-4">
          {comments.length === 0 && !submitting && (
            <p className="text-xs text-[var(--ink-muted)] italic text-center py-4">
              No feedback yet. Watch the scene and tell the AI what to change.
            </p>
          )}

          {comments.map((c) => {
            const reply = aiReplies[c.id];
            return (
              <div key={c.id} className="space-y-2">
                {/* Human message bubble */}
                <div className="flex items-end gap-2 justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--accent)] px-3 py-2 text-xs text-black">
                    {typeof c.timestamp === "number" && (
                      <button
                        type="button"
                        onClick={() => seekTo(c.timestamp)}
                        className="mb-1 flex items-center gap-1 text-[10px] opacity-70 hover:opacity-100"
                      >
                        ⏱ At {c.timestamp.toFixed(1)}s
                      </button>
                    )}
                    <p className="leading-relaxed">{c.comment}</p>
                    <span className="mt-1 block text-[10px] opacity-60 text-right">
                      {new Date(c.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {c.author}
                    </span>
                  </div>
                </div>

                {/* AI reply bubble */}
                {reply && (
                  <div className="flex items-end gap-2 justify-start">
                    <div className="shrink-0 w-6 h-6 rounded-full bg-[var(--line)] flex items-center justify-center text-[10px]">
                      AI
                    </div>
                    <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-[var(--line)] bg-[rgba(0,0,0,0.3)] px-3 py-2 text-xs space-y-1">
                      {reply.steps.map((s, i) => (
                        <div
                          key={i}
                          className={`flex items-start gap-2 ${
                            s.type === "error"
                              ? "text-red-400"
                              : s.message.toLowerCase().includes("complete")
                              ? "text-[var(--accent)] font-semibold"
                              : "text-[var(--ink-muted)]"
                          }`}
                        >
                          <span className="shrink-0 text-[10px] opacity-40 tabular-nums pt-px">
                            {new Date(s.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                          </span>
                          <span>{s.message}</span>
                        </div>
                      ))}

                      {/* Typing indicator while streaming */}
                      {!reply.done && (
                        <div className="flex items-center gap-1 pt-0.5">
                          {[0, 150, 300].map((delay) => (
                            <span
                              key={delay}
                              className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce"
                              style={{ animationDelay: `${delay}ms` }}
                            />
                          ))}
                        </div>
                      )}

                      {/* ── Approval gate ── */}
                      {reply.done && !reply.error && reply.approvalState === "pending" && (
                        <div className="mt-2 space-y-2 border-t border-[var(--line)] pt-2">
                          <p className="text-[var(--ink)] font-medium text-[11px]">
                            Review the concept preview above — does this look right?
                          </p>
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => void handleApprove(c.id)}
                              className="flex-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[11px] font-semibold text-black hover:opacity-90 transition"
                            >
                              ✓ Approve &amp; Update Final Video
                            </button>
                            <button
                              type="button"
                              onClick={() => handleReject(c.id)}
                              className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-[11px] font-medium text-[var(--ink-muted)] hover:text-[var(--ink)] hover:border-[var(--ink)] transition"
                            >
                              ✗ Not quite
                            </button>
                          </div>
                        </div>
                      )}

                      {reply.approvalState === "approving" && (
                        <div className="mt-2 flex items-center gap-2 text-[var(--accent)] text-[11px]">
                          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "0ms" }} />
                          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "150ms" }} />
                          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "300ms" }} />
                          <span>Updating final video…</span>
                        </div>
                      )}

                      {reply.approvalState === "approved" && (
                        <div className="mt-2 space-y-1 border-t border-[var(--line)] pt-2">
                          <p className="text-[var(--accent)] font-semibold text-[11px]">
                            ✓ Approved! Final video updated.
                          </p>
                          {reply.approvalNote && (
                            <p className="text-[var(--ink-muted)] text-[10px] italic">{reply.approvalNote}</p>
                          )}
                        </div>
                      )}

                      {reply.approvalState === "rejected" && (
                        <div className="mt-2 border-t border-[var(--line)] pt-2">
                          <p className="text-[var(--ink-muted)] text-[11px] italic">
                            Changes discarded. Add another comment to try again.
                          </p>
                        </div>
                      )}

                      {reply.error && (
                        <p className="text-red-400 pt-0.5 text-[11px]">⚠ {reply.error}</p>
                      )}
                    </div>
                  </div>
                )}

              </div>
            );
          })}

          {/* In-flight comment placeholder while saving */}
          {submitting && comments.length === 0 && (
            <div className="flex items-center gap-1.5 justify-center text-[var(--ink-muted)]">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
          )}

        </div>

        {/* Input form */}
        <div className="border-t border-[var(--line)] px-4 py-3 space-y-2">
          <textarea
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleSubmit(e as unknown as React.FormEvent);
              }
            }}
            placeholder="Describe what to change… (⌘↵ to send)"
            rows={2}
            className="w-full rounded-lg border border-[var(--line)] bg-black/40 p-2 text-xs text-[var(--ink)] focus:outline-none focus:border-[var(--accent)] resize-none"
          />
          <div className="flex items-center justify-between gap-2">
            <label className="flex items-center gap-1.5 text-xs text-[var(--ink-muted)] cursor-pointer">
              <input
                type="checkbox"
                checked={useTimestamp}
                onChange={(e) => setUseTimestamp(e.target.checked)}
                className="rounded border-[var(--line)]"
              />
              Pin video timestamp
            </label>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!newComment.trim() || submitting}
              className="shrink-0 rounded-lg bg-[var(--accent)] px-4 py-1.5 text-xs font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
            >
              {submitting ? "Retouching…" : "Send ↵"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}



type Props = {
  activeJobId: string | null;
  /** True while the generate SSE stream is in progress — polls job detail live. */
  live?: boolean;
};

const POLL_MS = 1500;

export function DebugInspector({ activeJobId, live = false }: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [tab, setTab] = useState<"plan" | "scenes" | "events">("scenes");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const hasLoadedRef = useRef(false);
  const loadedForIdRef = useRef<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const list = await listJobs();
      setJobs(list);
    } catch {
      /* API may be offline */
    }
  }, []);

  const bumpRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs, activeJobId]);

  useEffect(() => {
    if (activeJobId) setSelectedId(activeJobId);
  }, [activeJobId]);

  useEffect(() => {
    if (!selectedId) {
      setJob(null);
      hasLoadedRef.current = false;
      loadedForIdRef.current = null;
      return;
    }

    if (loadedForIdRef.current !== selectedId) {
      hasLoadedRef.current = false;
      loadedForIdRef.current = selectedId;
    }

    let cancelled = false;
    const silent = hasLoadedRef.current;
    if (!silent) setLoading(true);
    setError(null);

    fetchJob(selectedId)
      .then((detail) => {
        if (!cancelled) {
          setJob(detail);
          hasLoadedRef.current = true;
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  // Live-poll artifacts while generation is running for the selected job
  useEffect(() => {
    if (!live || !selectedId || selectedId !== activeJobId) return;
    const id = window.setInterval(bumpRefresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [live, selectedId, activeJobId, bumpRefresh]);

  // One final pull when the stream ends (catch last frames / events / video)
  const wasLiveRef = useRef(false);
  useEffect(() => {
    if (wasLiveRef.current && !live && selectedId) {
      bumpRefresh();
      void refreshJobs();
    }
    wasLiveRef.current = live;
  }, [live, selectedId, bumpRefresh, refreshJobs]);

  function onRefresh() {
    void refreshJobs();
    bumpRefresh();
  }

  return (
    <section className="relative mx-auto w-full max-w-3xl px-6 pb-28">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--ink-muted)]">
            Debug inspector
            {live && selectedId === activeJobId && (
              <span className="ml-2 normal-case tracking-normal text-[var(--accent)]">
                · live
              </span>
            )}
          </p>
          <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl">
            Saved plans & VLM frames
          </h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
        >
          Refresh
        </button>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        {jobs.length === 0 && (
          <p className="text-sm text-[var(--ink-muted)]">
            No saved jobs yet — generate once to populate{" "}
            <code className="text-[var(--accent)]">artifacts/</code>.
          </p>
        )}
        {jobs.map((j) => (
          <button
            key={j.job_id}
            type="button"
            onClick={() => setSelectedId(j.job_id)}
            className={`rounded-full border px-3 py-1.5 text-left text-xs transition ${
              selectedId === j.job_id
                ? "border-[var(--accent)] text-[var(--ink)]"
                : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
            }`}
          >
            <span className="font-medium">{j.title || j.job_id}</span>
            <span className="ml-2 opacity-60">{j.job_id.slice(0, 6)}</span>
          </button>
        ))}
      </div>

      {error && (
        <p className="mb-4 text-sm text-red-200">{error}</p>
      )}
      {loading && (
        <p className="mb-4 text-sm text-[var(--ink-muted)]">Loading job…</p>
      )}

      {job && (
        <>
          {(job.final_video_url || job.urls?.final_video) && (
            <div className="mb-8">
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-sm text-[var(--ink)]">
                  Final video <span className="text-[var(--ink-muted)]">(with audio)</span>
                </p>
                <a
                  href={assetUrl(job.final_video_url || job.urls?.final_video)}
                  download
                  className="text-sm text-[var(--accent)] underline-offset-4 hover:underline"
                >
                  Download
                </a>
              </div>
              <video
                key={job.final_video_url || job.urls?.final_video}
                className="w-full rounded-2xl border border-[var(--line)] bg-black"
                src={assetUrl(job.final_video_url || job.urls?.final_video)}
                controls
                playsInline
                preload="metadata"
              />
            </div>
          )}

          <div className="mb-4 flex gap-4 text-sm">
            {(
              [
                ["scenes", "Scenes & frames"],
                ["plan", "Scene JSON"],
                ["events", "Event log"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`border-b pb-1 transition ${
                  tab === id
                    ? "border-[var(--accent)] text-[var(--ink)]"
                    : "border-transparent text-[var(--ink-muted)]"
                }`}
              >
                {label}
              </button>
            ))}
            {job.urls?.scene_plan && (
              <a
                href={assetUrl(job.urls.scene_plan)}
                target="_blank"
                rel="noreferrer"
                className="ml-auto text-[var(--accent)] underline-offset-4 hover:underline"
              >
                Open scene_plan.json
              </a>
            )}
          </div>

          {tab === "plan" && (
            <pre className="max-h-[32rem] overflow-auto rounded-2xl border border-[var(--line)] bg-[rgba(0,0,0,0.3)] p-4 text-xs leading-relaxed text-[var(--ink-muted)]">
              {JSON.stringify(job.scene_plan, null, 2)}
            </pre>
          )}

          {tab === "events" && (
            <pre className="max-h-[32rem] overflow-auto rounded-2xl border border-[var(--line)] bg-[rgba(0,0,0,0.3)] p-4 text-xs leading-relaxed text-[var(--ink-muted)]">
              {JSON.stringify(job.events, null, 2)}
            </pre>
          )}

          {tab === "scenes" && (
            <div className="space-y-8">
              {job.scenes.map((scene) => (
                <article
                  key={scene.scene_id}
                  className="border-t border-[var(--line)] pt-6"
                >
                  <h3 className="text-lg font-medium">
                    {String(scene.section?.title || scene.scene_id)}
                  </h3>
                  <p className="mt-1 text-sm text-[var(--ink-muted)]">
                    {String(scene.section?.visual_description || "")}
                  </p>

                  {scene.video_url && (
                    <SceneVideoPlayer
                      jobId={job.job_id}
                      sceneId={scene.scene_id}
                      videoUrl={assetUrl(scene.video_url)}
                      initialComments={scene.human_comments || []}
                      onRefresh={bumpRefresh}
                    />
                  )}

                  <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    {(scene.vlm_reviews || []).map((review, idx) => (
                      <div
                        key={`${scene.scene_id}-r${idx}`}
                        className="overflow-hidden rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.02)]"
                      >
                        {typeof review.frame_url === "string" && review.frame_url && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={assetUrl(review.frame_url)}
                            alt={`Frame preview ${idx}`}
                            className="aspect-video w-full object-cover bg-black/40"
                          />
                        )}
                        <div className="space-y-2 p-3 text-xs">
                          <p className="text-[var(--ink-muted)]">
                            Initial Concept Frame ·{" "}
                            {String(review.review_mode || review.frame_source || "preview")}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>

                  {scene.code_final && (
                    <details className="mt-4">
                      <summary className="cursor-pointer text-sm text-[var(--ink-muted)]">
                        Generated Manim code
                      </summary>
                      <pre className="mt-2 max-h-64 overflow-auto rounded-xl border border-[var(--line)] bg-black/30 p-3 text-[11px] text-[var(--ink-muted)]">
                        {scene.code_final}
                      </pre>
                    </details>
                  )}
                </article>
              ))}

              {job.final_debug && (
                <div className="rounded-xl border border-[var(--line)] p-4 text-sm">
                  <p className="text-xs uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                    Final debug
                  </p>
                  <pre className="mt-2 overflow-auto text-xs text-[var(--ink-muted)]">
                    {JSON.stringify(job.final_debug, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
