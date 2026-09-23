"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { InteractiveLab } from "@/components/InteractiveLab";
import { PodcastPlayer } from "@/components/PodcastPlayer";
import { QuizRunner } from "@/components/QuizRunner";
import { SegmentedControl } from "@/components/SegmentedControl";
import { checkLabProgressLocally, gradeQuizLocally } from "@/lib/examples/local-grading";
import {
  AUDIENCE_LABEL,
  EXAMPLES,
  sampleUrl,
  type Example,
  type LabExample,
  type PodcastExample,
  type QuizExample,
  type VideoExample,
} from "@/lib/examples/manifest";

type Filter = "all" | Example["kind"];

const FILTERS: { id: Filter; label: string; hint?: string }[] = [
  { id: "all", label: "All" },
  { id: "video", label: "Videos" },
  { id: "clip", label: "GIF clip" },
  { id: "interactive", label: "Lab" },
  { id: "quiz", label: "Quiz" },
  { id: "podcast", label: "Podcast" },
];

const KIND_LABEL: Record<Example["kind"], string> = {
  video: "Explainer video",
  clip: "Looping clip",
  podcast: "Podcast",
  quiz: "Quiz",
  interactive: "Interactive lab",
};

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">{children}</p>
  );
}

function PromptBlock({ prompt }: { prompt: string }) {
  return (
    <blockquote className="mt-4 rounded-xl border-l-2 border-[var(--accent)] bg-[var(--surface-inset)] px-4 py-3 text-sm leading-relaxed text-[var(--ink)]">
      <span className="mr-2 text-[11px] uppercase tracking-[0.12em] text-[var(--ink-muted)]">
        Prompt
      </span>
      {prompt}
    </blockquote>
  );
}

function ToolChips({ tools }: { tools: string[] }) {
  return (
    <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="Connector tools used">
      {tools.map((tool) => (
        <li
          key={tool}
          className="rounded-md border border-[var(--line)] bg-[var(--surface-inset)] px-2 py-0.5 font-mono text-[11px] text-[var(--ink-muted)]"
        >
          {tool}
        </li>
      ))}
    </ul>
  );
}

function Note({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <p className="mt-4 rounded-xl border border-[var(--accent-hot)]/40 bg-[var(--surface-inset)] px-4 py-3 text-xs leading-relaxed text-[var(--ink-muted)]">
      <span className="font-semibold text-[var(--accent-hot)]">Note.</span> {text}
    </p>
  );
}

function CardHeader({ item, meta }: { item: Example; meta: string }) {
  return (
    <>
      <Eyebrow>
        {KIND_LABEL[item.kind]} · {meta} · {AUDIENCE_LABEL[item.audience]}
      </Eyebrow>
      <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl tracking-tight text-[var(--ink)]">
        {item.title}
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">{item.tagline}</p>
    </>
  );
}

/** A GIF is either the whole clip or one scene out of several; say which. */
function gifLabel(item: VideoExample): string {
  if (!item.gifScene) return "Open the GIF";
  const scene = item.scenes.find((s) => s.id === item.gifScene);
  return scene ? `Open the GIF · ${scene.title}` : "Open the GIF excerpt";
}

function VideoCard({ item }: { item: VideoExample }) {
  const isClip = item.kind === "clip";
  const meta = `${formatDuration(item.durationSeconds)}${
    item.narrated ? " · narrated" : " · silent"
  }${item.subtitles ? " · subtitles" : ""}`;
  return (
    <article
      id={item.slug}
      className="flex flex-col overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)]"
    >
      <div className="bg-[var(--surface-video)]">
        <video
          className="aspect-video w-full"
          src={sampleUrl(item.video)}
          poster={sampleUrl(item.poster)}
          controls={!isClip}
          autoPlay={isClip}
          loop={isClip}
          muted={isClip}
          playsInline
          preload="metadata"
          ref={(el) => {
            // React does not serialize `muted`; set it so autoplay is allowed.
            if (el && isClip) el.muted = true;
          }}
        >
          <a href={sampleUrl(item.video)}>Download the video</a>
        </video>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <CardHeader item={item} meta={meta} />
        <PromptBlock prompt={item.prompt} />
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-[var(--accent)]">
            Storyboard · {item.scenes.length} {item.scenes.length === 1 ? "scene" : "scenes"}
          </summary>
          <ol className="mt-3 list-decimal space-y-2 pl-5 text-[var(--ink-muted)]">
            {item.scenes.map((scene) => (
              <li key={scene.id} className="leading-relaxed">
                <span className="font-medium text-[var(--ink)]">{scene.title}.</span>{" "}
                {scene.narration}
              </li>
            ))}
          </ol>
        </details>
        {item.gif ? (
          <a
            href={sampleUrl(item.gif)}
            className="mt-4 inline-flex self-start rounded-full border border-[var(--line)] px-4 py-1.5 text-sm text-[var(--ink)] transition hover:border-[var(--accent)]"
          >
            {gifLabel(item)}
          </a>
        ) : null}
        <Note text={item.note} />
        <ToolChips tools={item.tools} />
      </div>
    </article>
  );
}

function LabCard({ item }: { item: LabExample }) {
  return (
    <article
      id={item.slug}
      className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 sm:p-6"
    >
      <CardHeader item={item} meta={`${item.lesson.phases.length} phases`} />
      <PromptBlock prompt={item.prompt} />
      <div className="mt-6">
        <InteractiveLab
          itemId={item.slug}
          lesson={item.lesson}
          checkProgress={async (body, baseline) => checkLabProgressLocally(item.lesson, body, baseline)}
        />
      </div>
      <Note text={item.note} />
      <ToolChips tools={item.tools} />
    </article>
  );
}

