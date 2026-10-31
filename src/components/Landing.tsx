"use client";

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import { BrandMark, BrandWordmark, Sparkle } from "@/components/BrandLogo";
import { SampleExplainer } from "@/components/SampleExplainer";
import { EXAMPLES, sampleUrl, type VideoExample } from "@/lib/examples/manifest";

const CLIPS = EXAMPLES.filter((e): e is VideoExample => e.kind === "clip");
const HERO_CLIP = CLIPS.find((c) => c.slug === "sine-is-a-height") ?? CLIPS[0];

const MODES: { title: string; body: string; href: string; icon: ReactNode }[] = [
  {
    title: "Explainer video",
    body: "Manim animation, cinematic shots, narration, and subtitles, from a 12-second GIF to a 3-minute lesson.",
    href: "/examples#gradient-descent",
    icon: <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5zM10 9v6l5-3z" />,
  },
  {
    title: "Podcast",
    body: "A two-voice conversation with chapters and a transcript, for when your eyes are busy.",
    href: "/examples#bayes-base-rates",
    icon: <path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v3M9 20h6" />,
  },
  {
    title: "Quiz",
    body: "Questions tied to each teaching step, scored with explanations, so you know it stuck.",
    href: "/examples#unit-circle-quiz",
    icon: <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01M4 12a8 8 0 1 0 16 0 8 8 0 0 0-16 0z" />,
  },
  {
    title: "Interactive lab",
    body: "Drag the sliders yourself: predict, test, and find the reason, phase by phase.",
    href: "/examples#projectile-angle-explorer",
    icon: <path d="M5 8h8M17 8h2M5 16h2M11 16h8M15 6v4M9 14v4" />,
  },
  {
    title: "Understand documents",
    body: "Drop a PDF, deck, or doc. Click any block for explanations, formulas, figures, or a quiz.",
    href: "/understand",
    icon: <path d="M7 3.5h7l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5zM14 3.5V8h4M9 12.5h6M9 16h4" />,
  },
  {
    title: "Paper to YouTube",
    body: "Point it at a paper and get a full explainer, published to your channel when it's done.",
    href: "/pipeline",
    icon: <path d="M3.5 12c0-3 .3-4.6.9-5.3.6-.7 2.6-1.2 7.6-1.2s7 .5 7.6 1.2c.6.7.9 2.3.9 5.3s-.3 4.6-.9 5.3c-.6.7-2.6 1.2-7.6 1.2s-7-.5-7.6-1.2c-.6-.7-.9-2.3-.9-5.3zM10.5 9.5v5l4-2.5z" />,
  },
];

const STEPS: { title: string; body: string }[] = [
  {
    title: "Ask, or attach",
    body: "Describe the idea, or drop lecture notes, slides, or a paper and leave the prompt blank.",
  },
  {
    title: "Approve the storyboard",
    body: "Scenes and narration arrive first. Reorder, rewrite, pick a voice. Nothing renders until you say so.",
  },
  {
    title: "Animate and check",
    body: "Each scene is written as Manim code, rendered, and reviewed frame by frame by a vision model.",
  },
  {
    title: "Voice, render, retouch",
    body: "Narration and subtitles are timed to the visuals. Pause on any frame, leave a note, and it fixes that scene.",
  },
];

/** Muted loop that only plays while on screen and never for reduced-motion users. */
function LoopingClip({ src, poster, label }: { src: string; poster: string; label: string }) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          video.play().catch(() => {});
        } else {
          video.pause();
        }
      },
      { threshold: 0.25 },
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, []);

  return (
    <video
      ref={ref}
      className="aspect-video w-full bg-[var(--surface-video)] object-cover"
      src={src}
      poster={poster}
      muted
      loop
      playsInline
      preload="none"
      aria-label={label}
    />
  );
}

function SectionHeading({ eyebrow, title, children }: { eyebrow: string; title: ReactNode; children?: ReactNode }) {
  return (
    <div className="max-w-2xl">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">{eyebrow}</p>
      <h2 className="mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold leading-[1.1] tracking-[-0.03em] text-[var(--ink)] sm:text-[2.6rem]">
        {title}
      </h2>
      {children && <p className="mt-4 text-base leading-relaxed text-[var(--ink-muted)] sm:text-lg">{children}</p>}
    </div>
  );
}

