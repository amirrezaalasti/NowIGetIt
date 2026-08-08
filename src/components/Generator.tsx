"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { AuthMedia } from "@/components/AuthMedia";
import { SegmentedControl } from "@/components/SegmentedControl";
import {
  ensureApiToken,
  assetUrl,
  fetchHealth,
  fetchJob,
  getStoredActiveJobId,
  setStoredActiveJobId,
  streamContinue,
  streamGenerate,
  cancelJob,
  streamJobEvents,
  streamRegenerateScene,
  revisePlanWithAI,
  updateJobPlan,
  type Audience,
  type JobDetail,
  type LanguageOption,
  type LengthPreset,
  type ScenePacing,
  type PipelineEvent,
  type ScenePlanDraft,
  type SceneSectionDraft,
  type TtsVoiceOption,
} from "@/lib/api";

const DEFAULT_TTS_VOICES: TtsVoiceOption[] = [
  { id: "Kore", gender: "Female", label: "Kore · Female" },
  { id: "Aoede", gender: "Female", label: "Aoede · Female" },
  { id: "Zephyr", gender: "Female", label: "Zephyr · Female" },
  { id: "Callirrhoe", gender: "Female", label: "Callirrhoe · Female" },
  { id: "Puck", gender: "Male", label: "Puck · Male" },
  { id: "Charon", gender: "Male", label: "Charon · Male" },
  { id: "Fenrir", gender: "Male", label: "Fenrir · Male" },
  { id: "Orus", gender: "Male", label: "Orus · Male" },
];

const DEFAULT_LANGUAGES: LanguageOption[] = [
  { id: "en", label: "English", native_label: "English" },
  { id: "es", label: "Spanish", native_label: "Español" },
  { id: "fr", label: "French", native_label: "Français" },
  { id: "de", label: "German", native_label: "Deutsch" },
  { id: "fa", label: "Persian", native_label: "فارسی" },
  { id: "ar", label: "Arabic", native_label: "العربية" },
  { id: "zh", label: "Chinese (Simplified)", native_label: "简体中文" },
  { id: "ja", label: "Japanese", native_label: "日本語" },
];

