"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addVideoMark,
  assetUrl,
  fetchVideoMarks,
  getApiToken,
  mediaUrl,
  streamRetouch,
  type HumanComment,
  type PipelineEvent,
  type VideoTimelineEntry,
} from "@/lib/api";

export function captureVideoFrame(video: HTMLVideoElement): string | null {
  if (!video.videoWidth || !video.videoHeight) return null;
  const canvas = document.createElement("canvas");
  const maxW = 960;
  const scale = Math.min(1, maxW / video.videoWidth);
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  try {
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.72);
  } catch {
    return null;
  }
}

export function formatMarkTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const whole = Math.floor(rest);
  const tenth = Math.floor((rest - whole) * 10);
  return `${m}:${String(whole).padStart(2, "0")}.${tenth}`;
}

function resolveSceneAtTime(
  timeline: VideoTimelineEntry[],
  globalTime: number,
): VideoTimelineEntry | null {
  if (timeline.length === 0) return null;
  for (const entry of timeline) {
    if (globalTime < entry.end) return entry;
  }
  return timeline[timeline.length - 1];
}

type DraftMark = {
  globalTime: number;
  localTime: number;
  sceneId: string;
  sceneTitle: string;
  frameDataUrl: string | null;
};

type Props = {
  jobId: string;
  src: string | null | undefined;
  cacheBust?: number | string;
  sceneId?: string;
  initialMarks?: HumanComment[];
  timeline?: VideoTimelineEntry[];
  onMarksChange?: (marks: HumanComment[]) => void;
  loop?: boolean;
};

