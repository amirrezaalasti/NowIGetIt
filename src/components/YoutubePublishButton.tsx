"use client";

import { useState } from "react";
import Link from "next/link";
import {
  fetchYoutubeStatus,
  publishJobToYoutube,
  type YoutubePublishResult,
} from "@/lib/api";

export function YoutubePublishButton({
  jobId,
  privacy = "unlisted",
  title,
  disabled,
  onPublished,
}: {
  jobId: string;
  privacy?: "public" | "unlisted" | "private";
  title?: string;
  disabled?: boolean;
  onPublished?: (result: YoutubePublishResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<YoutubePublishResult | null>(null);

  async function publish() {
    setBusy(true);
    setError(null);
    try {
      const yt = await fetchYoutubeStatus();
      if (!yt.connected) {
        setError("Connect YouTube in Settings first.");
        return;
      }
      const published = await publishJobToYoutube(jobId, { privacy, title });
      setResult(published);
      onPublished?.(published);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (result?.url) {
    return (
      <a
        href={result.url}
        target="_blank"
        rel="noreferrer"
        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-semibold text-[var(--on-accent)]"
      >
        Open on YouTube
      </a>
    );
  }

  return (
    <span className="inline-flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => void publish()}
        className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)] disabled:opacity-50"
      >
        {busy ? "Publishing…" : "Publish to YouTube"}
      </button>
      {error ? (
        <span className="max-w-xs text-right text-xs text-[var(--danger-ink)]">
          {error}{" "}
          <Link href="/settings" className="underline-offset-2 hover:underline">
            Settings
          </Link>
        </span>
      ) : null}
    </span>
  );
}