export function Landing() {
  return (
    <div className="relative w-full">
      {/* Hero */}
      <section className="mx-auto grid w-full max-w-6xl items-center gap-12 px-4 pb-16 pt-10 sm:px-6 sm:pt-24 lg:grid-cols-[1.05fr_1fr] lg:gap-16 lg:pb-24 lg:pt-28">
        <div className="animate-rise">
          <p className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3.5 py-1.5 text-[13px] text-[var(--ink-muted)]">
            <Sparkle className="h-3.5 w-3.5 text-[var(--mascot-spark)]" />
            Videos · podcasts · quizzes · interactive labs
          </p>
          <h1 className="mt-6 font-[family-name:var(--font-display)] text-[2.75rem] font-semibold leading-[1.02] tracking-[-0.045em] text-[var(--ink)] sm:text-6xl lg:text-[4.4rem]">
            Explain anything until it{" "}
            <span className="landing-clicks relative inline-block italic text-[var(--accent)]">clicks.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-[var(--ink-muted)]">
            Type a concept or drop a PDF. Now I Get It plans a storyboard, animates it, checks every
            frame with a vision model, and narrates it. You approve the plan before anything renders.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-7 py-3.5 text-base font-semibold text-[var(--on-accent)] shadow-[0_10px_30px_-10px_var(--accent)] transition hover:-translate-y-0.5 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-deep)]"
            >
              Start with Google
              <span aria-hidden>→</span>
            </Link>
            <Link
              href="/examples"
              className="inline-flex items-center rounded-full border border-[var(--line)] px-6 py-3.5 text-base text-[var(--ink)] transition hover:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            >
              See what it makes
            </Link>
          </div>
          <p className="mt-6 text-sm text-[var(--ink-muted)]">
            Also works inside ChatGPT, Claude, and Cursor.{" "}
            <Link href="/connect" className="text-[var(--accent)] underline-offset-4 hover:underline">
              Connect it →
            </Link>
          </p>
        </div>

        <div className="animate-rise-delay relative mx-auto w-full max-w-lg lg:max-w-none">
          <BrandMark
            size={150}
            animated
            className="absolute -right-2 -top-20 z-10 hidden sm:block lg:-right-8 lg:-top-24"
          />
          <div className="landing-demo overflow-hidden rounded-3xl border border-[var(--line)] bg-[var(--bg-mid)] shadow-[0_40px_80px_-40px_rgba(0,0,0,0.6)]">
            <div className="flex items-center gap-2 border-b border-[var(--line)] px-4 py-3">
              <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
              <span className="h-2.5 w-2.5 rounded-full bg-[var(--line)]" />
              <span className="ml-2 text-xs text-[var(--ink-muted)]">New explainer</span>
            </div>
            <div className="px-5 pb-5 pt-4">
              <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">Prompt</p>
              <p className="mt-2 rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] px-4 py-3 text-[15px] leading-relaxed text-[var(--ink)]">
                {HERO_CLIP.prompt}
                <span className="landing-caret" aria-hidden />
              </p>
              <ol className="mt-4 flex flex-wrap gap-1.5 text-xs text-[var(--ink-muted)]">
                {["Storyboard", "Manim", "Vision QA", "Render"].map((step) => (
                  <li
                    key={step}
                    className="inline-flex items-center gap-1.5 rounded-full border border-[var(--line)] px-2.5 py-1"
                  >
                    <svg viewBox="0 0 16 16" className="h-3 w-3 text-[var(--accent)]" aria-hidden>
                      <path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {step}
                  </li>
                ))}
              </ol>
              <div className="mt-4 overflow-hidden rounded-xl border border-[var(--line)]">
                <LoopingClip
                  src={sampleUrl(HERO_CLIP.video)}
                  poster={sampleUrl(HERO_CLIP.poster)}
                  label={`${HERO_CLIP.title}, generated from the prompt above`}
                />
              </div>
              <p className="mt-3 text-xs text-[var(--ink-muted)]">
                Real output · {HERO_CLIP.title} · {HERO_CLIP.durationSeconds}s loop
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Showreel */}
      <section className="border-y border-[var(--line)] bg-[var(--surface)] py-16 sm:py-20">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
          <SectionHeading eyebrow="Showreel" title="Every frame here was written by a model.">
            Each clip below came from a single chat: storyboard, Manim code, and render. Nothing was
            hand-animated.
          </SectionHeading>
          <ul className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {CLIPS.map((clip) => (
              <li key={clip.slug}>
                <Link
                  href={`/examples#${clip.slug}`}
                  className="group block overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--bg-deep)] transition hover:-translate-y-1 hover:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
                >
                  <LoopingClip src={sampleUrl(clip.video)} poster={sampleUrl(clip.poster)} label={clip.title} />
                  <div className="px-4 py-3.5">
                    <p className="text-[15px] font-semibold leading-snug text-[var(--ink)]">{clip.title}</p>
                    <p className="mt-1 text-xs text-[var(--ink-muted)]">
                      {clip.durationSeconds}s loop ·{" "}
                      <span className="text-[var(--accent)] transition group-hover:underline">See the prompt</span>
                    </p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Modes */}
      <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <SectionHeading eyebrow="One idea, many doors" title="Learn it the way it sticks for you.">
          The same teaching plan becomes whichever format clicks: watch it, hear it, test yourself, or
          take it apart with your own hands.
        </SectionHeading>
        <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {MODES.map((mode) => (
            <li key={mode.title}>
              <Link
                href={mode.href}
                className="group flex h-full flex-col rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 transition hover:border-[var(--accent)] hover:bg-[var(--surface-inset)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
              >
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--glow)] text-[var(--accent)]">
                  <svg
                    viewBox="0 0 24 24"
                    className="h-6 w-6"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden
                  >
                    {mode.icon}
                  </svg>
                </span>
                <span className="mt-5 text-lg font-semibold text-[var(--ink)]">{mode.title}</span>
                <span className="mt-2 text-[15px] leading-relaxed text-[var(--ink-muted)]">{mode.body}</span>
                <span className="mt-auto pt-5 text-sm text-[var(--accent)] opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100">
                  Take a look →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* How it works */}
      <section className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6 sm:pb-24">
        <SectionHeading eyebrow="How it works" title={<>You stay the director.</>}>
          An AI that animates is easy to demo and hard to trust. So every step is visible, and the
          expensive part waits for your go-ahead.
        </SectionHeading>
        <ol className="mt-12 grid gap-8 md:grid-cols-4 md:gap-6">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--accent)] font-[family-name:var(--font-display)] text-base font-semibold text-[var(--accent)]">
                  {i + 1}
                </span>
                {i < STEPS.length - 1 && (
                  <span className="hidden h-px flex-1 bg-gradient-to-r from-[var(--accent)] to-transparent opacity-50 md:block" aria-hidden />
                )}
              </div>
              <h3 className="mt-4 text-lg font-semibold text-[var(--ink)]">{step.title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-[var(--ink-muted)]">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Long form */}
      <section className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6 sm:pb-24">
        <div className="grid items-center gap-10 rounded-3xl border border-[var(--line)] bg-[var(--surface)] p-6 sm:p-10 lg:grid-cols-[0.8fr_1.2fr]">
          <SectionHeading eyebrow="It scales" title="From a 12-second loop to a full lecture.">
            This 27-minute narrated walkthrough of building cooling demand was produced with the
            same pipeline, scene by scene.
          </SectionHeading>
          <SampleExplainer />
        </div>
      </section>

      {/* Connector */}
      <section className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6 sm:pb-24">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <SectionHeading eyebrow="In your chat" title="Already talking to ChatGPT, Claude, or Cursor?">
            Add Now I Get It as a connector. Your assistant writes the storyboard and the Manim, we
            render it, and the video lands in your Library. No API key to paste.
          </SectionHeading>
          <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface-inset)] p-5 font-mono text-[13px] leading-relaxed text-[var(--ink)]">
            <p className="text-[var(--ink-muted)]">you →</p>
            <p className="mt-1">
              Make a 60-second video that explains gradient descent on a parabola for undergrads. Show
              me the storyboard first. Spoken audio, burned-in subtitles.
            </p>
            <p className="mt-4 text-[var(--ink-muted)]">assistant →</p>
            <p className="mt-1">
              <span className="text-[var(--accent)]">create_video</span> ·{" "}
              <span className="text-[var(--accent)]">submit_scene_code</span> ×7 ·{" "}
              <span className="text-[var(--accent)]">render_video</span>
            </p>
            <p className="mt-1 text-[var(--ink-muted)]">✓ Gradient Descent: Walking Downhill (1:42), saved to Library</p>
            <Link
              href="/connect"
              className="mt-5 inline-flex font-sans text-sm text-[var(--accent)] underline-offset-4 hover:underline"
            >
              Set up the connector →
            </Link>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto w-full max-w-6xl px-4 pb-20 sm:px-6 sm:pb-28">
        <div className="landing-cta relative overflow-hidden rounded-3xl border border-[var(--line)] px-6 py-14 text-center sm:px-12 sm:py-16">
          <BrandMark size={112} animated className="mx-auto" />
          <h2 className="mx-auto mt-6 max-w-xl font-[family-name:var(--font-display)] text-3xl font-semibold leading-[1.1] tracking-[-0.03em] text-[var(--ink)] sm:text-[2.6rem]">
            What should finally make sense today?
          </h2>
          <Link
            href="/login"
            className="mt-8 inline-flex items-center gap-2 rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent)] transition hover:-translate-y-0.5 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          >
            Start with Google <span aria-hidden>→</span>
          </Link>
          <p className="mt-4 text-sm text-[var(--ink-muted)]">Your jobs and videos stay private to your account.</p>
        </div>
      </section>

      <footer className="border-t border-[var(--line)]">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-3 px-4 py-6 text-sm text-[var(--ink-muted)] sm:flex-row sm:px-6">
          <BrandWordmark size="sm" className="!text-base" />
          <nav aria-label="Footer" className="flex flex-wrap justify-center gap-x-5 gap-y-1">
            <Link href="/examples" className="hover:text-[var(--ink)]">Examples</Link>
            <Link href="/learn" className="hover:text-[var(--ink)]">Learn</Link>
            <Link href="/understand" className="hover:text-[var(--ink)]">Understand</Link>
            <Link href="/connect" className="hover:text-[var(--ink)]">Connect</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
