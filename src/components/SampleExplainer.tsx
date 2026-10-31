import Link from "next/link";

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
          preload="none"
        >
          <a href={SAMPLE_SRC}>Download the sample explainer</a>
        </video>
      </div>
      <figcaption className="mt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm text-[var(--ink-muted)]">
        <span>Sample explainer · cooling demand with voiceover</span>
        <Link href="/examples" className="text-[var(--accent)] hover:underline">
          More examples, made from a chat →
        </Link>
      </figcaption>
    </figure>
  );
}
