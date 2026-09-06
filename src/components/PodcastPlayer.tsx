"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { mediaUrl, type PodcastScript } from "@/lib/api";

type Props = {
  title: string;
  audioUrl?: string | null;
  script: PodcastScript;
  takeaways?: string[];
  audioSkipped?: boolean;
};

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function PodcastPlayer({
  title,
  audioUrl,
  script,
  takeaways,
  audioSkipped,
}: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [src, setSrc] = useState<string>("");
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!audioUrl) {
      setSrc("");
      return;
    }
    setSrc(mediaUrl(audioUrl, Date.now()));
  }, [audioUrl]);

  const chapter = useMemo(() => {
    const list = script.chapters || [];
    let found = list[0];
    for (const ch of list) {
      if (current >= (ch.start_seconds || 0)) found = ch;
    }
    return found;
  }, [script.chapters, current]);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
          Podcast
        </p>
        <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
          {title}
        </h2>
        {script.tagline ? (
          <p className="mt-2 text-sm text-[var(--ink-muted)]">{script.tagline}</p>
        ) : null}
        {src ? (
          <audio
            ref={audioRef}
            src={src}
            controls
            className="mt-5 w-full"
            onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
          />
        ) : (
          <p className="mt-4 text-sm text-[var(--ink-muted)]">
            {audioSkipped
              ? "Audio was skipped (TTS isn’t configured). Read along below."
              : "Audio isn’t ready yet — you can still read the transcript."}
          </p>
        )}
      </div>

      <ol className="space-y-2">
        {script.chapters.map((ch) => {
          const on = chapter?.id === ch.id;
          return (
            <li key={ch.id}>
              <button
                type="button"
                onClick={() => {
                  const el = audioRef.current;
                  if (el) {
                    el.currentTime = ch.start_seconds || 0;
                    void el.play();
                  }
                }}
                className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                  on
                    ? "border-[var(--accent)] bg-[var(--surface)]"
                    : "border-[var(--line)] hover:border-[var(--accent)]/50"
                }`}
              >
                <span className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-[var(--ink)]">{ch.title}</span>
                  <span className="font-mono text-xs text-[var(--ink-muted)]">
                    {formatTime(ch.start_seconds)}
                    {playing && on ? " · now" : ""}
                  </span>
                </span>
                {ch.summary ? (
                  <span className="mt-1 block text-sm text-[var(--ink-muted)]">
                    {ch.summary}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ol>

      <div className="space-y-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
          Transcript · {chapter?.title || ""}
        </p>
        {(chapter?.lines || []).map((line, i) => (
          <p key={`${chapter?.id}-${i}`} className="text-sm leading-relaxed">
            <span className="mr-2 font-semibold text-[var(--accent)]">
              {line.speaker === "host"
                ? script.host_name || "Host"
                : script.guide_name || "Guide"}
            </span>
            <span className="text-[var(--ink)]">{line.text}</span>
          </p>
        ))}
      </div>

      {takeaways && takeaways.length > 0 ? (
        <div>
          <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
            Takeaways
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--ink)]">
            {takeaways.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
