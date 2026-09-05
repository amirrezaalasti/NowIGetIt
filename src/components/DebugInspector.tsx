"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  addSceneComment,
  approveScene,
  assetUrl,
  ensureApiToken,
  fetchJob,
  listJobs,
  streamRetouch,
  type HumanComment,
  type JobDetail,
  type PipelineEvent,
  type JobSummary,
} from "@/lib/api";
import { SceneEditor } from "@/components/SceneEditor";
import { AuthMedia } from "@/components/AuthMedia";
import { captureVideoFrame, formatMarkTime, MarkedVideoPlayer } from "@/components/MarkedVideoPlayer";

type JobFilter = "all" | "ready" | "in_progress";
type StatusTone = "ready" | "live" | "warn" | "muted";

function formatRelativeDate(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

function formatAbsoluteDate(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function jobStatusMeta(job: JobSummary): { label: string; tone: StatusTone } {
  const status = (job.status || "").toLowerCase();
  if (job.has_result || status === "complete") {
    return { label: job.has_final_video ? "Ready" : "Complete", tone: "ready" };
  }
  if (status === "running") return { label: "Generating", tone: "live" };
  if (status === "awaiting_plan") return { label: "Awaiting plan", tone: "warn" };
  if (status === "interrupted") return { label: "Interrupted", tone: "warn" };
  if (status === "unknown" || !status) return { label: "Draft", tone: "muted" };
  return { label: status.replace(/_/g, " "), tone: "muted" };
}

function jobHref(job: JobSummary): string {
  const kind = job.kind || "";
  const id = job.job_id;
  if (
    kind === "podcast" ||
    kind === "quiz" ||
    kind === "interactive" ||
    id.startsWith("pod_") ||
    id.startsWith("quiz_") ||
    id.startsWith("lab_")
  ) {
    return `/learn?id=${encodeURIComponent(id)}`;
  }
  if (kind === "document" || id.startsWith("doc_")) {
    return `/understand?doc=${encodeURIComponent(id)}`;
  }
  return `/?job=${encodeURIComponent(id)}`;
}

function kindLabel(job: JobSummary): string | null {
  const kind =
    job.kind ||
    (job.job_id.startsWith("pod_")
      ? "podcast"
      : job.job_id.startsWith("quiz_")
        ? "quiz"
        : job.job_id.startsWith("lab_")
          ? "interactive"
          : job.job_id.startsWith("doc_")
            ? "document"
            : "");
  if (!kind || kind === "video") return null;
  if (kind === "interactive") return "lab";
  return kind;
}

function matchesFilter(job: JobSummary, filter: JobFilter): boolean {
  if (filter === "all") return true;
  const status = (job.status || "").toLowerCase();
  const ready = Boolean(job.has_result) || status === "complete";
  if (filter === "ready") return ready;
  return !ready;
}

function statusToneClass(tone: StatusTone): string {
  if (tone === "ready") {
    return "bg-[var(--accent)]/15 text-[var(--accent)]";
  }
  if (tone === "live") {
    return "bg-[var(--accent-hot)]/15 text-[var(--accent-hot)]";
  }
  if (tone === "warn") {
    return "bg-[var(--danger-bg)] text-[var(--danger-ink)]";
  }
  return "bg-[var(--surface-strong)] text-[var(--ink-muted)]";
}

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
  const [capturedFrame, setCapturedFrame] = useState<string | null>(null);
  const [capturedTime, setCapturedTime] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Map of commentId → AI reply data
  const [aiReplies, setAiReplies] = useState<Record<string, AIReply>>({});
  // Stable cache-bust — only changes when a retouch with a new VIDEO succeeds
  const [videoCacheBust, setVideoCacheBust] = useState(() => Date.now());
  // Latest concept frame from retouch (when Manim not available)
  const [latestFrameUrl, setLatestFrameUrl] = useState<string | null>(null);
  const [latestVideoUrl, setLatestVideoUrl] = useState<string | null>(null);

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

  const handleMarkFrame = () => {
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    const time = video.currentTime;
    setCapturedTime(time);
    setUseTimestamp(true);
    setCapturedFrame(captureVideoFrame(video));
  };

  const handleSubmit = async (e: React.FormEvent, retouch = true) => {
    e.preventDefault();
    if (!newComment.trim() || submitting) return;

    const commentText = newComment.trim();
    const currentTime =
      capturedTime ??
      (useTimestamp && videoRef.current ? videoRef.current.currentTime : undefined);

    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setSubmitting(true);
    setSubmitError(null);
    setNewComment("");

    // Step 1: save comment immediately → get its ID
    let savedComment: HumanComment;
    try {
      savedComment = await addSceneComment(
        jobId,
        sceneId,
        commentText,
        currentTime,
        { frameBase64: capturedFrame || undefined },
      );
      setComments((prev) => [...prev, savedComment]);
      setCapturedFrame(null);
      setCapturedTime(null);
    } catch (err) {
      setSubmitting(false);
      setNewComment(commentText);
      setSubmitError((err as Error).message || "Failed to save feedback");
      return;
    }

    if (!retouch) {
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
          const newVideoUrl = typeof data?.video_url === "string" ? data.video_url : null;

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
            if (newVideoUrl) setLatestVideoUrl(newVideoUrl);
            setVideoCacheBust(Date.now());
            onRefresh?.();
          }
        },
        abort.signal,
        cid,
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

  const currentVideoUrl = latestVideoUrl ? assetUrl(latestVideoUrl) : videoUrl;
  const videoSrc = `${currentVideoUrl}${currentVideoUrl.includes("?") ? "&" : "?"}cb=${videoCacheBust}`;

  return (
    <div className="mt-4 space-y-3">
      {/* ── Video or Updated Concept Frame ── */}
      <div className="relative">
        <video
          ref={videoRef}
          key={String(videoCacheBust)}
          className="w-full rounded-xl border border-[var(--line)] bg-[var(--surface-video)]"
          src={videoSrc}
          controls
          playsInline
          preload="metadata"
        />
        <button
          type="button"
          onClick={handleMarkFrame}
          className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/65 px-3 py-1.5 text-[11px] font-semibold text-white backdrop-blur-sm transition hover:bg-black/80"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M5 3v18l7-4 7 4V3z" />
          </svg>
          Mark this frame
        </button>
        {latestFrameUrl && (
          <div className="mt-2 rounded-xl border border-[var(--line)] overflow-hidden">
            <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-[var(--ink-muted)] bg-[var(--surface-strong)]">
              Updated Concept Preview (Manim rendering disabled — code is revised)
            </p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={assetUrl(latestFrameUrl)}
              alt="Retouched concept preview"
              className="w-full object-contain bg-[var(--surface-panel)]"
            />
          </div>
        )}
      </div>

      {/* ── Chat Thread ── */}
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface)] flex flex-col">
        <div className="border-b border-[var(--line)] px-4 pb-2 pt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
            Scene feedback
          </h4>
          <p className="mt-0.5 text-[10px] text-[var(--ink-muted)]">
            Describe changes — AI revises this scene only.
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
                  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--accent)] px-3 py-2 text-xs text-[var(--on-accent)]">
                    {typeof c.timestamp === "number" && (
                      <button
                        type="button"
                        onClick={() => seekTo(c.timestamp)}
                        className="mb-1 flex items-center gap-1 text-[10px] opacity-70 hover:opacity-100"
                      >
                        At {formatMarkTime(c.timestamp)}
                      </button>
                    )}
                    {c.frame_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={assetUrl(c.frame_url)}
                        alt=""
                        className="mb-1.5 max-h-24 w-full rounded-lg object-cover"
                      />
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
                    <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-[var(--line)] bg-[var(--surface-panel)] px-3 py-2 text-xs space-y-1">
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
                              className="flex-1 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[11px] font-semibold text-[var(--on-accent)] hover:opacity-90 transition"
                            >
                              Approve &amp; update final video
                            </button>
                            <button
                              type="button"
                              onClick={() => handleReject(c.id)}
                              className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-[11px] font-medium text-[var(--ink-muted)] transition hover:border-[var(--ink)] hover:text-[var(--ink)]"
                            >
                              Not quite
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
                          <p className="text-[11px] font-semibold text-[var(--accent)]">
                            Approved — final video updated.
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
                        <p className="pt-0.5 text-[11px] text-red-400">{reply.error}</p>
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
          {submitError && (
            <p className="text-[11px] text-red-400">{submitError}</p>
          )}
          {capturedFrame && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface-strong)] p-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={capturedFrame} alt="" className="h-12 w-20 rounded object-cover" />
              <div className="min-w-0 flex-1 text-[11px] text-[var(--ink-muted)]">
                Marked frame
                {typeof capturedTime === "number" ? ` at ${formatMarkTime(capturedTime)}` : ""}
              </div>
              <button
                type="button"
                onClick={() => {
                  setCapturedFrame(null);
                  setCapturedTime(null);
                }}
                className="text-[11px] text-[var(--ink-muted)] hover:text-[var(--ink)]"
              >
                Clear
              </button>
            </div>
          )}
          <textarea
            value={newComment}
            onChange={(e) => {
              setNewComment(e.target.value);
              if (submitError) setSubmitError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleSubmit(e as unknown as React.FormEvent, true);
              }
            }}
            placeholder="Describe what to change on the marked frame… (⌘↵ to retouch)"
            rows={2}
            disabled={submitting}
            className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-strong)] p-2 text-xs text-[var(--ink)] focus:outline-none focus:border-[var(--accent)] resize-none disabled:opacity-60"
          />
          <div className="flex items-center justify-between gap-2">
            <label className="flex items-center gap-1.5 text-xs text-[var(--ink-muted)] cursor-pointer">
              <input
                type="checkbox"
                checked={useTimestamp}
                onChange={(e) => setUseTimestamp(e.target.checked)}
                disabled={submitting}
                className="rounded border-[var(--line)]"
              />
              Pin video timestamp
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={(e) => void handleSubmit(e, false)}
                disabled={!newComment.trim() || submitting}
                className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-xs font-medium text-[var(--ink)] transition hover:border-[var(--accent)] disabled:opacity-40"
              >
                Save mark
              </button>
              <button
                type="button"
                onClick={(e) => void handleSubmit(e, true)}
                disabled={!newComment.trim() || submitting}
                className="shrink-0 flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-4 py-1.5 text-xs font-semibold text-[var(--on-accent)] transition hover:opacity-90 disabled:opacity-40"
              >
                {submitting && (
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                )}
                {submitting ? "Retouching…" : "Send"}
              </button>
            </div>
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
  const { status: authStatus } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [tab, setTab] = useState<"scenes" | "advanced">("scenes");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<JobFilter>("all");
  const [copiedId, setCopiedId] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  // Track which scenes are in "edit" mode (interactive canvas)
  const [editingScenes, setEditingScenes] = useState<Set<string>>(new Set());
  const hasLoadedRef = useRef(false);
  const loadedForIdRef = useRef<string | null>(null);
  const signedIn = authStatus === "authenticated";

  const syncJobToUrl = useCallback(
    (jobId: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (jobId) params.set("job", jobId);
      else params.delete("job");
      const next = params.toString();
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const selectJob = useCallback(
    (jobId: string) => {
      setSelectedId(jobId);
      setTab("scenes");
      syncJobToUrl(jobId);
    },
    [syncJobToUrl],
  );

  const refreshJobs = useCallback(async () => {
    if (!signedIn) {
      setJobs([]);
      setListLoading(false);
      return;
    }
    try {
      await ensureApiToken();
      const list = await listJobs();
      setJobs(list);
      setListError(null);
    } catch (err) {
      setListError((err as Error).message || "Failed to load library");
    } finally {
      setListLoading(false);
    }
  }, [signedIn]);

  const bumpRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs, activeJobId]);

  useEffect(() => {
    if (activeJobId) {
      setSelectedId(activeJobId);
      return;
    }
    const fromUrl = searchParams.get("job");
    if (fromUrl) setSelectedId(fromUrl);
  }, [activeJobId, searchParams]);

  useEffect(() => {
    if (!selectedId || !signedIn) {
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

    void ensureApiToken()
      .then(() => fetchJob(selectedId))
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
  }, [selectedId, refreshKey, signedIn]);

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

  async function onRefresh() {
    setRefreshing(true);
    try {
      await refreshJobs();
      bumpRefresh();
    } finally {
      setRefreshing(false);
    }
  }

  const filteredJobs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return jobs
      .filter((j) => matchesFilter(j, filter))
      .filter((j) => {
        if (!q) return true;
        const haystack = [j.title, j.prompt, j.job_id]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .sort((a, b) => {
        const aTime = a.created_at ? Date.parse(a.created_at) : 0;
        const bTime = b.created_at ? Date.parse(b.created_at) : 0;
        return bTime - aTime;
      });
  }, [jobs, filter, query]);

  const filterCounts = useMemo(() => {
    const counts = { all: jobs.length, ready: 0, in_progress: 0 };
    for (const j of jobs) {
      if (matchesFilter(j, "ready")) counts.ready += 1;
      else counts.in_progress += 1;
    }
    return counts;
  }, [jobs]);

  const selectedSummary = useMemo(
    () => jobs.find((j) => j.job_id === selectedId) || null,
    [jobs, selectedId],
  );

  const selectedStatus = selectedSummary
    ? jobStatusMeta(selectedSummary)
    : job?.runtime?.status
      ? jobStatusMeta({
          job_id: job.job_id,
          status: job.runtime.status,
          has_result: job.runtime.has_result,
          has_final_video: job.runtime.has_final_video,
        })
      : null;

  async function copyJobId() {
    if (!selectedId) return;
    try {
      await navigator.clipboard.writeText(selectedId);
      setCopiedId(true);
      window.setTimeout(() => setCopiedId(false), 1600);
    } catch {
      /* clipboard may be unavailable */
    }
  }

  if (!signedIn) {
    return (
      <section className="relative mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 pb-28 pt-4 text-center">
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
          Your library
        </h1>
        <p className="mx-auto mt-3 max-w-md text-sm text-[var(--ink-muted)]">
          Sign in to revisit past explanations, download videos, and retouch
          individual scenes.
        </p>
        <Link
          href="/login?callbackUrl=/library"
          className="mt-8 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
        >
          Continue with Google
        </Link>
      </section>
    );
  }

  const filterOptions: { id: JobFilter; label: string }[] = [
    { id: "all", label: `All (${filterCounts.all})` },
    { id: "ready", label: `Ready (${filterCounts.ready})` },
    { id: "in_progress", label: `In progress (${filterCounts.in_progress})` },
  ];

  return (
    <section className="relative mx-auto w-full max-w-6xl px-6 pb-28">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4 animate-rise">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.16em] text-[var(--ink-muted)]">
            Library
            {live && selectedId === activeJobId && (
              <span className="ml-2 normal-case tracking-normal text-[var(--accent)]">
                · live
              </span>
            )}
          </p>
          <h1 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight sm:text-4xl">
            Past explanations
          </h1>
          <p className="mt-2 max-w-xl text-sm text-[var(--ink-muted)]">
            Browse finished videos, resume in-progress work, leave scene feedback,
            or inspect pipeline artifacts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/"
            className="rounded-lg border border-[var(--line)] px-3.5 py-2 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
          >
            New explanation
          </Link>
          <button
            type="button"
            onClick={() => void onRefresh()}
            disabled={refreshing || listLoading}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--ink)] transition hover:bg-[var(--bg-lift)] disabled:opacity-50"
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent ${
                refreshing ? "animate-spin" : "opacity-40"
              }`}
              aria-hidden
            />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="mb-5 flex flex-col gap-3 animate-rise-delay sm:flex-row sm:items-center sm:justify-between">
        <label className="relative block min-w-0 flex-1 sm:max-w-md">
          <span className="sr-only">Search explanations</span>
          <svg
            viewBox="0 0 20 20"
            fill="none"
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--ink-muted)]"
          >
            <path
              d="M8.5 14.5a6 6 0 1 1 0-12 6 6 0 0 1 0 12Zm5.3-1.2 3.4 3.4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, prompt, or id…"
            className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] py-2.5 pl-9 pr-3 text-sm text-[var(--ink)] placeholder:text-[var(--ink-muted)] outline-none transition focus:border-[var(--accent)]"
          />
        </label>
        <div
          role="radiogroup"
          aria-label="Filter by status"
          className="inline-flex max-w-full flex-wrap rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-0.5"
        >
          {filterOptions.map((opt) => {
            const selected = filter === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => setFilter(opt.id)}
                className={`rounded-md px-3 py-1.5 text-sm transition ${
                  selected
                    ? "bg-[var(--bg-lift)] text-[var(--ink)] shadow-sm"
                    : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)] xl:grid-cols-[22rem_minmax(0,1fr)]">
        <aside className="min-w-0 lg:sticky lg:top-20 lg:self-start">
          <div className="mb-3 flex items-baseline justify-between gap-2">
            <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
              Explanations
            </p>
            {!listLoading && (
              <p className="text-xs text-[var(--ink-muted)]">
                {filteredJobs.length}
                {filteredJobs.length !== jobs.length ? ` of ${jobs.length}` : ""}
              </p>
            )}
          </div>

          {listError && (
            <p className="mb-3 rounded-lg border border-[var(--danger-line)] bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger-ink)]">
              {listError}
            </p>
          )}

          {listLoading ? (
            <ul className="space-y-2" aria-hidden>
              {Array.from({ length: 6 }).map((_, i) => (
                <li
                  key={i}
                  className="h-[4.5rem] animate-pulse rounded-xl bg-[var(--surface)]"
                />
              ))}
            </ul>
          ) : jobs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-4 py-8 text-sm text-[var(--ink-muted)]">
              <p className="font-medium text-[var(--ink)]">Nothing here yet</p>
              <p className="mt-1.5">
                Create an explanation and it will appear in your library.
              </p>
              <Link
                href="/"
                className="mt-4 inline-flex rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110"
              >
                Create explanation
              </Link>
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-4 py-6 text-sm text-[var(--ink-muted)]">
              No matches
              {query.trim() ? ` for “${query.trim()}”` : ""}.
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setFilter("all");
                }}
                className="mt-3 block text-[var(--accent)] underline-offset-4 hover:underline"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <ul className="max-h-[min(70vh,40rem)] space-y-1 overflow-y-auto pr-1">
              {filteredJobs.map((j) => {
                const active = selectedId === j.job_id;
                const status = jobStatusMeta(j);
                const relative = formatRelativeDate(j.created_at);
                return (
                  <li key={j.job_id}>
                    <button
                      type="button"
                      onClick={() => selectJob(j.job_id)}
                      aria-current={active ? "true" : undefined}
                      className={`group w-full rounded-xl px-3 py-3 text-left transition ${
                        active
                          ? "bg-[var(--surface)] ring-1 ring-[var(--accent)]/35"
                          : "hover:bg-[var(--surface)]/70"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span
                          className={`min-w-0 flex-1 text-sm font-medium leading-snug ${
                            active ? "text-[var(--ink)]" : "text-[var(--ink)]/90"
                          }`}
                        >
                          <span className="line-clamp-2">
                            {j.title?.trim() || "Untitled explanation"}
                          </span>
                        </span>
                        <span className="flex shrink-0 flex-col items-end gap-1">
                          {kindLabel(j) ? (
                            <span className="rounded-md bg-[var(--surface-strong)] px-1.5 py-0.5 text-[10px] capitalize text-[var(--ink-muted)]">
                              {kindLabel(j)}
                            </span>
                          ) : null}
                          <span
                            className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium capitalize ${statusToneClass(status.tone)}`}
                          >
                            {status.label}
                          </span>
                        </span>
                      </div>
                      <span className="mt-1.5 flex items-center gap-1.5 text-[11px] text-[var(--ink-muted)]">
                        {relative ? <span>{relative}</span> : null}
                        {relative ? <span aria-hidden>·</span> : null}
                        <span className="font-mono opacity-70">
                          {j.job_id.slice(0, 8)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <div className="min-w-0 animate-rise-delay-2">
          {error && (
            <p className="mb-4 rounded-lg border border-[var(--danger-line)] bg-[var(--danger-bg)] px-3 py-2 text-sm text-[var(--danger-ink)]">
              {error}
            </p>
          )}

          {!selectedId && !listLoading && jobs.length > 0 && (
            <div className="flex min-h-[22rem] flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--line)] bg-[var(--surface)]/40 px-6 py-16 text-center">
              <p className="font-[family-name:var(--font-display)] text-xl tracking-tight text-[var(--ink)]">
                Select an explanation
              </p>
              <p className="mt-2 max-w-sm text-sm text-[var(--ink-muted)]">
                Pick one from the list to watch the final video, leave scene
                feedback, or inspect advanced artifacts.
              </p>
            </div>
          )}

          {selectedId && loading && !job && (
            <div className="space-y-4" aria-busy aria-label="Loading explanation">
              <div className="h-8 w-2/3 animate-pulse rounded-lg bg-[var(--surface)]" />
              <div className="h-4 w-full animate-pulse rounded bg-[var(--surface)]" />
              <div className="aspect-video w-full animate-pulse rounded-2xl bg-[var(--surface)]" />
            </div>
          )}

          {job && (
            <>
              <div className="mb-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight sm:text-3xl">
                      {String(
                        job.scene_plan?.title ||
                          selectedSummary?.title ||
                          "Untitled explanation",
                      )}
                    </h2>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                      {selectedStatus ? (
                        <span
                          className={`rounded-md px-2 py-1 font-medium capitalize ${statusToneClass(selectedStatus.tone)}`}
                        >
                          {selectedStatus.label}
                          {job.runtime?.running ? " · generating…" : ""}
                        </span>
                      ) : null}
                      {job.scenes.length > 0 ? (
                        <span className="rounded-md bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink-muted)]">
                          {job.scenes.length} scene
                          {job.scenes.length === 1 ? "" : "s"}
                        </span>
                      ) : null}
                      {selectedSummary?.created_at ? (
                        <span
                          className="rounded-md bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink-muted)]"
                          title={formatAbsoluteDate(selectedSummary.created_at)}
                        >
                          {formatAbsoluteDate(selectedSummary.created_at)}
                        </span>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => void copyJobId()}
                        className="rounded-md bg-[var(--surface-strong)] px-2 py-1 font-mono text-[var(--ink-muted)] transition hover:text-[var(--ink)]"
                        title="Copy job id"
                      >
                        {copiedId ? "Copied" : `${job.job_id.slice(0, 10)}…`}
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={jobHref({
                        job_id: job.job_id,
                        kind:
                          selectedSummary?.kind ||
                          (typeof job.meta?.kind === "string" ? job.meta.kind : undefined),
                      })}
                      className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
                    >
                      Open
                    </Link>
                    {(job.final_video_url || job.urls?.final_video) && (
                      <a
                        href={assetUrl(job.final_video_url || job.urls?.final_video)}
                        download
                        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110"
                      >
                        Download
                      </a>
                    )}
                    {(job.gif_url || job.urls?.final_gif) && (
                      <a
                        href={assetUrl(job.gif_url || job.urls?.final_gif)}
                        download
                        className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
                      >
                        Download GIF
                      </a>
                    )}
                  </div>
                </div>
                {selectedSummary?.prompt ? (
                  <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-[var(--ink-muted)]">
                    {selectedSummary.prompt}
                  </p>
                ) : null}
              </div>

              {(job.final_video_url || job.urls?.final_video) ? (
                <div className="mb-10">
                  <p className="mb-2 text-sm text-[var(--ink)]">Final video</p>
                  <p className="mb-3 text-xs text-[var(--ink-muted)]">
                    Pause on a frame, mark it, and leave a comment. The agent uses that screenshot and timestamp to edit the scene.
                  </p>
                  <MarkedVideoPlayer
                    jobId={job.job_id}
                    src={job.final_video_url || job.urls?.final_video}
                    timeline={job.timeline}
                    initialMarks={job.video_marks}
                    onMarksChange={() => bumpRefresh()}
                    loop={Boolean(job.gif_url || job.urls?.final_gif)}
                  />
                  {(job.gif_url || job.urls?.final_gif) && (
                    <div className="mt-4">
                      <p className="mb-2 text-sm text-[var(--ink)]">Looping GIF</p>
                      <AuthMedia
                        kind="image"
                        src={job.gif_url || job.urls?.final_gif}
                        alt="Looping GIF"
                        className="w-full max-w-md overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-video)]"
                      />
                    </div>
                  )}
                </div>
              ) : (
                !loading && (
                  <div className="mb-10 rounded-2xl border border-dashed border-[var(--line)] bg-[var(--surface)]/30 px-5 py-8 text-sm text-[var(--ink-muted)]">
                    No final video yet
                    {job.runtime?.running
                      ? " — generation is still running."
                      : selectedSummary && !selectedSummary.has_result
                        ? " — this explanation is still in progress."
                        : "."}
                    <Link
                      href={`/?job=${encodeURIComponent(job.job_id)}`}
                      className="mt-2 block text-[var(--accent)] underline-offset-4 hover:underline"
                    >
                      Resume in Create
                    </Link>
                  </div>
                )
              )}

              <div className="mb-6 flex gap-4 border-b border-[var(--line)] text-sm">
                <button
                  type="button"
                  onClick={() => setTab("scenes")}
                  className={`border-b-2 pb-2 transition ${
                    tab === "scenes"
                      ? "border-[var(--accent)] text-[var(--ink)]"
                      : "border-transparent text-[var(--ink-muted)]"
                  }`}
                >
                  Scenes
                  {job.scenes.length > 0 ? ` (${job.scenes.length})` : ""}
                </button>
                <button
                  type="button"
                  onClick={() => setTab("advanced")}
                  className={`border-b-2 pb-2 transition ${
                    tab === "advanced"
                      ? "border-[var(--accent)] text-[var(--ink)]"
                      : "border-transparent text-[var(--ink-muted)]"
                  }`}
                >
                  Advanced
                </button>
              </div>

              {tab === "scenes" && (
                <div className="space-y-8">
                  {job.scenes.length === 0 && (
                    <p className="text-sm text-[var(--ink-muted)]">
                      No scenes recorded for this job yet.
                    </p>
                  )}
                  {job.scenes.map((scene, sceneIndex) => {
                    const isEditing = editingScenes.has(scene.scene_id);
                    return (
                      <article
                        key={scene.scene_id}
                        className="border-t border-[var(--line)] pt-6 first:border-t-0 first:pt-0"
                      >
                        <div className="mb-2 flex items-start justify-between gap-3">
                          <div>
                            <div className="mb-1 flex flex-wrap items-baseline gap-2">
                              <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                                Scene {sceneIndex + 1}
                              </span>
                              <h3 className="text-lg font-medium">
                                {String(scene.section?.title || scene.scene_id)}
                              </h3>
                            </div>
                            <p className="mt-1 text-sm text-[var(--ink-muted)]">
                              {String(scene.section?.visual_description || "")}
                            </p>
                          </div>
                          {scene.code_final && (
                            <button
                              type="button"
                              onClick={() => {
                                setEditingScenes((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(scene.scene_id)) {
                                    next.delete(scene.scene_id);
                                  } else {
                                    next.add(scene.scene_id);
                                  }
                                  return next;
                                });
                              }}
                              className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[11px] font-medium transition ${
                                isEditing
                                  ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                                  : "border-[var(--line)] text-[var(--ink-muted)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
                              }`}
                            >
                              {isEditing ? (
                                <>
                                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                                  Watch Video
                                </>
                              ) : (
                                <>
                                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                                  Edit Scene
                                </>
                              )}
                            </button>
                          )}
                        </div>

                        {/* Interactive Editor or Video Player */}
                        {isEditing ? (
                          <SceneEditor
                            jobId={job.job_id}
                            sceneId={scene.scene_id}
                            initialTimestamp={0.0}
                            onVideoUpdated={(url) => {
                              if (url) bumpRefresh();
                            }}
                          />
                        ) : (
                          scene.video_url && (
                            <SceneVideoPlayer
                              jobId={job.job_id}
                              sceneId={scene.scene_id}
                              videoUrl={assetUrl(scene.video_url)}
                              initialComments={scene.human_comments || []}
                              onRefresh={bumpRefresh}
                            />
                          )
                        )}

                        {(scene.vlm_reviews || []).length > 0 && (
                          <div className="mt-4 grid gap-4 sm:grid-cols-2">
                            {(scene.vlm_reviews || []).map((review, idx) => (
                              <div
                                key={`${scene.scene_id}-r${idx}`}
                                className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface)]"
                              >
                                {typeof review.frame_url === "string" &&
                                  review.frame_url && (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img
                                      src={assetUrl(review.frame_url)}
                                      alt={`Frame preview ${idx}`}
                                      className="aspect-video w-full bg-[var(--surface-strong)] object-cover"
                                    />
                                  )}
                                <div className="p-3 text-xs text-[var(--ink-muted)]">
                                  Concept frame ·{" "}
                                  {String(
                                    review.review_mode ||
                                      review.frame_source ||
                                      "preview",
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}

              {tab === "advanced" && (
                <div className="space-y-6">
                  {job.urls?.scene_plan && (
                    <a
                      href={assetUrl(job.urls.scene_plan)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-sm text-[var(--accent)] underline-offset-4 hover:underline"
                    >
                      Open scene_plan.json
                    </a>
                  )}

                  <details open className="group">
                    <summary className="cursor-pointer text-sm text-[var(--ink)]">
                      Scene plan JSON
                    </summary>
                    <pre className="mt-3 max-h-[24rem] overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-panel)] p-4 text-xs leading-relaxed text-[var(--ink-muted)]">
                      {JSON.stringify(job.scene_plan, null, 2)}
                    </pre>
                  </details>

                  <details className="group">
                    <summary className="cursor-pointer text-sm text-[var(--ink)]">
                      Event log
                    </summary>
                    <pre className="mt-3 max-h-[24rem] overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-panel)] p-4 text-xs leading-relaxed text-[var(--ink-muted)]">
                      {JSON.stringify(job.events, null, 2)}
                    </pre>
                  </details>

                  {job.scenes.some((s) => s.code_final) && (
                    <details className="group">
                      <summary className="cursor-pointer text-sm text-[var(--ink)]">
                        Generated Manim code
                      </summary>
                      <div className="mt-3 space-y-4">
                        {job.scenes.map((scene) =>
                          scene.code_final ? (
                            <div key={scene.scene_id}>
                              <p className="mb-2 text-xs text-[var(--ink-muted)]">
                                {String(scene.section?.title || scene.scene_id)}
                              </p>
                              <pre className="max-h-64 overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-panel)] p-3 text-[11px] text-[var(--ink-muted)]">
                                {scene.code_final}
                              </pre>
                            </div>
                          ) : null,
                        )}
                      </div>
                    </details>
                  )}

                  {job.final_debug && (
                    <details className="group">
                      <summary className="cursor-pointer text-sm text-[var(--ink)]">
                        Final debug
                      </summary>
                      <pre className="mt-3 max-h-[24rem] overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-panel)] p-4 text-xs text-[var(--ink-muted)]">
                        {JSON.stringify(job.final_debug, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
