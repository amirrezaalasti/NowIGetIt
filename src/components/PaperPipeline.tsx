"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { SegmentedControl } from "@/components/SegmentedControl";
import {
  SourceAttachments,
  readySourceIds,
  type AttachedSource,
} from "@/components/SourceAttachments";
import { YoutubePublishButton } from "@/components/YoutubePublishButton";
import {
  cancelJob,
  ensureApiToken,
  fetchHealth,
  fetchJob,
  fetchYoutubeStatus,
  streamPaperPipeline,
  youtubeConnectUrl,
  type Audience,
  type JobDetail,
  type LanguageOption,
  type LengthPreset,
  type PipelineEvent,
  type ScenePacing,
  type TtsVoiceOption,
  type YoutubePublishResult,
  type YoutubeStatus,
} from "@/lib/api";
import { AuthMedia } from "@/components/AuthMedia";
import { MarkedVideoPlayer } from "@/components/MarkedVideoPlayer";

const LENGTH_OPTIONS: { id: LengthPreset; label: string; hint: string }[] = [
  { id: "clip", label: "GIF", hint: "~12s loop" },
  { id: "short", label: "60s", hint: "Quick intuition" },
  { id: "standard", label: "90s", hint: "Balanced" },
  { id: "deep", label: "3 min", hint: "Deep dive" },
];

const AUDIENCE_OPTIONS: { id: Audience; label: string }[] = [
  { id: "general", label: "General" },
  { id: "hs", label: "High school" },
  { id: "undergrad", label: "Undergrad" },
];

