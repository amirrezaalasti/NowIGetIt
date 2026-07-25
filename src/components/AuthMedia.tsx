"use client";

import { useEffect, useState } from "react";
import { getApiToken, mediaUrl } from "@/lib/api";

type Props = {
  src: string | null | undefined;
  poster?: string | null;
  kind?: "video" | "image";
  className?: string;
  alt?: string;
};

/**
 * Play protected job media via same-origin Next.js file route.
 * That serves from disk in the Node process, so clips keep playing while
 * Python/Manim is busy rendering the next scene.
 */
export function AuthMedia({
  src,
  poster,
  kind = "video",
  className,
  alt = "",
}: Props) {
  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const [posterUrl, setPosterUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function prepare() {
      if (!src) {
        setPlayUrl(null);
        setReady(false);
        return;
      }
      setReady(false);
      setError(null);
      try {
        await getApiToken();
        if (cancelled) return;
        // Cache-bust so a freshly published scene.mp4 is picked up.
        const url = mediaUrl(src, Date.now());
        if (!url) throw new Error("Missing media token");
        setPlayUrl(url);
        setReady(true);
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || "Failed to load media");
          setPlayUrl(null);
          setReady(false);
        }
      }
    }

    void prepare();
    return () => {
      cancelled = true;
    };
  }, [src]);

  useEffect(() => {
    let cancelled = false;

    async function preparePoster() {
      if (!poster) {
        setPosterUrl(null);
        return;
      }
      try {
        await getApiToken();
        if (cancelled) return;
        setPosterUrl(mediaUrl(poster) || null);
      } catch {
        /* optional */
      }
    }

    void preparePoster();
    return () => {
      cancelled = true;
    };
  }, [poster]);

  if (!src) return null;

  if (kind === "image") {
    if (error) {
      return (
        <div
          className={`flex aspect-video items-center justify-center bg-[var(--surface)] text-sm text-[var(--ink-muted)] ${className || ""}`}
        >
          Preview unavailable
        </div>
      );
    }
    if (!playUrl || !ready) {
      return (
        <div
          className={`flex aspect-video items-center justify-center bg-[var(--surface-video)] ${className || ""}`}
        >
          <span className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--ink-muted)] border-t-transparent" />
        </div>
      );
    }
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={playUrl} alt={alt} className={className} />;
  }

  return (
    <div
      className={`relative overflow-hidden bg-[var(--surface-video)] ${className || ""}`}
    >
      {playUrl && ready ? (
        <video
          key={playUrl}
          className="aspect-video w-full"
          src={playUrl}
          poster={posterUrl || undefined}
          controls
          playsInline
          preload="metadata"
        />
      ) : (
        <div className="flex aspect-video flex-col items-center justify-center gap-2">
          {posterUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={posterUrl}
              alt=""
              className="absolute inset-0 h-full w-full object-contain opacity-50"
            />
          ) : null}
          {error ? (
            <span className="relative px-4 text-center text-sm text-white/70">
              {error}
            </span>
          ) : (
            <>
              <span className="relative h-7 w-7 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
              <span className="relative text-xs text-white/70">
                Loading clip…
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
