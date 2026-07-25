"use client";

import { useCallback, useEffect, useState } from "react";
import {
  assetUrl,
  fetchJob,
  listJobs,
  type JobDetail,
  type JobSummary,
} from "@/lib/api";

type Props = {
  activeJobId: string | null;
};

export function DebugInspector({ activeJobId }: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [tab, setTab] = useState<"plan" | "scenes" | "events">("scenes");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refreshJobs = useCallback(async () => {
    try {
      const list = await listJobs();
      setJobs(list);
    } catch {
      /* API may be offline */
    }
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
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJob(selectedId)
      .then((detail) => {
        if (!cancelled) setJob(detail);
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
  }, [selectedId]);

  return (
    <section className="relative mx-auto w-full max-w-3xl px-6 pb-28">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--ink-muted)]">
            Debug inspector
          </p>
          <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl">
            Saved plans & VLM frames
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void refreshJobs()}
          className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
        >
          Refresh jobs
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
                    <video
                      className="mt-4 w-full rounded-xl border border-[var(--line)] bg-black"
                      src={assetUrl(scene.video_url)}
                      controls
                      playsInline
                      preload="metadata"
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
                            alt={`VLM frame r${String(review.revision ?? idx)}`}
                            className="aspect-video w-full object-cover bg-black/40"
                          />
                        )}
                        <div className="space-y-2 p-3 text-xs">
                          <p className="text-[var(--ink-muted)]">
                            rev {String(review.revision ?? idx)} ·{" "}
                            {String(review.review_mode || review.frame_source || "unknown")}
                            {review.frame_source === "storyboard" ||
                            review.frame_source === "visual_preview"
                              ? review.frame_source === "visual_preview"
                                ? " · matplotlib preview (not Manim)"
                                : " · plan card (not a render)"
                              : ""}{" "}
                            ·{" "}
                            <span
                              className={
                                review.approved
                                  ? "text-[var(--accent)]"
                                  : "text-[var(--accent-hot)]"
                              }
                            >
                              {review.approved ? "approved" : "needs revision"}
                            </span>
                          </p>
                          {Array.isArray(review.issues) &&
                            review.issues.length > 0 && (
                              <ul className="list-disc pl-4 text-[var(--ink-muted)]">
                                {(review.issues as string[]).map((issue) => (
                                  <li key={issue}>{issue}</li>
                                ))}
                              </ul>
                            )}
                          {typeof review.revision_instructions === "string" &&
                            review.revision_instructions && (
                              <p className="text-[var(--ink)]">
                                {review.revision_instructions}
                              </p>
                            )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {scene.code_final && (
                    <details className="mt-4">
                      <summary className="cursor-pointer text-sm text-[var(--ink-muted)]">
                        Final Manim code
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
