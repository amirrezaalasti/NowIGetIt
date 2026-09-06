"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { InteractiveLab } from "@/components/InteractiveLab";
import { PodcastPlayer } from "@/components/PodcastPlayer";
import { QuizRunner } from "@/components/QuizRunner";
import { SegmentedControl } from "@/components/SegmentedControl";
import {
  SourceAttachments,
  readySourceIds,
  type AttachedSource,
} from "@/components/SourceAttachments";
import {
  ensureApiToken,
  fetchHealth,
  fetchLearnItem,
  streamLearnGenerate,
  type Audience,
  type InteractiveLesson,
  type LanguageOption,
  type LearnKind,
  type LengthPreset,
  type PipelineEvent,
  type PodcastScript,
  type QuizPaper,
  type TtsVoiceOption,
} from "@/lib/api";

const DEFAULT_TTS_VOICES: TtsVoiceOption[] = [
  { id: "Kore", gender: "Female", label: "Kore · Female" },
  { id: "Puck", gender: "Male", label: "Puck · Male" },
  { id: "Aoede", gender: "Female", label: "Aoede · Female" },
  { id: "Charon", gender: "Male", label: "Charon · Male" },
];

const DEFAULT_LANGUAGES: LanguageOption[] = [
  { id: "en", label: "English", native_label: "English" },
  { id: "es", label: "Spanish", native_label: "Español" },
  { id: "fr", label: "French", native_label: "Français" },
  { id: "de", label: "German", native_label: "Deutsch" },
  { id: "fa", label: "Persian", native_label: "فارسی" },
];

const EXAMPLES: Record<LearnKind, string[]> = {
  podcast: [
    "A 8-minute podcast on why gradient descent walks downhill",
    "Explain compound interest as a conversation for high schoolers",
  ],
  quiz: [
    "Quiz me on the unit circle until sine and cosine click",
    "8 questions on Bayes' theorem with a medical-test example",
  ],
  interactive: [
    "Let me play with projectile motion until I find the 45° rule",
    "An interactive lab for y = mx + b where I have to hit a target slope",
  ],
};

const AUDIENCE_OPTIONS: { id: Audience; label: string }[] = [
  { id: "general", label: "General" },
  { id: "hs", label: "High school" },
  { id: "undergrad", label: "Undergrad" },
];