function AutoTextarea({
  value,
  onChange,
  placeholder,
  className,
  minRows = 2,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  minRows?: number;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(el.scrollHeight, minRows * 22)}px`;
  }, [value, minRows]);
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={minRows}
      disabled={disabled}
      className={`block w-full resize-none overflow-hidden bg-transparent outline-none disabled:cursor-not-allowed disabled:opacity-60 ${className || ""}`}
    />
  );
}

type ScenePreview = {
  id: string;
  title: string;
  narration?: string;
  visualDescription?: string;
  beats?: string[];
  visualDevice?: string;
  duration?: number;
  approved?: boolean;
  clarity?: number;
  frameUrl?: string;
  videoUrl?: string;
  status?: string;
};

type FlowMode = "compose" | "storyboard" | "building" | "result";

const EXAMPLES = [
  "Explain gradient descent on a simple parabola",
  "Show why the Pythagorean theorem works visually",
  "Animate how sine and cosine relate on the unit circle",
];

const LENGTH_OPTIONS: { id: LengthPreset; label: string; hint: string }[] = [
  { id: "short", label: "60s", hint: "Quick intuition" },
  { id: "standard", label: "90s", hint: "Balanced" },
  { id: "deep", label: "3 min", hint: "Deep dive" },
];

const SCENE_PACING_OPTIONS: {
  id: ScenePacing;
  label: string;
  hint: string;
}[] = [
  { id: "short", label: "Many short", hint: "More cuts, quicker beats" },
  { id: "balanced", label: "Balanced", hint: "Default scene length" },
  { id: "long", label: "Fewer long", hint: "Deeper scenes, fewer cuts" },
];

const AUDIENCE_OPTIONS: { id: Audience; label: string }[] = [
  { id: "general", label: "General" },
  { id: "hs", label: "High school" },
  { id: "undergrad", label: "Undergrad" },
];

function planFromEvent(data: Record<string, unknown>): ScenePlanDraft {
  const scenes = (data.scenes as Array<Record<string, unknown>>) || [];
  return {
    title: String(data.title || "Untitled"),
    concept_summary: String(data.concept_summary || ""),
    style_notes: String(data.style_notes || ""),
    visual_identity: String(data.visual_identity || ""),
    palette: (data.palette as Record<string, string>) || {},
    scenes: scenes.map((s, i) => ({
      id: String(s.id || s.scene_id || `scene_${i + 1}`),
      title: String(s.title || `Scene ${i + 1}`),
      narration: String(s.narration || ""),
      visual_description: String(s.visual_description || ""),
      animation_beats: Array.isArray(s.animation_beats)
        ? (s.animation_beats as string[])
        : [],
      duration_seconds: Number(s.duration_seconds) || 8,
      camera_notes: String(s.camera_notes || ""),
      visual_device: String(s.visual_device || ""),
      style_tags: Array.isArray(s.style_tags)
        ? (s.style_tags as string[])
        : [],
    })),
  };
}

function scenesFromPlan(plan: ScenePlanDraft): ScenePreview[] {
  return plan.scenes.map((s) => ({
    id: s.id,
    title: s.title,
    narration: s.narration,
    visualDescription: s.visual_description,
    beats: s.animation_beats,
    visualDevice: s.visual_device,
    duration: s.duration_seconds,
    status: "queued",
  }));
}

function sceneStatusTone(status?: string, approved?: boolean) {
  if (
    approved === false ||
    status === "needs work" ||
    status === "render failed" ||
    status === "regenerate failed"
  ) {
    return "text-[var(--accent-hot)]";
  }
  if (approved === true || status === "done" || status === "approved") {
    return "text-[var(--accent)]";
  }
  return "text-[var(--ink-muted)]";
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

function eventStepLabel(event: PipelineEvent): string {
  const step =
    typeof event.data?.step === "string" ? event.data.step : event.type;
  const labels: Record<string, string> = {
    "blueprint.start": "Teaching",
    "blueprint.prepare": "Teaching",
    "blueprint.llm": "Thinking",
    "blueprint.retry": "Retry",
    "blueprint.failed": "Retry",
    "blueprint.done": "Teaching",
    "planning.start": "Plan",
    "planning.prepare": "Plan",
    "planning.llm": "Thinking",
    "planning.validate": "Validate",
    "planning.retry": "Retry",
    "planning.done": "Plan",
    "planning.revise": "Revise",
    "planning.revise_llm": "Thinking",
    "planning.revise_retry": "Retry",
    "planning.revise_done": "Plan",
    "scene.start": "Scene",
    "scene.tts": "Narration",
    "scene.codegen": "Writing code",
    "scene.code_ready": "Code",
    "scene.render": "Render",
    "scene.revise_render": "Fixing",
    "scene.revise_timing": "Timing",
    "scene.revise_clarity": "Clarity",
    status: "Status",
    plan: "Plan",
    plan_ready: "Ready",
    scene_start: "Scene",
    scene_code: "Code",
    scene_render: "Render",
    scene_vlm: "Review",
    scene_revise: "Revise",
    scene_tts: "Narration",
    scene_done: "Done",
    complete: "Complete",
    error: "Error",
    final_debug: "Notes",
  };
  return labels[step] || labels[event.type] || event.type;
}

type CodePreview = {
  sceneId: string;
  revision: number;
  code: string;
  truncated: boolean;
  chars: number;
};

export function Generator() {
  const { status: authStatus } = useSession();
  const searchParams = useSearchParams();
  const [prompt, setPrompt] = useState("");
  const [lengthPreset, setLengthPreset] = useState<LengthPreset>("standard");
  const [scenePacing, setScenePacing] = useState<ScenePacing>("balanced");
  const [audience, setAudience] = useState<Audience>("general");
  const [ttsVoice, setTtsVoice] = useState("Kore");
  const [language, setLanguage] = useState("en");
  const [includeAudio, setIncludeAudio] = useState(true);
  const [includeSubtitles, setIncludeSubtitles] = useState(true);
  const [ttsVoices, setTtsVoices] =
    useState<TtsVoiceOption[]>(DEFAULT_TTS_VOICES);
  const [languages, setLanguages] =
    useState<LanguageOption[]>(DEFAULT_LANGUAGES);
  const [running, setRunning] = useState(false);
  const [awaitingPlan, setAwaitingPlan] = useState(false);
  const [editingPlan, setEditingPlan] = useState<ScenePlanDraft | null>(null);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [planTitle, setPlanTitle] = useState<string | null>(null);
  const [scenes, setScenes] = useState<ScenePreview[]>([]);
  const [finalNotes, setFinalNotes] = useState<string | null>(null);
  const [finalVideoUrl, setFinalVideoUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<string>("Checking API…");
  const [liveMessage, setLiveMessage] = useState<string>("");
  const [regenDirection, setRegenDirection] = useState<Record<string, string>>(
    {},
  );
  // Scene edits run independently of the main pipeline and of each other, so
  // in-flight state is per scene rather than one global flag.
  const [regeneratingSceneIds, setRegeneratingSceneIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [sceneRegenError, setSceneRegenError] = useState<
    Record<string, string>
  >({});
  const [sceneRegenMessage, setSceneRegenMessage] = useState<
    Record<string, string>
  >({});
  // Bumped whenever a scene's video is (re)published so <AuthMedia> is forced
  // to refetch — the published file path never changes on regenerate/retouch.
  const [videoVersion, setVideoVersion] = useState<Record<string, number>>({});
  const [finalVideoVersion, setFinalVideoVersion] = useState(0);

  function bumpVideoVersion(sceneId: string) {
    setVideoVersion((prev) => ({ ...prev, [sceneId]: (prev[sceneId] ?? 0) + 1 }));
  }
  const [promptFocused, setPromptFocused] = useState(false);
  const [revisePrompt, setRevisePrompt] = useState("");
  const [revising, setRevising] = useState(false);
  const [reviseError, setReviseError] = useState<string | null>(null);
  const [reviseElapsed, setReviseElapsed] = useState(0);
  const [reviseSuccessMessage, setReviseSuccessMessage] = useState<
    string | null
  >(null);
  const [logOpen, setLogOpen] = useState(true);
  const [codeOpen, setCodeOpen] = useState(true);
  const [latestCode, setLatestCode] = useState<CodePreview | null>(null);
  const [buildElapsed, setBuildElapsed] = useState(0);
  const [restoring, setRestoring] = useState(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlayingPreview, setIsPlayingPreview] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const reviseAbortRef = useRef<AbortController | null>(null);
  // One abort controller per in-flight scene edit. Kept separate from
  // `abortRef` (the main pipeline stream) so regenerating a scene never tears
  // down the generation stream — that's what blocked editing mid-build.
  const sceneAbortsRef = useRef<Map<string, AbortController>>(new Map());
  // Mirrors regeneratingSceneIds; applyPipelineEvent closes over state and
  // would otherwise see a stale set.
  const regeneratingSceneIdsRef = useRef<Set<string>>(new Set());
  const logContainerRef = useRef<HTMLDivElement | null>(null);
  const codeContainerRef = useRef<HTMLPreElement | null>(null);
  const eventsLenRef = useRef(0);
  const didInitialRestoreRef = useRef(false);
  const buildStartedAtRef = useRef<number | null>(null);
  const signedIn = authStatus === "authenticated";
  const urlJobId = searchParams.get("job");
  const urlPrompt = searchParams.get("prompt");

  useEffect(() => {
    if (urlPrompt && !prompt) {
      setPrompt(urlPrompt);
    }
    // Seed once from ?prompt= (e.g. Understand → Create handoff)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlPrompt]);

  useEffect(() => {
    eventsLenRef.current = events.length;
  }, [events.length]);

  // The AI storyboard-revise call is a single blocking request (up to 3 LLM
  // attempts server-side) with no progress stream — tick a visible timer so
  // it doesn't look frozen for the 10-60s it can realistically take.
  // Elapsed is reset to 0 when revise starts (in onRevisePlan), not here —
  // avoids a synchronous setState on the !revising cleanup path.
  useEffect(() => {
    if (!revising) return;
    const id = window.setInterval(() => {
      setReviseElapsed((s) => s + 1);
    }, 1000);
    return () => window.clearInterval(id);
  }, [revising]);

  useEffect(() => {
    if (jobId) setStoredActiveJobId(jobId);
  }, [jobId]);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        const manim = h.manim_available
          ? ` · Manim ${h.manim_version || "ok"}`
          : "";
        const short = (id?: string) =>
          id?.includes("/") ? id.split("/").pop() : id;
        const worker =
          h.render_worker_configured && h.render_worker_ok === false
            ? " · worker URL invalid (using local)"
            : h.render_worker_ok
              ? " · remote worker"
              : "";
        if (h.tts_voices?.length) {
          setTtsVoices(h.tts_voices);
          setTtsVoice((current) => {
            if (!h.tts_voices!.find((v) => v.id === current)) {
              return h.tts_voices![0].id;
            }
            return current;
          });
        }
        if (h.languages?.length) {
          setLanguages(h.languages);
        }
        setHealth(
          h.openrouter_configured
            ? `Ready · ${short(h.manim_model || h.model) || "llm"} · VLM ${short(h.vlm_model) || "flash-lite"}${manim}${worker}`
            : "API up · set OPENROUTER_API_KEY",
        );
      })
      .catch(() => setHealth("API offline — start FastAPI on :8000"));
  }, []);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [events, logOpen]);

  useEffect(() => {
    if (codeContainerRef.current && codeOpen) {
      codeContainerRef.current.scrollTop = 0;
    }
  }, [latestCode?.sceneId, latestCode?.revision, codeOpen]);

  // Visible elapsed clock while planning/building so long LLM/render waits
  // don't look frozen between sparse status lines.
  useEffect(() => {
    if (!running) {
      buildStartedAtRef.current = null;
      return;
    }
    if (buildStartedAtRef.current == null) {
      buildStartedAtRef.current = Date.now();
    }
    const id = window.setInterval(() => {
      const start = buildStartedAtRef.current;
      if (start != null) {
        setBuildElapsed(Math.floor((Date.now() - start) / 1000));
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const hasSceneOutput = scenes.some(
    (s) => s.videoUrl || s.frameUrl || s.status === "done",
  );
  const completed = events.some((e) => e.type === "complete") || Boolean(finalVideoUrl);

  const mode: FlowMode = useMemo(() => {
    if (awaitingPlan && editingPlan) return "storyboard";
    if (finalVideoUrl || (completed && hasSceneOutput && !awaitingPlan)) {
      return "result";
    }
    if (running || (scenes.length > 0 && !awaitingPlan && !completed)) {
      return "building";
    }
    return "compose";
  }, [
    awaitingPlan,
    editingPlan,
    finalVideoUrl,
    completed,
    hasSceneOutput,
    running,
    scenes.length,
  ]);

  const doneCount = scenes.filter((s) => s.status === "done").length;
  const showExamples = promptFocused || !prompt.trim();

  function applyPipelineEvent(event: PipelineEvent) {
    setEvents((prev) => {
      const next = [...prev, event];
      eventsLenRef.current = next.length;
      return next;
    });
    setLiveMessage(event.message);
    if (event.data?.job_id && typeof event.data.job_id === "string") {
      setJobId(event.data.job_id);
      setStoredActiveJobId(event.data.job_id);
    }
    const eventSceneId =
      typeof event.data?.scene_id === "string" ? event.data.scene_id : null;
    const inFlight = regeneratingSceneIdsRef.current;
    // Route by the event's own scene_id. Falling back to "the" active scene
    // only works when exactly one edit is running — with several in flight an
    // untagged event would land on the wrong scene.
    const attributedSceneId =
      eventSceneId ?? (inFlight.size === 1 ? [...inFlight][0] : null);
    if (eventSceneId && inFlight.has(eventSceneId)) {
      setSceneRegenMessage((prev) => ({
        ...prev,
        [eventSceneId]: event.message,
      }));
    }
    if (event.type === "error") {
      if (attributedSceneId && inFlight.has(attributedSceneId)) {
        setSceneRegenError((prev) => ({
          ...prev,
          [attributedSceneId]: event.message,
        }));
      } else {
        setError(event.message);
      }
    }
    if (
      (event.type === "plan" || event.type === "plan_ready") &&
      event.data
    ) {
      const plan = planFromEvent(event.data as Record<string, unknown>);
      setPlanTitle(plan.title);
      setEditingPlan(plan);
      setScenes(scenesFromPlan(plan));
      if (event.type === "plan_ready" || event.data.awaiting_confirm) {
        setAwaitingPlan(true);
        setRunning(false);
      }
    }
    if (event.type === "scene_start" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id ? { ...s, status: "starting" } : s,
        ),
      );
    }
    if (
      event.type === "status" &&
      event.data?.scene_id &&
      typeof event.data.step === "string"
    ) {
      const step = event.data.step as string;
      const statusByStep: Record<string, string> = {
        "scene.tts": "narrating",
        "scene.codegen": "writing code",
        "scene.render": "rendering",
      };
      const nextStatus = statusByStep[step];
      if (nextStatus) {
        setScenes((prev) =>
          prev.map((s) =>
            s.id === event.data?.scene_id ? { ...s, status: nextStatus } : s,
          ),
        );
      }
    }
    if (event.type === "scene_code" && event.data?.scene_id) {
      const code =
        typeof event.data.code === "string" ? event.data.code : null;
      if (code) {
        setLatestCode({
          sceneId: String(event.data.scene_id),
          revision:
            typeof event.data.revision === "number" ? event.data.revision : 0,
          code,
          truncated: Boolean(event.data.code_truncated),
          chars:
            typeof event.data.code_chars === "number"
              ? event.data.code_chars
              : code.length,
        });
        setCodeOpen(true);
        setLogOpen(true);
      }
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id ? { ...s, status: "code ready" } : s,
        ),
      );
    }
    if (event.type === "scene_revise" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id ? { ...s, status: "revising" } : s,
        ),
      );
    }
    if (event.type === "scene_tts" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                status: "narrating",
                duration:
                  typeof event.data?.target_duration === "number"
                    ? event.data.target_duration
                    : s.duration,
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_render" && event.data?.scene_id) {
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                status: event.data?.ok ? "rendered" : "render failed",
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_vlm" && event.data?.scene_id) {
      if (typeof event.data.frame_url === "string") {
        bumpVideoVersion(event.data.scene_id as string);
      }
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                approved: Boolean(event.data?.approved),
                clarity:
                  typeof event.data?.clarity_score === "number"
                    ? event.data.clarity_score
                    : s.clarity,
                status: event.data?.approved ? "approved" : "needs work",
                frameUrl:
                  typeof event.data?.frame_url === "string"
                    ? event.data.frame_url
                    : s.frameUrl,
              }
            : s,
        ),
      );
    }
    if (event.type === "scene_done" && event.data?.scene_id) {
      const newVideoUrl =
        typeof event.data?.video_url === "string"
          ? event.data.video_url
          : undefined;
      if (newVideoUrl) bumpVideoVersion(event.data.scene_id as string);
      setScenes((prev) =>
        prev.map((s) =>
          s.id === event.data?.scene_id
            ? {
                ...s,
                // A scene can finish its pipeline without ever producing a
                // clip (render kept failing) — don't report "done" in that
                // case, or a failed regenerate silently looks successful.
                status: newVideoUrl || s.videoUrl ? "done" : "render failed",
                approved: Boolean(event.data?.vlm_approved),
                clarity:
                  typeof event.data?.clarity_score === "number"
                    ? event.data.clarity_score
                    : s.clarity,
                videoUrl: newVideoUrl ?? s.videoUrl,
                frameUrl:
                  typeof event.data?.frame_url === "string"
                    ? event.data.frame_url
                    : s.frameUrl,
              }
            : s,
        ),
      );
    }
    if (event.type === "final_debug" && event.data) {
      setFinalNotes(String(event.data.notes || ""));
    }
    if (event.type === "complete" && event.data) {
      if (typeof event.data.final_video_url === "string") {
        setFinalVideoUrl(event.data.final_video_url);
        setFinalVideoVersion((v) => v + 1);
      }
      const completedScenes = event.data.scenes as
        | Array<Record<string, unknown>>
        | undefined;
      if (completedScenes?.length) {
        setScenes((prev) =>
          prev.map((s) => {
            const match = completedScenes.find(
              (c) => c.scene_id === s.id || c.id === s.id,
            );
            if (!match) return s;
            const newVideoUrl =
              typeof match.video_url === "string" ? match.video_url : undefined;
            if (newVideoUrl) bumpVideoVersion(s.id);
            return {
              ...s,
              status: newVideoUrl || s.videoUrl ? "done" : "render failed",
              approved: Boolean(match.vlm_approved),
              videoUrl: newVideoUrl ?? s.videoUrl,
              frameUrl:
                typeof match.frame_url === "string"
                  ? match.frame_url
                  : s.frameUrl,
            };
          }),
        );
      }
      // "complete" from a single-scene regenerate: has scene_id + video_url
      // (video_url may be null if the re-render failed — surface that
      // instead of silently reporting success with the old clip).
      if (typeof event.data.scene_id === "string") {
        const sceneId = event.data.scene_id;
        const newVideoUrl =
          typeof event.data.video_url === "string"
            ? event.data.video_url
            : undefined;
        if (newVideoUrl) bumpVideoVersion(sceneId);
        else {
          setSceneRegenError((prev) => ({
            ...prev,
            [sceneId]:
              "Regenerate finished but the scene failed to render — kept the previous clip.",
          }));
        }
        setScenes((prev) =>
          prev.map((s) =>
            s.id === sceneId
              ? {
                  ...s,
                  status: newVideoUrl || s.videoUrl ? "done" : "regenerate failed",
                  videoUrl: newVideoUrl ?? s.videoUrl,
                  frameUrl:
                    typeof event.data?.frame_url === "string"
                      ? event.data.frame_url
                      : s.frameUrl,
                  approved:
                    event.data?.vlm_approved !== undefined
                      ? Boolean(event.data.vlm_approved)
                      : s.approved,
                }
              : s,
          ),
        );
        if (typeof event.data.final_video_url === "string") {
          setFinalVideoUrl(event.data.final_video_url);
          setFinalVideoVersion((v) => v + 1);
        }
      }
    }
  }

  function hydrateFromJob(job: JobDetail) {
    const planData = (job.scene_plan || {}) as Record<string, unknown>;
    if (planData.title || Array.isArray(planData.scenes)) {
      const plan = planFromEvent(planData);
      setPlanTitle(plan.title);
      setEditingPlan(plan);
      const previews = plan.scenes.map((s) => {
        const art = job.scenes.find((x) => x.scene_id === s.id);
        const lastReview = art?.vlm_reviews?.[art.vlm_reviews.length - 1];
        const frameUrl =
          typeof lastReview?.frame_url === "string"
            ? lastReview.frame_url
            : undefined;
        return {
          id: s.id,
          title: s.title,
          narration: s.narration,
          visualDescription: s.visual_description,
          beats: s.animation_beats,
          visualDevice: s.visual_device,
          duration: s.duration_seconds,
          videoUrl: art?.video_url,
          frameUrl,
          approved:
            typeof lastReview?.approved === "boolean"
              ? lastReview.approved
              : undefined,
          clarity:
            typeof lastReview?.clarity_score === "number"
              ? lastReview.clarity_score
              : undefined,
          status: art?.video_url
            ? "done"
            : art?.code_final
              ? "building"
              : "queued",
        } satisfies ScenePreview;
      });
      setScenes(previews);
    }
    if (typeof job.meta?.prompt === "string" && job.meta.prompt) {
      setPrompt(job.meta.prompt);
    }
    const metaSettings = job.meta?.settings;
    if (metaSettings && typeof metaSettings === "object") {
      const s = metaSettings as {
        tts_voice?: unknown;
        language?: unknown;
        include_audio?: unknown;
        include_subtitles?: unknown;
      };
      if (typeof s.tts_voice === "string") setTtsVoice(s.tts_voice);
      if (typeof s.language === "string") setLanguage(s.language);
      if (typeof s.include_audio === "boolean") setIncludeAudio(s.include_audio);
      if (typeof s.include_subtitles === "boolean") {
        setIncludeSubtitles(s.include_subtitles);
      }
    }
    if (job.final_video_url) setFinalVideoUrl(job.final_video_url);
    if (job.final_debug && typeof job.final_debug.notes === "string") {
      setFinalNotes(job.final_debug.notes);
    }
    const replay = (job.events || []).map(
      (e) =>
        ({
          type: String(e.type || "status"),
          message: String(e.message || ""),
          data: (e.data as Record<string, unknown>) || null,
        }) satisfies PipelineEvent,
    );
    setEvents(replay);
    eventsLenRef.current = replay.length;
    // Prefer the newest code blob from the event stream; fall back to disk.
    let codeFromEvents: CodePreview | null = null;
    for (let i = replay.length - 1; i >= 0; i -= 1) {
      const e = replay[i];
      if (e.type === "scene_code" && typeof e.data?.code === "string") {
        codeFromEvents = {
          sceneId: String(e.data.scene_id || ""),
          revision:
            typeof e.data.revision === "number" ? e.data.revision : 0,
          code: e.data.code,
          truncated: Boolean(e.data.code_truncated),
          chars:
            typeof e.data.code_chars === "number"
              ? e.data.code_chars
              : e.data.code.length,
        };
        break;
      }
    }
    if (!codeFromEvents) {
      for (let i = job.scenes.length - 1; i >= 0; i -= 1) {
        const art = job.scenes[i];
        if (art.code_final) {
          codeFromEvents = {
            sceneId: art.scene_id,
            revision: 0,
            code: art.code_final,
            truncated: false,
            chars: art.code_final.length,
          };
          break;
        }
      }
    }
    setLatestCode(codeFromEvents);
    if (codeFromEvents) setCodeOpen(true);
    setLogOpen(true);
    setJobId(job.job_id);
    setStoredActiveJobId(job.job_id);
  }

  async function attachToJobStream(activeJobId: string, after: number) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setLogOpen(true);
    setBuildElapsed(0);
    buildStartedAtRef.current = Date.now();
    setLiveMessage("Reconnected — catching up on progress…");
    try {
      await streamJobEvents(activeJobId, applyPipelineEvent, {
        after,
        signal: controller.signal,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      if (abortRef.current === controller) {
        setRunning(false);
      }
    }
  }

  async function resumeOrAttach(job: JobDetail) {
    const runtime = job.runtime;
    const status = runtime?.status || "unknown";
    const after = runtime?.event_count ?? (job.events?.length || 0);

    if (status === "awaiting_plan") {
      setAwaitingPlan(true);
      setRunning(false);
      setLiveMessage("Storyboard ready — confirm to generate video");
      return;
    }
    if (status === "complete") {
      setAwaitingPlan(false);
      setRunning(false);
      setLiveMessage("Restored finished explanation");
      return;
    }
    if (status === "running" || runtime?.running) {
      setAwaitingPlan(false);
      await attachToJobStream(job.job_id, Math.max(0, after - 0));
      // Re-fetch in case stream ended before complete event arrived
      try {
        const fresh = await fetchJob(job.job_id);
        hydrateFromJob(fresh);
        if (fresh.runtime?.status === "interrupted") {
          setLiveMessage("Resuming interrupted generation…");
          await streamContinue(job.job_id, applyPipelineEvent, undefined);
        }
      } catch {
        /* ignore */
      }
      return;
    }
    if (status === "interrupted") {
      setAwaitingPlan(false);
      setRunning(true);
      setLiveMessage("Resuming interrupted generation…");
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamContinue(
          job.job_id,
          applyPipelineEvent,
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message);
        }
      } finally {
        if (abortRef.current === controller) setRunning(false);
      }
      return;
    }
    setRunning(false);
  }

  // Restore active job after refresh, or when opened via /?job=…
  useEffect(() => {
    if (authStatus === "loading") return;
    if (!signedIn) {
      setRestoring(false);
      return;
    }
    const restoreId =
      urlJobId ||
      (!didInitialRestoreRef.current ? getStoredActiveJobId() : null);
    didInitialRestoreRef.current = true;
    if (!restoreId) {
      setRestoring(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await ensureApiToken();
        const job = await fetchJob(restoreId);
        if (cancelled) return;
        hydrateFromJob(job);
        setRestoring(false);
        await resumeOrAttach(job);
      } catch {
        if (!cancelled) {
          setStoredActiveJobId(null);
          setRestoring(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      // Drop this UI subscription only — backend job keeps running.
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial restore + URL job changes
  }, [authStatus, signedIn, urlJobId]);

  function resetToCompose() {
    // Stop watching this job in the UI, but leave the backend job running.
    abortRef.current?.abort();
    reviseAbortRef.current?.abort();
    setRunning(false);
    setAwaitingPlan(false);
    setEditingPlan(null);
    setEvents([]);
    setPlanTitle(null);
    setScenes([]);
    setFinalNotes(null);
    setFinalVideoUrl(null);
    setJobId(null);
    setStoredActiveJobId(null);
    setError(null);
    setLiveMessage("");
    setRegenDirection({});
    for (const controller of sceneAbortsRef.current.values()) {
      controller.abort();
    }
    sceneAbortsRef.current.clear();
    regeneratingSceneIdsRef.current = new Set();
    setRegeneratingSceneIds(new Set());
    setSceneRegenError({});
    setSceneRegenMessage({});
    setVideoVersion({});
    setFinalVideoVersion(0);
    setRevisePrompt("");
    setRevising(false);
    setReviseElapsed(0);
    setReviseError(null);
    setReviseSuccessMessage(null);
    setLogOpen(true);
    setCodeOpen(true);
    setLatestCode(null);
    setBuildElapsed(0);
    buildStartedAtRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      setIsPlayingPreview(false);
    }
  }

  async function playVoicePreview(voiceId: string) {
    if (audioRef.current) {
      audioRef.current.pause();
    }
    
    setIsPlayingPreview(true);
    await ensureApiToken();
    const src = assetUrl(`/api/tts/preview?voice=${encodeURIComponent(voiceId)}`);
    const audio = new Audio(src);
    audioRef.current = audio;
    
    audio.onended = () => setIsPlayingPreview(false);
    audio.onerror = () => setIsPlayingPreview(false);
    
    audio.play().catch((err) => {
      console.error("Failed to play preview", err);
      setIsPlayingPreview(false);
    });
  }

  async function onGenerate() {
    if (!prompt.trim() || running || restoring) return;
    if (!signedIn) {
      window.location.href = "/login";
      return;
    }
    // Detach UI from any previous job without cancelling it on the server.
    abortRef.current?.abort();
    setStoredActiveJobId(null);
    setRunning(true);
    setAwaitingPlan(false);
    setEditingPlan(null);
    setError(null);
    setEvents([]);
    setPlanTitle(null);
    setScenes([]);
    setFinalNotes(null);
    setFinalVideoUrl(null);
    setJobId(null);
    setLiveMessage("Planning storyboard…");
    setLatestCode(null);
    setLogOpen(true);
    setCodeOpen(true);
    setBuildElapsed(0);
    buildStartedAtRef.current = Date.now();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await ensureApiToken();
      await streamGenerate(
        {
          prompt: prompt.trim(),
          length_preset: lengthPreset,
          scene_pacing: scenePacing,
          audience,
          language,
          tts_voice: ttsVoice,
          include_audio: includeAudio,
          include_subtitles: includeSubtitles,
          plan_only: true,
          skip_render: false,
        },
        applyPipelineEvent,
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      if (abortRef.current === controller) {
        setRunning(false);
      }
    }
  }

  function updateSceneField(
    sceneId: string,
    patch: Partial<SceneSectionDraft>,
  ) {
    setEditingPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        scenes: prev.scenes.map((s) =>
          s.id === sceneId ? { ...s, ...patch } : s,
        ),
      };
    });
    setScenes((prev) =>
      prev.map((s) => {
        if (s.id !== sceneId) return s;
        return {
          ...s,
          title: patch.title ?? s.title,
          narration: patch.narration ?? s.narration,
          visualDescription:
            patch.visual_description ?? s.visualDescription,
          beats: patch.animation_beats ?? s.beats,
          visualDevice: patch.visual_device ?? s.visualDevice,
          duration: patch.duration_seconds ?? s.duration,
        };
      }),
    );
  }

  async function onRevisePlan() {
    if (!jobId || !revisePrompt.trim() || running || revising) return;
    setRevising(true);
    setReviseElapsed(0);
    setReviseError(null);
    setReviseSuccessMessage(null);
    const previousSceneCount = editingPlan?.scenes.length ?? 0;
    // This is a single blocking call (no progress stream) that can take a
    // while server-side (up to 3 LLM attempts) — bound it so a network hiccup
    // doesn't leave the UI stuck on "Revising…" forever with no way out.
    const controller = new AbortController();
    reviseAbortRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 120_000);
    try {
      await ensureApiToken();
      const plan = await revisePlanWithAI(
        jobId,
        revisePrompt.trim(),
        controller.signal,
      );
      setEditingPlan(plan);
      setPlanTitle(plan.title);
      setScenes(scenesFromPlan(plan));
      setRevisePrompt("");
      const delta = plan.scenes.length - previousSceneCount;
      const deltaLabel =
        delta > 0
          ? ` (+${delta} scene${delta === 1 ? "" : "s"})`
          : delta < 0
            ? ` (${delta} scene${delta === -1 ? "" : "s"})`
            : "";
      setReviseSuccessMessage(
        `Storyboard updated${deltaLabel} — review the changes below.`,
      );
      window.setTimeout(() => setReviseSuccessMessage(null), 6000);
      // Bring the revised scenes into view so the update isn't invisible.
      window.requestAnimationFrame(() => {
        document
          .getElementById("storyboard-scenes")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (err) {
      const e = err as Error;
      setReviseError(
        e.name === "AbortError"
          ? "That took too long and was cancelled. Try a shorter, more specific instruction, or try again."
          : e.message,
      );
    } finally {
      window.clearTimeout(timeout);
      reviseAbortRef.current = null;
      setRevising(false);
    }
  }

  function onCancelRevisePlan() {
    reviseAbortRef.current?.abort();
  }

  async function onConfirmPlan() {
    if (!jobId || !editingPlan || running) return;
    setRunning(true);
    setAwaitingPlan(false);
    setError(null);
    setLiveMessage("Saving storyboard…");
    setLogOpen(true);
    setCodeOpen(true);
    setBuildElapsed(0);
    buildStartedAtRef.current = Date.now();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await ensureApiToken();
      await updateJobPlan(jobId, editingPlan);
      setScenes((prev) => prev.map((s) => ({ ...s, status: "queued" })));
      setLiveMessage("Building scenes…");
      await streamContinue(jobId, applyPipelineEvent, controller.signal, {
        language,
        tts_voice: ttsVoice,
        include_audio: includeAudio,
        include_subtitles: includeSubtitles,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setAwaitingPlan(true);
      }
    } finally {
      setRunning(false);
    }
  }

  function markSceneRegenerating(sceneId: string, active: boolean) {
    const next = new Set(regeneratingSceneIdsRef.current);
    if (active) next.add(sceneId);
    else next.delete(sceneId);
    regeneratingSceneIdsRef.current = next;
    setRegeneratingSceneIds(next);
  }

  async function onRegenerateScene(sceneId: string) {
    // Deliberately not gated on `running`: a scene may be edited while the
    // pipeline builds other scenes, and while other scenes are being edited.
    // Only a second edit of *this* scene is refused (the server 409s too).
    if (!jobId || regeneratingSceneIdsRef.current.has(sceneId)) return;
    markSceneRegenerating(sceneId, true);
    setSceneRegenError((prev) => {
      const next = { ...prev };
      delete next[sceneId];
      return next;
    });
    setSceneRegenMessage((prev) => ({
      ...prev,
      [sceneId]: "Starting regeneration…",
    }));
    setScenes((prev) =>
      prev.map((s) =>
        s.id === sceneId ? { ...s, status: "regenerating" } : s,
      ),
    );
    // A per-scene controller — never touch abortRef, which owns the main
    // generation stream.
    sceneAbortsRef.current.get(sceneId)?.abort();
    const controller = new AbortController();
    sceneAbortsRef.current.set(sceneId, controller);

    const section = editingPlan?.scenes.find((s) => s.id === sceneId);
    try {
      await ensureApiToken();
      await streamRegenerateScene(jobId, sceneId, applyPipelineEvent, {
        direction: regenDirection[sceneId] || "more visual, clearer beats",
        section,
        signal: controller.signal,
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const message = (err as Error).message;
        setSceneRegenError((prev) => ({ ...prev, [sceneId]: message }));
        // The stream broke before we could tell whether a clip was ever
        // produced — don't leave the scene stuck on "regenerating…" forever.
        setScenes((prev) =>
          prev.map((s) =>
            s.id === sceneId && s.status === "regenerating"
              ? { ...s, status: s.videoUrl ? "done" : "regenerate failed" }
              : s,
          ),
        );
      }
    } finally {
      markSceneRegenerating(sceneId, false);
      if (sceneAbortsRef.current.get(sceneId) === controller) {
        sceneAbortsRef.current.delete(sceneId);
      }
    }
  }

  if (authStatus === "loading") {
    return (
      <section className="relative mx-auto w-full max-w-3xl px-6 py-16">
        <p className="text-sm text-[var(--ink-muted)]">Checking session…</p>
      </section>
    );
  }

  if (!signedIn) {
    return (
      <section className="relative mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 py-16 text-center">
        <p className="font-[family-name:var(--font-display)] text-4xl tracking-tight text-[var(--ink)] sm:text-5xl">
          NowIGetIt
        </p>
        <h1 className="mt-4 text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
          Prompt in. Scene plan, visual QA, voice — until the idea clicks.
        </h1>
        <p className="mx-auto mt-6 max-w-md text-sm text-[var(--ink-muted)]">
          Sign in to plan storyboards, generate videos, and keep every revision
          private to your account.
        </p>
        <Link
          href="/login"
          className="mt-10 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
        >
          Continue with Google
        </Link>
      </section>
    );
  }

  return (
    <>
      <section
        className={`relative mx-auto w-full max-w-3xl px-6 pt-8 sm:pt-10 ${
          mode === "storyboard" ? "pb-32" : "pb-16"
        }`}
      >
        {mode === "compose" && (
          <div className="animate-rise">
            <p className="font-[family-name:var(--font-display)] text-4xl tracking-tight text-[var(--ink)] sm:text-5xl">
              NowIGetIt
            </p>
            <h1 className="mt-3 max-w-xl text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
              Prompt in. Scene plan, visual QA, voice — until the idea clicks.
            </h1>

            <label className="sr-only" htmlFor="prompt">
              Prompt
            </label>
            <textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onFocus={() => setPromptFocused(true)}
              onBlur={() => setPromptFocused(false)}
              rows={4}
              placeholder="What should click? Describe the concept you want animated…"
              className="mt-10 w-full resize-none rounded-2xl border border-[var(--line)] bg-[var(--surface)] px-5 py-4 text-lg leading-relaxed text-[var(--ink)] outline-none transition focus:border-[var(--accent)] focus:shadow-[0_0_0_3px_var(--glow)] placeholder:text-[var(--ink-muted)]"
              disabled={running}
            />

            <div className="mt-5 flex flex-wrap items-end gap-5">
              <SegmentedControl
                label="Length"
                value={lengthPreset}
                options={LENGTH_OPTIONS}
                onChange={setLengthPreset}
                disabled={running}
              />
              <SegmentedControl
                label="Scenes"
                value={scenePacing}
                options={SCENE_PACING_OPTIONS}
                onChange={setScenePacing}
                disabled={running}
              />
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
                  className="rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {languages.map((lang) => (
                    <option key={lang.id} value={lang.id}>
                      {lang.label} · {lang.native_label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex min-w-[10rem] flex-col gap-1.5">
                <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Narrator
                </span>
                <div className="flex items-center gap-2">
                  <select
                    value={ttsVoice}
                    onChange={(e) => setTtsVoice(e.target.value)}
                    disabled={running || !includeAudio}
                    className="flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {ttsVoices.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    title="Test Voice"
                    disabled={running || !includeAudio || isPlayingPreview}
                    onClick={(e) => {
                      e.preventDefault();
                      playVoicePreview(ttsVoice);
                    }}
                    className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--line)] bg-[var(--surface)] text-[var(--ink)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-40"
                  >
                    {isPlayingPreview ? (
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="animate-pulse"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
                    ) : (
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                    )}
                  </button>
                </div>
              </label>
              <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-sm text-[var(--ink-muted)]">
                <input
                  type="checkbox"
                  checked={includeAudio}
                  onChange={(e) => setIncludeAudio(e.target.checked)}
                  disabled={running}
                  className="rounded border-[var(--line)]"
                />
                Audio
              </label>
              <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-sm text-[var(--ink-muted)]">
                <input
                  type="checkbox"
                  checked={includeSubtitles}
                  onChange={(e) => setIncludeSubtitles(e.target.checked)}
                  disabled={running}
                  className="rounded border-[var(--line)]"
                />
                Subtitles
              </label>
            </div>

            {showExamples && (
              <div className="mt-5 animate-rise">
                <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Try an example
                </p>
                <ul className="space-y-1.5">
                  {EXAMPLES.map((example) => (
                    <li key={example}>
                      <button
                        type="button"
                        onClick={() => setPrompt(example)}
                        className="text-left text-sm text-[var(--ink-muted)] transition hover:text-[var(--ink)]"
                      >
                        {example}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-8 flex flex-wrap items-center gap-4">
              <button
                type="button"
                disabled={running || !prompt.trim()}
                onClick={onGenerate}
                className="rounded-full bg-[var(--accent)] px-8 py-3 text-base font-semibold text-[var(--on-accent)] transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Plan storyboard
              </button>
            </div>

            <details className="mt-10 group">
              <summary className="cursor-pointer list-none text-xs text-[var(--ink-muted)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                <span className="border-b border-transparent group-open:border-[var(--line)]">
                  System status
                </span>
              </summary>
              <p className="mt-2 font-mono text-xs leading-relaxed text-[var(--ink-muted)]">
                {health}
              </p>
            </details>
          </div>
        )}

        {mode === "storyboard" && editingPlan && (
          <div className="animate-rise">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  Step 2 · Storyboard
                </p>
                <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
                  Edit the plan
                </h2>
                <p className="mt-2 max-w-xl text-sm text-[var(--ink-muted)]">
                  Tweak narration and visuals, then confirm to render.
                  {editingPlan.visual_identity
                    ? ` ${editingPlan.visual_identity}`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={resetToCompose}
                className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
              >
                Start over
              </button>
            </div>

            <input
              value={editingPlan.title}
              onChange={(e) => {
                setEditingPlan({ ...editingPlan, title: e.target.value });
                setPlanTitle(e.target.value);
              }}
              className="mt-8 w-full border-b border-[var(--line)] bg-transparent pb-2 font-[family-name:var(--font-display)] text-2xl text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              placeholder="Video title"
            />

            <label className="mt-6 flex max-w-xs flex-col gap-1.5">
              <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                Narrator voice
              </span>
              <div className="flex items-center gap-2">
                <select
                  value={ttsVoice}
                  onChange={(e) => setTtsVoice(e.target.value)}
                  disabled={running}
                  className="flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-1.5 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {ttsVoices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  title="Test Voice"
                  disabled={running || isPlayingPreview}
                  onClick={(e) => {
                    e.preventDefault();
                    playVoicePreview(ttsVoice);
                  }}
                  className="flex h-[34px] w-[34px] items-center justify-center rounded-lg border border-[var(--line)] bg-[var(--surface)] text-[var(--ink)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-40"
                >
                  {isPlayingPreview ? (
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="animate-pulse"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                  )}
                </button>
              </div>
            </label>

            <div className="mt-6 rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-4">
              <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                Ask AI to revise the storyboard
              </span>
              <p className="mt-1 text-xs text-[var(--ink-muted)]">
                e.g. &ldquo;add a scene about X&rdquo;, &ldquo;remove scene
                3&rdquo;, &ldquo;merge the last two scenes&rdquo;, &ldquo;make
                it longer&rdquo;.
              </p>
              <div className="mt-2 flex flex-wrap items-start gap-2">
                <AutoTextarea
                  value={revisePrompt}
                  onChange={setRevisePrompt}
                  minRows={1}
                  disabled={revising || running}
                  className="min-w-[12rem] flex-1 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)]"
                  placeholder="Describe the change you want…"
                />
                <button
                  type="button"
                  disabled={running || revising || !revisePrompt.trim()}
                  onClick={onRevisePlan}
                  className="flex items-center gap-2 rounded-lg border border-[var(--line)] px-4 py-2 text-sm font-medium text-[var(--ink)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-40"
                >
                  {revising && (
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  )}
                  {revising ? "Revising…" : "Apply"}
                </button>
                {revising && (
                  <button
                    type="button"
                    onClick={onCancelRevisePlan}
                    className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
                  >
                    Cancel
                  </button>
                )}
              </div>
              {revising && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--accent)]">
                  <span className="inline-flex gap-0.5">
                    {[0, 150, 300].map((delay) => (
                      <span
                        key={delay}
                        className="inline-block h-1 w-1 rounded-full bg-[var(--accent)] animate-bounce"
                        style={{ animationDelay: `${delay}ms` }}
                      />
                    ))}
                  </span>
                  AI is rewriting the storyboard…{" "}
                  {reviseElapsed > 0 ? `${reviseElapsed}s` : ""}
                  {reviseElapsed > 20
                    ? " · this can take up to a minute or two"
                    : ""}
                </p>
              )}
              {!revising && reviseSuccessMessage && (
                <p className="mt-2 text-xs text-[var(--accent)]">
                  ✓ {reviseSuccessMessage}
                </p>
              )}
              {reviseError && (
                <p className="mt-2 text-xs text-[var(--danger-ink)]">
                  {reviseError}
                </p>
              )}
            </div>

            <ol id="storyboard-scenes" className="mt-8 space-y-10">
              {editingPlan.scenes.map((scene, i) => (
                <li
                  key={scene.id}
                  className="grid gap-4 sm:grid-cols-[2.5rem_1fr]"
                >
                  <div className="pt-1 font-mono text-sm text-[var(--accent)]">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div className="min-w-0 space-y-4">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <input
                        value={scene.title}
                        onChange={(e) =>
                          updateSceneField(scene.id, { title: e.target.value })
                        }
                        className="min-w-0 flex-1 bg-transparent text-lg font-medium text-[var(--ink)] outline-none"
                      />
                      {scene.visual_device && (
                        <span className="text-xs uppercase tracking-[0.12em] text-[var(--ink-muted)]">
                          {scene.visual_device.replaceAll("_", " ")}
                        </span>
                      )}
                    </div>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        Narration
                      </span>
                      <AutoTextarea
                        value={scene.narration}
                        onChange={(v) =>
                          updateSceneField(scene.id, { narration: v })
                        }
                        minRows={3}
                        className="mt-1 text-[15px] leading-relaxed text-[var(--ink)]"
                        placeholder="What the voiceover says…"
                      />
                    </label>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        On screen
                      </span>
                      <AutoTextarea
                        value={scene.visual_description}
                        onChange={(v) =>
                          updateSceneField(scene.id, {
                            visual_description: v,
                          })
                        }
                        minRows={2}
                        className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]"
                        placeholder="What appears visually…"
                      />
                    </label>

                    <label className="block">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        Beats
                      </span>
                      <AutoTextarea
                        value={scene.animation_beats.join("\n")}
                        onChange={(v) =>
                          updateSceneField(scene.id, {
                            animation_beats: v
                              .split("\n")
                              .map((b) => b.trim())
                              .filter(Boolean),
                          })
                        }
                        minRows={2}
                        className="mt-1 text-sm leading-relaxed text-[var(--ink-muted)]"
                        placeholder="One animation beat per line…"
                      />
                    </label>
                  </div>
                </li>
              ))}
            </ol>

            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={running || revising || !prompt.trim()}
                onClick={onGenerate}
                className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline disabled:opacity-40"
              >
                Re-plan from prompt
              </button>
            </div>
          </div>
        )}

        {(mode === "building" || mode === "result") && (
          <div className="animate-rise">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                  {mode === "building"
                    ? scenes.length === 0
                      ? "Step 1 · Planning"
                      : "Step 3 · Building"
                    : "Your video"}
                </p>
                <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
                  {planTitle ||
                    (mode === "building" && scenes.length === 0
                      ? "Planning storyboard"
                      : "Explanation")}
                </h2>
                <p className="mt-2 text-sm text-[var(--ink-muted)]">
                  {mode === "building"
                    ? liveMessage ||
                      (scenes.length === 0
                        ? "Sketching scenes from your prompt…"
                        : "Clips unlock as each scene finishes — you don’t need to wait for the end.")
                    : "Full explanation with narration. Tweak individual scenes below if needed."}
                </p>
                {mode === "building" && running && (
                  <p className="mt-1 font-mono text-xs text-[var(--accent)]">
                    Elapsed {formatElapsed(buildElapsed)}
                    {events.length > 0 ? ` · ${events.length} steps` : ""}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {running && (
                  <button
                    type="button"
                    onClick={() => abortRef.current?.abort()}
                    className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
                    title="Stop updating this page — generation keeps running in the background"
                  >
                    Stop watching
                  </button>
                )}
                <button
                  type="button"
                  onClick={resetToCompose}
                  className="rounded-md border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
                  title="Start something new — the previous job keeps generating and stays in your library"
                >
                  New explanation
                </button>
              </div>
            </div>

            {mode === "building" && scenes.length > 0 && (
              <div className="mt-6">
                <div className="mb-2 flex justify-between text-xs text-[var(--ink-muted)]">
                  <span>
                    {doneCount} of {scenes.length} scenes ready
                  </span>
                  {running && (
                    <span className="text-[var(--accent)]">Generating…</span>
                  )}
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-strong)]">
                  <div
                    className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
                    style={{
                      width: `${scenes.length ? (doneCount / scenes.length) * 100 : 8}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {mode === "building" && (running || events.length > 0) && (
              <div className="mt-8 space-y-4">
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                      Live activity
                    </p>
                    <button
                      type="button"
                      onClick={() => setLogOpen((v) => !v)}
                      className="text-xs text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
                    >
                      {logOpen ? "Collapse" : "Expand"}
                      {events.length > 0 ? ` · ${events.length}` : ""}
                    </button>
                  </div>
                  {logOpen && (
                    <div
                      ref={logContainerRef}
                      className="mt-3 max-h-72 overflow-y-auto rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-3"
                    >
                      {events.length === 0 && (
                        <div className="font-mono text-xs text-[var(--ink-muted)] opacity-60">
                          Waiting for the first planning step…
                        </div>
                      )}
                      {events.map((event, idx) => {
                        const detail =
                          typeof event.data?.detail === "string"
                            ? event.data.detail
                            : null;
                        const isLatest = idx === events.length - 1;
                        return (
                          <div
                            key={`${event.type}-${idx}`}
                            className={`mb-2.5 border-l-2 pl-3 ${
                              isLatest && running
                                ? "border-[var(--accent)]"
                                : "border-[var(--line)]"
                            }`}
                          >
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                              <span className="rounded bg-[var(--surface-strong)] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-[var(--accent)]">
                                {eventStepLabel(event)}
                              </span>
                              <span
                                className={`text-xs leading-relaxed ${
                                  isLatest && running
                                    ? "text-[var(--ink)]"
                                    : "text-[var(--ink-muted)]"
                                }`}
                              >
                                {event.message}
                              </span>
                            </div>
                            {detail && (
                              <p className="mt-1 line-clamp-3 font-mono text-[11px] leading-relaxed text-[var(--ink-muted)]">
                                {detail}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {latestCode && (
                  <div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
                        Generated code · {latestCode.sceneId}
                        {latestCode.revision > 0
                          ? ` · r${latestCode.revision}`
                          : ""}
                        {latestCode.truncated ? " · preview" : ""}
                      </p>
                      <button
                        type="button"
                        onClick={() => setCodeOpen((v) => !v)}
                        className="text-xs text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
                      >
                        {codeOpen ? "Hide code" : "Show code"}
                        {` · ${latestCode.chars.toLocaleString()} chars`}
                      </button>
                    </div>
                    {codeOpen && (
                      <pre
                        ref={codeContainerRef}
                        className="mt-3 max-h-80 overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-4 font-mono text-[11px] leading-relaxed text-[var(--ink)]"
                      >
                        <code>{latestCode.code}</code>
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}

            {mode === "result" && finalVideoUrl && (
              <div className="mt-8">
                <AuthMedia
                  src={finalVideoUrl}
                  cacheBust={finalVideoVersion}
                  className="w-full overflow-hidden rounded-2xl border border-[var(--line)]"
                />
                {jobId && (
                  <p className="mt-3 text-sm text-[var(--ink-muted)]">
                    Saved to your{" "}
                    <Link
                      href="/library"
                      className="text-[var(--accent)] underline-offset-4 hover:underline"
                    >
                      library
                    </Link>
                    .
                  </p>
                )}
              </div>
            )}

            {mode === "result" && running && liveMessage && (
              <div className="mt-4 flex items-center justify-between gap-4 rounded-xl border border-[var(--line)] bg-[var(--bg-deep)] px-4 py-3">
                <p className="text-sm text-[var(--accent)]">{liveMessage}</p>
                {jobId && (
                  <button
                    type="button"
                    onClick={() => {
                      void cancelJob(jobId);
                      abortRef.current?.abort();
                    }}
                    className="shrink-0 text-sm font-medium text-[var(--danger-ink)] hover:underline transition hover:text-[var(--danger-line)]"
                  >
                    Stop generation
                  </button>
                )}
              </div>
            )}

            <ul className="mt-10 space-y-8">
              {scenes.map((scene, i) => {
                const isRegeneratingThis = regeneratingSceneIds.has(scene.id);
                const settledStatuses = new Set([
                  "done",
                  "approved",
                  "needs work",
                  "render failed",
                  "regenerate failed",
                ]);
                // A finished scene stays editable even while the pipeline is
                // still building later ones, so this no longer waits for
                // mode === "result".
                const canShowRegenControls =
                  Boolean(jobId) &&
                  Boolean(scene.status) &&
                  settledStatuses.has(scene.status as string);
                return (
                  <li key={scene.id} className="min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                      <span className="font-mono text-xs text-[var(--accent)]">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="font-medium text-[var(--ink)]">
                        {scene.title}
                      </span>
                      {scene.status && (
                        <span className={sceneStatusTone(scene.status, scene.approved)}>
                          · {isRegeneratingThis ? "regenerating" : scene.status}
                        </span>
                      )}
                      {typeof scene.clarity === "number" && (
                        <span className="text-[var(--ink-muted)]">
                          · clarity {Math.round(scene.clarity * 100)}%
                        </span>
                      )}
                    </div>

                    {mode === "result" && scene.narration && (
                      <p className="mt-2 text-sm leading-relaxed text-[var(--ink-muted)]">
                        {scene.narration}
                      </p>
                    )}

                    <div className="relative mt-3">
                      {scene.videoUrl ? (
                        <AuthMedia
                          src={scene.videoUrl}
                          poster={scene.frameUrl}
                          cacheBust={videoVersion[scene.id]}
                          className="w-full overflow-hidden rounded-xl border border-[var(--line)]"
                        />
                      ) : scene.frameUrl ? (
                        <AuthMedia
                          src={scene.frameUrl}
                          kind="image"
                          alt={`${scene.title} preview`}
                          cacheBust={videoVersion[scene.id]}
                          className="w-full overflow-hidden rounded-xl border border-[var(--line)]"
                        />
                      ) : scene.status &&
                        scene.status !== "queued" &&
                        scene.status !== "done" ? (
                        <div className="flex aspect-video items-center justify-center rounded-xl border border-dashed border-[var(--line)] bg-[var(--surface)] text-sm text-[var(--ink-muted)]">
                          {scene.status}…
                        </div>
                      ) : null}

                      {isRegeneratingThis && (
                        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-xl bg-black/60 backdrop-blur-sm">
                          <span className="h-7 w-7 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
                          <span className="max-w-[85%] text-center text-xs text-white/90">
                            {sceneRegenMessage[scene.id] || "Regenerating scene…"}
                          </span>
                        </div>
                      )}
                    </div>

                    {sceneRegenError[scene.id] && !isRegeneratingThis && (
                      <p className="mt-2 text-xs text-[var(--danger-ink)]">
                        {sceneRegenError[scene.id]}
                      </p>
                    )}

                    {canShowRegenControls && (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <input
                          value={regenDirection[scene.id] ?? ""}
                          onChange={(e) =>
                            setRegenDirection((prev) => ({
                              ...prev,
                              [scene.id]: e.target.value,
                            }))
                          }
                          placeholder="What should change? e.g. more visual, less text"
                          className="min-w-[12rem] flex-1 border-b border-[var(--line)] bg-transparent px-0 py-1.5 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)] disabled:opacity-50"
                          disabled={isRegeneratingThis}
                        />
                        <button
                          type="button"
                          disabled={isRegeneratingThis}
                          onClick={() => onRegenerateScene(scene.id)}
                          className="flex items-center gap-1.5 text-sm font-medium text-[var(--accent)] underline-offset-4 hover:underline disabled:opacity-40"
                        >
                          {isRegeneratingThis && (
                            <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                          )}
                          {isRegeneratingThis
                            ? "Regenerating…"
                            : scene.status === "render failed" ||
                                scene.status === "regenerate failed"
                              ? "Try again"
                              : "Regenerate scene"}
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>

            {finalNotes && mode === "result" && (
              <details className="mt-8">
                <summary className="cursor-pointer text-sm text-[var(--ink-muted)] hover:text-[var(--ink)]">
                  Final notes
                </summary>
                <p className="mt-2 text-sm text-[var(--ink)]">{finalNotes}</p>
              </details>
            )}

            {mode === "result" && (running || events.length > 0) && (
              <div className="mt-10 space-y-4">
                <div>
                  <button
                    type="button"
                    onClick={() => setLogOpen((v) => !v)}
                    className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
                  >
                    {logOpen ? "Hide activity" : "Show activity"}
                    {events.length > 0 ? ` (${events.length})` : ""}
                  </button>
                  {logOpen && (
                    <div
                      ref={logContainerRef}
                      className="mt-3 max-h-64 overflow-y-auto rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-3"
                    >
                      {events.map((event, idx) => (
                        <div
                          key={`${event.type}-${idx}`}
                          className="mb-2 border-l-2 border-[var(--line)] pl-3"
                        >
                          <span className="rounded bg-[var(--surface-strong)] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-[var(--accent)]">
                            {eventStepLabel(event)}
                          </span>{" "}
                          <span className="text-xs text-[var(--ink-muted)]">
                            {event.message}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {latestCode && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setCodeOpen((v) => !v)}
                      className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:text-[var(--ink)] hover:underline"
                    >
                      {codeOpen ? "Hide" : "Show"} generated code ·{" "}
                      {latestCode.sceneId}
                    </button>
                    {codeOpen && (
                      <pre
                        ref={codeContainerRef}
                        className="mt-3 max-h-80 overflow-auto rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-4 font-mono text-[11px] leading-relaxed text-[var(--ink)]"
                      >
                        <code>{latestCode.code}</code>
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}

            <details className="mt-8 group">
              <summary className="cursor-pointer list-none text-xs text-[var(--ink-muted)] transition hover:text-[var(--ink)] [&::-webkit-details-marker]:hidden">
                System status
              </summary>
              <p className="mt-2 font-mono text-xs leading-relaxed text-[var(--ink-muted)]">
                {health}
                {jobId ? ` · job ${jobId}` : ""}
              </p>
            </details>
          </div>
        )}

        {error && (
          <p className="mt-6 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-ink)]">
            {error}
          </p>
        )}
      </section>

      {mode === "storyboard" && editingPlan && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--line)] bg-[var(--bg-deep)]/90 backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3 px-6 py-4">
            <p className="text-sm text-[var(--ink-muted)]">
              {revising
                ? "Applying your storyboard changes…"
                : `${editingPlan.scenes.length} scenes ready to render`}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {running && (
                <button
                  type="button"
                  onClick={() => {
                    if (jobId) void cancelJob(jobId);
                    abortRef.current?.abort();
                  }}
                  className="text-sm text-[var(--ink-muted)] underline-offset-4 hover:underline"
                >
                  Cancel
                </button>
              )}
              <button
                type="button"
                disabled={running || revising || !editingPlan}
                onClick={onConfirmPlan}
                title={
                  revising
                    ? "Wait for the storyboard revision to finish first"
                    : undefined
                }
                className="rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110 disabled:opacity-40"
              >
                {running ? "Working…" : "Confirm & generate video"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