function QuizCard({ item }: { item: QuizExample }) {
  return (
    <article
      id={item.slug}
      className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 sm:p-6"
    >
      <CardHeader item={item} meta={`${item.paper.questions.length} questions`} />
      <PromptBlock prompt={item.prompt} />
      <div className="mt-6">
        <QuizRunner
          itemId={item.slug}
          paper={item.paper}
          grade={async (answers) => gradeQuizLocally(item.paper, answers)}
        />
      </div>
      <Note text={item.note} />
      <ToolChips tools={item.tools} />
    </article>
  );
}

function PodcastCard({ item }: { item: PodcastExample }) {
  return (
    <article
      id={item.slug}
      className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 sm:p-6"
    >
      <CardHeader item={item} meta={formatDuration(item.durationSeconds)} />
      <PromptBlock prompt={item.prompt} />
      <div className="mt-6">
        <PodcastPlayer
          title={item.script.title}
          audioUrl={item.audio ? sampleUrl(item.audio) : null}
          script={item.script}
          takeaways={item.takeaways}
          rawAudioSrc
        />
      </div>
      <Note text={item.note} />
      <ToolChips tools={item.tools} />
    </article>
  );
}

function HowItWasMade() {
  const steps = [
    "The chat model read the ScenePlan schema (video_planning_spec) and wrote each storyboard as JSON: title, palette, recurring visual elements, and per-scene beats that pair a visual action with a spoken line. It saved the plan with create_video.",
    "It set narration, burned-in subtitles, and a narrator voice with update_video_options. The server recorded the voiceover first, so every scene came back with the exact time window for each beat.",
    "For every scene it asked for the Manim rules (video_codegen_spec), wrote a complete Manim Community Scene, and saved it with submit_scene_code. Each submit returned a last-frame preview and a layout check; a few scenes were resubmitted after that check.",
    "render_video rendered the clips, mixed the narration, burned the subtitles, and stitched the final video. The clip preset also exported a looping GIF.",
    "The lab and the quiz came straight from create_interactive and create_quiz; on this page they are graded in the browser with the same rules the Learn API uses. The podcast is the create_podcast pipeline: a teaching plan, a two-voice script, one recording per line, stitched with chapter markers.",
  ];
  return (
    <section
      id="how"
      className="rounded-2xl border border-[var(--line)] bg-[var(--surface-panel)] p-5 sm:p-6"
    >
      <Eyebrow>How these were made</Eyebrow>
      <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl tracking-tight text-[var(--ink)]">
        A chat model drove the connector end to end
      </h2>
      <ol className="mt-4 list-decimal space-y-3 pl-5 text-sm leading-relaxed text-[var(--ink-muted)]">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          href="/"
          className="rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110"
        >
          Make your own
        </Link>
        <Link
          href="/connect"
          className="rounded-full border border-[var(--line)] px-6 py-2.5 text-sm text-[var(--ink)] transition hover:border-[var(--accent)]"
        >
          Use it from ChatGPT, Claude, or Cursor
        </Link>
      </div>
    </section>
  );
}

export function ExamplesGallery() {
  const [filter, setFilter] = useState<Filter>("all");

  const visible = useMemo(
    () => (filter === "all" ? EXAMPLES : EXAMPLES.filter((item) => item.kind === filter)),
    [filter],
  );
  const available = useMemo(() => new Set(EXAMPLES.map((item) => item.kind)), []);
  const filters = FILTERS.filter((f) => f.id === "all" || available.has(f.id));

  const videos = visible.filter(
    (item): item is VideoExample => item.kind === "video" || item.kind === "clip",
  );
  const rest = visible.filter((item) => item.kind !== "video" && item.kind !== "clip");

  return (
    <section className="relative mx-auto w-full max-w-6xl px-6 pb-28 pt-8">
      <div className="max-w-3xl animate-rise">
        <Eyebrow>Examples</Eyebrow>
        <h1 className="mt-1 font-[family-name:var(--font-display)] text-4xl tracking-tight text-[var(--ink)] sm:text-5xl">
          Made from a chat, start to finish
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[var(--ink-muted)]">
          Everything below was generated through the Now I Get It connector by an AI model in one
          sitting: the storyboards, the Manim code for every scene, the narration and subtitles, the
          quiz, and the lab. Play them here, open the prompts to see what was asked, then make your
          own.{" "}
          <a href="#how" className="text-[var(--accent)] hover:underline">
            How it works
          </a>
          .
        </p>
      </div>

      <div className="mt-8 animate-rise-delay">
        <SegmentedControl<Filter>
          label="Show"
          value={filter}
          options={filters}
          onChange={setFilter}
        />
      </div>

      {videos.length > 0 ? (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {videos.map((item) => (
            <VideoCard key={item.slug} item={item} />
          ))}
        </div>
      ) : null}

      {rest.length > 0 ? (
        <div className="mt-6 space-y-6">
          {rest.map((item) => {
            if (item.kind === "interactive") return <LabCard key={item.slug} item={item} />;
            if (item.kind === "quiz") return <QuizCard key={item.slug} item={item} />;
            if (item.kind === "podcast") return <PodcastCard key={item.slug} item={item} />;
            return null;
          })}
        </div>
      ) : null}

      {visible.length === 0 ? (
        <p className="mt-10 text-sm text-[var(--ink-muted)]">Nothing in this category yet.</p>
      ) : null}

      <div className="mt-10">
        <HowItWasMade />
      </div>
    </section>
  );
}
