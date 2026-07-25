"use client";

import { useEffect, useState } from "react";
import { getApiToken, apiBasePath } from "@/lib/api";

type Props = {
  src: string | null | undefined;
  poster?: string | null;
  kind?: "video" | "image";
  className?: string;
  alt?: string;
};

/**
 * Load protected job media via Authorization header into a blob URL.
 * Avoids <video src> hanging on cross-origin query-token requests while
 * the API is busy rendering the next scene.
 */
export function AuthMedia({
  src,
  poster,
  kind = "video",
  className,
  alt = "",
}: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [posterUrl, setPosterUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    async function load() {
      if (!src) {
        setBlobUrl(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const token = await getApiToken();
        const url = src.startsWith("http") ? src : `${apiBasePath()}${src}`;
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        if (!res.ok) throw new Error(`Media ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || "Failed to load media");
          setBlobUrl(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    async function loadPoster() {
      if (!poster) {
        setPosterUrl(null);
        return;
      }
      try {
        const token = await getApiToken();
        const url = poster.startsWith("http")
          ? poster
          : `${apiBasePath()}${poster}`;
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        if (!res.ok) return;
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setPosterUrl(objectUrl);
      } catch {
        /* poster is optional */
      }
    }

    void loadPoster();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
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
    if (!blobUrl) {
      return (
        <div
          className={`flex aspect-video items-center justify-center bg-[var(--surface-video)] ${className || ""}`}
        >
          <span className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--ink-muted)] border-t-transparent" />
        </div>
      );
    }
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={blobUrl} alt={alt} className={className} />;
  }

  return (
    <div className={`relative overflow-hidden bg-[var(--surface-video)] ${className || ""}`}>
      {blobUrl ? (
        <video
          key={blobUrl}
          className="aspect-video w-full"
          src={blobUrl}
          poster={posterUrl || undefined}
          controls
          playsInline
          preload="auto"
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
          {loading ? (
            <>
              <span className="relative h-7 w-7 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
              <span className="relative text-xs text-white/70">Loading clip…</span>
            </>
          ) : (
            <span className="relative px-4 text-center text-sm text-white/70">
              {error || "No video for this scene"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
