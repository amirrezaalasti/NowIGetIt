const SAMPLE_SRC =
  process.env.NEXT_PUBLIC_SAMPLE_VIDEO_URL || "/samples/cooling-demand.mp4";
const SAMPLE_POSTER =
  process.env.NEXT_PUBLIC_SAMPLE_POSTER_URL || "/samples/cooling-demand.jpg";

/** Public sample explainer shown on the home page (no auth required). */
export function SampleExplainer({ className = "" }: { className?: string }) {
  return (
    <figure className={className}>
      <div className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-video)]">
        <video
          className="aspect-video w-full"
          src={SAMPLE_SRC}
          poster={SAMPLE_POSTER}
          controls
          playsInline
          preload="metadata"
        >
          <a href={SAMPLE_SRC}>Download the sample explainer</a>
        </video>
      </div>
      <figcaption className="mt-3 text-sm text-[var(--ink-muted)]">
        Sample explainer · cooling demand with voiceover
      </figcaption>
    </figure>
  );
}