export function LearnHub() {
  const { status: authStatus } = useSession();
  const searchParams = useSearchParams();
  const signedIn = authStatus === "authenticated";
  const urlId = searchParams.get("id");
  const urlKind = searchParams.get("kind") as LearnKind | null;

  const [kind, setKind] = useState<LearnKind>(urlKind || "interactive");
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<AttachedSource[]>([]);
  const [audience, setAudience] = useState<Audience>("general");
  const [language, setLanguage] = useState("en");
  const [lengthPreset, setLengthPreset] = useState<LengthPreset>("standard");
  const [ttsVoice, setTtsVoice] = useState("Kore");
  const [partnerVoice, setPartnerVoice] = useState("Puck");
  const [style, setStyle] = useState<"dialogue" | "solo">("dialogue");
  const [questionCount, setQuestionCount] = useState(8);
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard" | "mixed">(
    "mixed",
  );
  const [voices, setVoices] = useState<TtsVoiceOption[]>(DEFAULT_TTS_VOICES);
  const [languages, setLanguages] = useState<LanguageOption[]>(DEFAULT_LANGUAGES);
  const [running, setRunning] = useState(false);
  const [liveMessage, setLiveMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [itemId, setItemId] = useState<string | null>(urlId);
  const [item, setItem] = useState<Awaited<ReturnType<typeof fetchLearnItem>> | null>(
    null,
  );
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        if (h.tts_voices?.length) setVoices(h.tts_voices);
        if (h.languages?.length) setLanguages(h.languages);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!urlId || !signedIn) return;
    void ensureApiToken()
      .then(() => fetchLearnItem(urlId))
      .then((detail) => {
        setItem(detail);
        setItemId(detail.id);
        if (detail.kind === "podcast" || detail.kind === "quiz" || detail.kind === "interactive") {
          setKind(detail.kind);
        }
      })
      .catch((err) => setError((err as Error).message));
  }, [urlId, signedIn]);

  async function onGenerate() {
    const sourceIds = readySourceIds(attachments);
    if ((!prompt.trim() && sourceIds.length === 0) || running) return;
    if (attachments.some((item) => item.status === "uploading")) return;
    setRunning(true);
    setError(null);
    setItem(null);
    setLiveMessage("Starting…");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let generatedId: string | null = itemId;
    let ready = false;
    try {
      await ensureApiToken();
      await streamLearnGenerate(
        {
          kind,
          prompt: prompt.trim(),
          source_doc_ids: sourceIds,
          audience,
          language,
          length_preset: lengthPreset,
          tts_voice: ttsVoice,
          partner_voice: partnerVoice,
          style,
          question_count: questionCount,
          difficulty,
        },
        (event: PipelineEvent) => {
          if (event.message) setLiveMessage(event.message);
          const id = event.data && typeof event.data.id === "string" ? event.data.id : null;
          if (id) {
            generatedId = id;
            setItemId(id);
          }
          if (event.type === "result" && event.data && "payload" in event.data) {
            ready = true;
            setItem(event.data as Awaited<ReturnType<typeof fetchLearnItem>>);
          }
          if (event.type === "error") {
            setError(event.message || "Generation failed");
          }
        },
        controller.signal,
      );
      if (generatedId && ready) {
        const detail = await fetchLearnItem(generatedId);
        setItem(detail);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  if (authStatus === "loading") {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16 text-sm text-[var(--ink-muted)]">
        Checking session…
      </section>
    );
  }

  if (!signedIn) {
    return (
      <section className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 py-16 text-center">
        <h1 className="font-[family-name:var(--font-display)] text-4xl tracking-tight">
          Learn it until it clicks
        </h1>
        <p className="mt-4 text-[var(--ink-muted)]">
          Podcasts, quizzes, and interactive labs — same teaching engine as the videos.
        </p>
        <Link
          href="/login?callbackUrl=/learn"
          className="mt-8 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3 font-semibold text-[var(--on-accent)]"
        >
          Continue with Google
        </Link>
      </section>
    );
  }

  const payload = item?.payload || {};
  const podcastScript = payload.script as PodcastScript | undefined;
  const quizPaper = payload.paper as QuizPaper | undefined;
  const lesson = payload.lesson as InteractiveLesson | undefined;

  return (
    <section className="relative mx-auto w-full max-w-6xl px-6 pb-28 pt-8">
      <div className="max-w-3xl animate-rise">
        <p className="text-[11px] uppercase tracking-[0.16em] text-[var(--ink-muted)]">
          Learn
        </p>
        <h1 className="mt-1 font-[family-name:var(--font-display)] text-4xl tracking-tight sm:text-5xl">
          Play the idea until it sticks
        </h1>
        <p className="mt-3 max-w-xl text-sm text-[var(--ink-muted)]">
          Hear it as a podcast, check it with a quiz, or drive a live picture
          through learning phases — explore, predict, challenge. Attach notes
          or a deck if you want it grounded in your material.
        </p>
      </div>

      <div className="mt-8 animate-rise-delay">
        <SegmentedControl
          label="Mode"
          value={kind}
          options={[
            { id: "interactive", label: "Play", hint: "Interactive lab" },
            { id: "podcast", label: "Podcast" },
            { id: "quiz", label: "Quiz" },
          ]}
          onChange={setKind}
          disabled={running}
        />
      </div>

      <div className="mt-6 max-w-3xl rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={
            kind === "interactive"
              ? "What should I be able to change — and what should click?"
              : kind === "podcast"
                ? "What should the episode make obvious?"
                : "What should this quiz prove I understand?"
          }
          rows={4}
          disabled={running}
          className="block w-full resize-none bg-transparent text-base outline-none disabled:opacity-60"
        />
        <SourceAttachments
          items={attachments}
          onChange={setAttachments}
          disabled={running}
        />
        <div className="mt-4 flex flex-wrap gap-4">
          <SegmentedControl
            label="Audience"
            value={audience}
            options={AUDIENCE_OPTIONS}
            onChange={setAudience}
            disabled={running}
          />
          <label className="flex min-w-[10rem] flex-col gap-1.5">
            <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
              Language
            </span>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={running}
              className="rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm"
            >
              {languages.map((lang) => (
                <option key={lang.id} value={lang.id}>
                  {lang.label}
                </option>
              ))}
            </select>
          </label>
          {kind === "podcast" ? (
            <>
              <SegmentedControl
                label="Length"
                value={lengthPreset}
                options={[
                  { id: "short", label: "~4 min" },
                  { id: "standard", label: "~8 min" },
                  { id: "deep", label: "~15 min" },
                ]}
                onChange={setLengthPreset}
                disabled={running}
              />
              <SegmentedControl
                label="Style"
                value={style}
                options={[
                  { id: "dialogue", label: "Two voices" },
                  { id: "solo", label: "Solo" },
                ]}
                onChange={setStyle}
                disabled={running}
              />
              <label className="flex min-w-[10rem] flex-col gap-1.5">
                <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Guide voice
                </span>
                <select
                  value={ttsVoice}
                  onChange={(e) => setTtsVoice(e.target.value)}
                  className="rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm"
                >
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : null}
          {kind === "quiz" ? (
            <SegmentedControl
              label="Difficulty"
              value={difficulty}
              options={[
                { id: "mixed", label: "Mixed" },
                { id: "easy", label: "Easy" },
                { id: "medium", label: "Medium" },
                { id: "hard", label: "Hard" },
              ]}
              onChange={setDifficulty}
              disabled={running}
            />
          ) : null}
        </div>
        {kind === "quiz" ? (
          <label className="mt-4 block text-sm text-[var(--ink-muted)]">
            Questions
            <input
              type="range"
              min={3}
              max={15}
              value={questionCount}
              onChange={(e) => setQuestionCount(Number(e.target.value))}
              className="ml-3 align-middle accent-[var(--accent)]"
            />
            <span className="ml-2 font-mono text-[var(--ink)]">{questionCount}</span>
          </label>
        ) : null}
        {kind === "podcast" && style === "dialogue" ? (
          <label className="mt-4 flex max-w-xs flex-col gap-1.5">
            <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
              Host voice
            </span>
            <select
              value={partnerVoice}
              onChange={(e) => setPartnerVoice(e.target.value)}
              className="rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm"
            >
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <div className="mt-5">
          <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
            Try an example
          </p>
          <ul className="space-y-1">
            {EXAMPLES[kind].map((ex) => (
              <li key={ex}>
                <button
                  type="button"
                  onClick={() => setPrompt(ex)}
                  className="text-left text-sm text-[var(--ink-muted)] hover:text-[var(--ink)]"
                >
                  {ex}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-4">
          <button
            type="button"
            disabled={
              running ||
              attachments.some((item) => item.status === "uploading") ||
              (!prompt.trim() && readySourceIds(attachments).length === 0)
            }
            onClick={() => void onGenerate()}
            className="rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] disabled:opacity-40"
          >
            {running
              ? "Building…"
              : kind === "interactive"
                ? "Build the lab"
                : kind === "podcast"
                  ? "Record episode"
                  : "Write quiz"}
          </button>
          {running ? (
            <p className="text-sm text-[var(--ink-muted)]">{liveMessage}</p>
          ) : null}
        </div>
        {error ? (
          <p className="mt-3 text-sm text-[var(--danger-ink)]">{error}</p>
        ) : null}
      </div>

      {item && podcastScript && item.kind === "podcast" ? (
        <div className="mt-12">
          <PodcastPlayer
            title={item.title}
            audioUrl={
              (payload.audio_url as string | undefined) || item.urls?.audio
            }
            script={podcastScript}
            takeaways={(payload.takeaways as string[]) || podcastScript.takeaways}
            audioSkipped={Boolean(payload.audio_skipped)}
          />
        </div>
      ) : null}

      {item && quizPaper && item.kind === "quiz" ? (
        <div className="mt-12">
          <QuizRunner itemId={item.id} paper={quizPaper} />
        </div>
      ) : null}

      {item && lesson && item.kind === "interactive" ? (
        <div className="mt-12">
          <InteractiveLab
            itemId={item.id}
            lesson={lesson}
            initialProgress={item.progress}
          />
        </div>
      ) : null}
    </section>
  );
}