export function PaperPipeline() {
  const { status } = useSession();
  const [sources, setSources] = useState<AttachedSource[]>([]);
  const [prompt, setPrompt] = useState("");
  const [length, setLength] = useState<LengthPreset>("standard");
  const [pacing, setPacing] = useState<ScenePacing>("balanced");
  const [audience, setAudience] = useState<Audience>("general");
  const [language, setLanguage] = useState("en");
  const [voice, setVoice] = useState("Kore");
  const [autoPublish, setAutoPublish] = useState(false);
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">(
    "unlisted",
  );
  const [youtube, setYoutube] = useState<YoutubeStatus | null>(null);
  const [voices, setVoices] = useState<TtsVoiceOption[]>([]);
  const [languages, setLanguages] = useState<LanguageOption[]>([]);
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [published, setPublished] = useState<YoutubePublishResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    void ensureApiToken()
      .then(() =>
        Promise.all([fetchYoutubeStatus(), fetchHealth()]),
      )
      .then(([yt, health]) => {
        if (cancelled) return;
        setYoutube(yt);
        if (health.tts_voices?.length) setVoices(health.tts_voices);
        if (health.languages?.length) setLanguages(health.languages);
        if (health.tts_voice) setVoice(health.tts_voice);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [status]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void fetchJob(jobId)
        .then((detail) => {
          if (!cancelled) setJob(detail);
        })
        .catch(() => {
          /* still generating */
        });
    }, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId]);

  async function connectYoutube() {
    const { url } = await youtubeConnectUrl(window.location.origin, "/pipeline");
    window.location.href = url;
  }

  async function run() {
    const ids = readySourceIds(sources);
    if (!ids.length) {
      setError("Attach at least one PDF or paper first.");
      return;
    }
    if (autoPublish && !youtube?.connected) {
      setError("Connect YouTube before auto-publish, or turn auto-publish off.");
      return;
    }
    setError(null);
    setPublished(null);
    setEvents([]);
    setJob(null);
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let seenJobId = jobId;
    try {
      await ensureApiToken();
      await streamPaperPipeline(
        {
          prompt,
          source_doc_ids: ids,
          length_preset: length,
          scene_pacing: pacing,
          audience,
          language,
          tts_voice: voice,
          auto_publish: autoPublish,
          youtube_privacy: privacy,
        },
        (event) => {
          setEvents((prev) => [...prev.slice(-40), event]);
          const data = event.data || {};
          if (typeof data.job_id === "string") {
            seenJobId = data.job_id;
            setJobId(data.job_id);
          }
          const yt = data.youtube as YoutubePublishResult | undefined;
          if (yt?.url) setPublished(yt);
          if (event.type === "error") setError(event.message);
        },
        controller.signal,
      );
      if (seenJobId) {
        try {
          setJob(await fetchJob(seenJobId));
        } catch {
          /* ignore */
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  if (status === "loading") {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <p className="text-sm text-[var(--ink-muted)]">Checking session…</p>
      </section>
    );
  }

  if (status !== "authenticated") {
    return (
      <section className="relative mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 py-16 text-center">
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
          Paper pipeline
        </h1>
        <p className="mx-auto mt-4 max-w-md text-sm text-[var(--ink-muted)]">
          Sign in to attach papers, generate an explainer, and publish it to
          your YouTube channel.
        </p>
        <Link
          href="/login?callbackUrl=/pipeline"
          className="mt-10 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
        >
          Continue with Google
        </Link>
      </section>
    );
  }

  const last = events[events.length - 1];
  const videoUrl = job?.final_video_url || job?.urls?.final_video;
  const youtubeUrl =
    published?.url ||
    (typeof job?.meta?.youtube === "object" &&
    job.meta.youtube &&
    typeof (job.meta.youtube as { url?: string }).url === "string"
      ? (job.meta.youtube as { url: string }).url
      : null);

  return (
    <section className="relative mx-auto w-full max-w-3xl px-6 py-12">
      <p className="text-sm text-[var(--ink-muted)]">Automated</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
        Paper → video → YouTube
      </h1>
      <p className="mt-3 max-w-2xl text-[var(--ink-muted)]">
        Attach a paper or slide deck, generate a Manim explainer, then publish
        it to the YouTube account you connect here.
      </p>

      <section className="mt-10 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--ink)]">
              1. YouTube
            </h2>
            <p className="mt-1 text-sm text-[var(--ink-muted)]">
              {youtube?.connected
                ? `Connected${youtube.channel_title ? ` · ${youtube.channel_title}` : ""}`
                : "Connect the channel that should receive the video."}
            </p>
          </div>
          {youtube?.connected ? (
            <Link
              href="/settings"
              className="text-sm text-[var(--accent)] underline-offset-2 hover:underline"
            >
              Manage
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => void connectYoutube()}
              disabled={youtube?.configured === false}
              className="rounded-full bg-[var(--accent)] px-4 py-1.5 text-sm font-semibold text-[var(--on-accent)] disabled:opacity-50"
            >
              Connect YouTube
            </button>
          )}
        </div>
        {youtube && !youtube.configured ? (
          <p className="mt-3 text-sm text-[var(--accent-hot)]">
            Google OAuth is not configured. Add YouTube Data API v3 and redirect
            URI <code>/api/youtube/callback</code> — see Settings.
          </p>
        ) : null}
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <h2 className="text-sm font-semibold text-[var(--ink)]">
          2. Papers & references
        </h2>
        <p className="mt-1 mb-4 text-sm text-[var(--ink-muted)]">
          PDF, PPTX, DOCX, or notes. The storyboard is grounded in this
          material.
        </p>
        <SourceAttachments
          items={sources}
          onChange={setSources}
          disabled={running}
        />
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={running}
          rows={3}
          placeholder="Optional focus: “Explain the proof of theorem 3 for undergrads.” Leave blank to cover the whole paper."
          className="mt-4 w-full resize-y rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <h2 className="text-sm font-semibold text-[var(--ink)]">3. Production</h2>
        <div className="mt-4 flex flex-col gap-4">
          <SegmentedControl
            label="Length"
            value={length}
            options={LENGTH_OPTIONS}
            onChange={setLength}
            disabled={running}
          />
          <SegmentedControl
            label="Audience"
            value={audience}
            options={AUDIENCE_OPTIONS}
            onChange={setAudience}
            disabled={running}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm text-[var(--ink-muted)]">
              Language
              <select
                className="mt-1 w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-[var(--ink)]"
                value={language}
                disabled={running}
                onChange={(e) => setLanguage(e.target.value)}
              >
                {(languages.length
                  ? languages
                  : [{ id: "en", label: "English", native_label: "English" }]
                ).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.native_label || item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-[var(--ink-muted)]">
              Voice
              <select
                className="mt-1 w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-[var(--ink)]"
                value={voice}
                disabled={running}
                onChange={(e) => setVoice(e.target.value)}
              >
                {(voices.length
                  ? voices
                  : [{ id: "Kore", gender: "Female", label: "Kore" }]
                ).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex items-start gap-3 text-sm text-[var(--ink)]">
            <input
              type="checkbox"
              className="mt-1"
              checked={autoPublish}
              disabled={running}
              onChange={(e) => setAutoPublish(e.target.checked)}
            />
            <span>
              Publish automatically when the video is ready
              <span className="block text-[var(--ink-muted)]">
                Default privacy is unlisted. You can also publish later from
                Library.
              </span>
            </span>
          </label>
          {autoPublish ? (
            <SegmentedControl
              label="YouTube privacy"
              value={privacy}
              options={[
                { id: "unlisted", label: "Unlisted" },
                { id: "private", label: "Private" },
                { id: "public", label: "Public" },
              ]}
              onChange={setPrivacy}
              disabled={running}
            />
          ) : null}
        </div>
      </section>

      {error ? (
        <p className="mt-6 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-ink)]">
          {error}
        </p>
      ) : null}

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void run()}
          disabled={running || sources.every((s) => s.status !== "ready")}
          className="rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110 disabled:opacity-50"
        >
          {running ? "Running pipeline…" : "Run pipeline"}
        </button>
        {running && jobId ? (
          <button
            type="button"
            onClick={() => {
              abortRef.current?.abort();
              void cancelJob(jobId);
            }}
            className="rounded-full border border-[var(--line)] px-5 py-2.5 text-sm text-[var(--ink-muted)]"
          >
            Cancel
          </button>
        ) : null}
        <Link
          href="/settings"
          className="text-sm text-[var(--ink-muted)] underline-offset-2 hover:underline"
        >
          Provider keys
        </Link>
      </div>

      {last ? (
        <p className="mt-6 text-sm text-[var(--ink-muted)]">{last.message}</p>
      ) : null}

      {videoUrl ? (
        <div className="mt-10">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-[var(--ink)]">Result</h2>
            {jobId ? (
              <YoutubePublishButton
                jobId={jobId}
                privacy={privacy}
                disabled={running}
                onPublished={setPublished}
              />
            ) : null}
          </div>
          <MarkedVideoPlayer
            jobId={jobId || ""}
            src={videoUrl}
            timeline={job?.timeline}
            initialMarks={job?.video_marks}
          />
          {youtubeUrl ? (
            <a
              href={youtubeUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-block text-sm text-[var(--accent)] underline-offset-2 hover:underline"
            >
              Open on YouTube
            </a>
          ) : null}
          {job?.gif_url || job?.urls?.final_gif ? (
            <div className="mt-6">
              <p className="mb-2 text-sm text-[var(--ink)]">Looping GIF</p>
              <AuthMedia
                kind="image"
                src={job.gif_url || job.urls?.final_gif}
                alt="Looping GIF"
                className="w-full max-w-md overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-video)]"
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