export function MarkedVideoPlayer({
  jobId,
  src,
  cacheBust,
  sceneId,
  initialMarks,
  timeline: timelineProp,
  onMarksChange,
  loop = false,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const [marks, setMarks] = useState<HumanComment[]>(initialMarks || []);
  const [timeline, setTimeline] = useState<VideoTimelineEntry[]>(timelineProp || []);
  const [draft, setDraft] = useState<DraftMark | null>(null);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [retouchingId, setRetouchingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (initialMarks) setMarks(initialMarks);
  }, [initialMarks]);

  useEffect(() => {
    if (timelineProp && timelineProp.length > 0) setTimeline(timelineProp);
  }, [timelineProp]);

  useEffect(() => {
    let cancelled = false;
    async function prepare() {
      if (!src) {
        setPlayUrl(null);
        return;
      }
      try {
        await getApiToken();
        if (cancelled) return;
        setPlayUrl(mediaUrl(src, cacheBust ?? Date.now()) || null);
      } catch {
        if (!cancelled) setPlayUrl(null);
      }
    }
    void prepare();
    return () => {
      cancelled = true;
    };
  }, [src, cacheBust]);

  useEffect(() => {
    if (initialMarks && timelineProp && timelineProp.length > 0) return;
    let cancelled = false;
    void fetchVideoMarks(jobId)
      .then((payload) => {
        if (cancelled) return;
        if (!initialMarks) setMarks(payload.marks);
        if (!timelineProp || timelineProp.length === 0) setTimeline(payload.timeline);
      })
      .catch(() => {
        /* marks are optional until the first save */
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, initialMarks, timelineProp]);

  const visibleMarks = useMemo(
    () => (sceneId ? marks.filter((m) => m.scene_id === sceneId) : marks),
    [marks, sceneId],
  );

  const beginMark = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.pause();
    const globalTime = video.currentTime || 0;
    const frameDataUrl = captureVideoFrame(video);
    let resolvedSceneId = sceneId || "";
    let sceneTitle = sceneId ? "This scene" : "Video";
    let localTime = globalTime;
    if (!sceneId) {
      const hit = resolveSceneAtTime(timeline, globalTime);
      if (hit) {
        resolvedSceneId = hit.scene_id;
        sceneTitle = hit.title;
        localTime = Math.max(0, globalTime - hit.start);
      }
    }
    if (!resolvedSceneId && timeline[0]) {
      resolvedSceneId = timeline[0].scene_id;
      sceneTitle = timeline[0].title;
    }
    setDraft({
      globalTime,
      localTime,
      sceneId: resolvedSceneId,
      sceneTitle,
      frameDataUrl,
    });
    setComment("");
    setError(null);
  }, [sceneId, timeline]);

  useEffect(() => {
    if (!hovered) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "m" && event.key !== "M") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "TEXTAREA" || target.tagName === "INPUT")) {
        return;
      }
      event.preventDefault();
      beginMark();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [beginMark, hovered]);

  const seekTo = (seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    video.play().catch(() => {});
  };

  const saveMark = async (andRetouch: boolean) => {
    if (!draft || !comment.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await addVideoMark(jobId, comment.trim(), {
        sceneId: draft.sceneId || sceneId,
        timestamp: draft.localTime,
        globalTimestamp: sceneId ? undefined : draft.globalTime,
        frameBase64: draft.frameDataUrl || undefined,
      });
      const next = [...marks, saved];
      setMarks(next);
      onMarksChange?.(next);
      setDraft(null);
      setComment("");
      if (andRetouch) {
        await runRetouch(saved);
      }
    } catch (err) {
      setError((err as Error).message || "Could not save this mark");
    } finally {
      setSaving(false);
    }
  };

  const runRetouch = async (mark: HumanComment) => {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    setRetouchingId(mark.id);
    setError(null);
    try {
      await streamRetouch(
        jobId,
        mark.scene_id,
        mark.comment,
        mark.timestamp ?? undefined,
        (_event: PipelineEvent) => {},
        abort.signal,
        mark.id,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message || "Retouch failed");
      }
    } finally {
      setRetouchingId(null);
    }
  };

  if (!src) return null;

  return (
    <div
      className="space-y-3"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="relative overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-video)]">
        {playUrl ? (
          <video
            ref={videoRef}
            key={playUrl}
            className="aspect-video w-full"
            src={playUrl}
            controls
            playsInline
            loop={loop}
            preload="metadata"
            onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
          />
        ) : (
          <div className="flex aspect-video items-center justify-center">
            <span className="h-7 w-7 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
          </div>
        )}

        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-3">
          <button
            type="button"
            onClick={beginMark}
            className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-black/65 px-3 py-1.5 text-[11px] font-semibold text-white backdrop-blur-sm transition hover:bg-black/80"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M5 3v18l7-4 7 4V3z" />
            </svg>
            Mark this moment
          </button>
          <span className="rounded-full bg-black/50 px-2 py-1 text-[10px] text-white/80">
            Press M
          </span>
        </div>

        {duration > 0 && visibleMarks.length > 0 && (
          <div className="absolute inset-x-3 bottom-12 h-1.5 rounded-full bg-white/20">
            {visibleMarks.map((mark) => {
              const t = sceneId ? mark.timestamp : mark.global_timestamp;
              if (typeof t !== "number") return null;
              const pct = Math.min(100, Math.max(0, (t / duration) * 100));
              return (
                <button
                  key={mark.id}
                  type="button"
                  title={mark.comment}
                  onClick={() => seekTo(t)}
                  className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white bg-[var(--accent)]"
                  style={{ left: `${pct}%` }}
                />
              );
            })}
          </div>
        )}
      </div>

      {draft && (
        <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-4">
          <div className="flex gap-3">
            {draft.frameDataUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={draft.frameDataUrl}
                alt="Marked frame"
                className="h-24 w-40 shrink-0 rounded-lg object-cover"
              />
            ) : (
              <div className="flex h-24 w-40 shrink-0 items-center justify-center rounded-lg bg-[var(--surface-strong)] text-[10px] text-[var(--ink-muted)]">
                No frame capture
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-[var(--ink)]">
                {formatMarkTime(sceneId ? draft.localTime : draft.globalTime)}
                {draft.sceneTitle ? ` · ${draft.sceneTitle}` : ""}
              </p>
              <p className="mt-0.5 text-[11px] text-[var(--ink-muted)]">
                Describe what should change in this frame. The agent uses this screenshot and timestamp.
              </p>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={3}
                autoFocus
                placeholder="e.g. The axis labels are too small and the arrow should be blue…"
                className="mt-2 w-full resize-none rounded-lg border border-[var(--line)] bg-[var(--surface-strong)] p-2 text-xs text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>
          {error && <p className="mt-2 text-[11px] text-red-400">{error}</p>}
          <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setDraft(null);
                setComment("");
              }}
              className="rounded-lg px-3 py-1.5 text-xs text-[var(--ink-muted)] hover:text-[var(--ink)]"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!comment.trim() || saving || !draft.sceneId}
              onClick={() => void saveMark(false)}
              className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-xs font-medium text-[var(--ink)] transition hover:border-[var(--accent)] disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save mark"}
            </button>
            <button
              type="button"
              disabled={!comment.trim() || saving || !draft.sceneId}
              onClick={() => void saveMark(true)}
              className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--on-accent)] transition hover:opacity-90 disabled:opacity-40"
            >
              Save &amp; retouch
            </button>
          </div>
        </div>
      )}

      {visibleMarks.length > 0 && (
        <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)]">
          <div className="border-b border-[var(--line)] px-4 py-2.5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--ink)]">
              Marked moments
            </h4>
            <p className="mt-0.5 text-[10px] text-[var(--ink-muted)]">
              Saved as metadata for the agent. Retouch applies the comment to that scene.
            </p>
          </div>
          <ul className="divide-y divide-[var(--line)]">
            {visibleMarks.map((mark) => {
              const t = sceneId
                ? mark.timestamp
                : (mark.global_timestamp ?? mark.timestamp);
              return (
                <li key={mark.id} className="flex gap-3 px-4 py-3">
                  {mark.frame_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={assetUrl(mark.frame_url)}
                      alt=""
                      className="h-14 w-24 shrink-0 cursor-pointer rounded-md object-cover"
                      onClick={() => typeof t === "number" && seekTo(t)}
                    />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    <button
                      type="button"
                      onClick={() => typeof t === "number" && seekTo(t)}
                      className="text-[11px] font-medium text-[var(--accent)] hover:underline"
                    >
                      {typeof t === "number" ? formatMarkTime(t) : "Scene"}
                      {mark.scene_title ? ` · ${mark.scene_title}` : ""}
                    </button>
                    <p className="mt-0.5 text-xs leading-relaxed text-[var(--ink)]">
                      {mark.comment}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={retouchingId === mark.id}
                    onClick={() => void runRetouch(mark)}
                    className="shrink-0 self-start rounded-lg border border-[var(--line)] px-2.5 py-1 text-[11px] text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-50"
                  >
                    {retouchingId === mark.id ? "Retouching…" : "Ask AI"}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {error && !draft && (
        <p className="text-[11px] text-red-400">{error}</p>
      )}
    </div>
  );
}
