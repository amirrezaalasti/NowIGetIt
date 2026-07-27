"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { MarkdownView } from "@/components/MarkdownView";
import {
  askDocument,
  assetUrl,
  deleteDocument,
  deleteDocumentComment,
  ensureApiToken,
  getApiToken,
  getDocument,
  listDocuments,
  saveDocumentComment,
  uploadDocumentStream,
  type DocumentAnnotation,
  type DocumentAskAction,
  type DocumentAskResult,
  type DocumentAskTurn,
  type DocumentDetail,
  type DocumentListItem,
  type DocumentManifest,
  type DocumentSlide,
  type PipelineEvent,
} from "@/lib/api";

type BlockSelection = {
  slideId: string;
  blockId: string;
  blockType: string;
  text: string;
  imageSrc?: string | null;
};

const PRIMARY_ACTIONS: { id: DocumentAskAction; label: string }[] = [
  { id: "explain", label: "Explain" },
  { id: "explain_figure", label: "Figure" },
  { id: "simplify", label: "Simplify" },
  { id: "deepen", label: "Deeper" },
  { id: "quiz", label: "Quiz" },
  { id: "summarize_slide", label: "Summary" },
];

const MORE_ACTIONS: { id: DocumentAskAction; label: string }[] = [
  { id: "key_takeaways", label: "Takeaways" },
  { id: "misconceptions", label: "Misconceptions" },
  { id: "critique", label: "Critique" },
  { id: "relate", label: "Relate" },
  { id: "extract_formula", label: "Formulas" },
  { id: "translate", label: "Translate" },
  { id: "comment", label: "Comment" },
  { id: "turn_into_video_prompt", label: "Video prompt" },
  { id: "freeform", label: "Ask anything" },
];

const ACTION_LABEL: Record<string, string> = Object.fromEntries(
  [...PRIMARY_ACTIONS, ...MORE_ACTIONS].map((a) => [a.id, a.label]),
);

export function Understand() {
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);
  const [selection, setSelection] = useState<BlockSelection | null>(null);
  const [action, setAction] = useState<DocumentAskAction>("explain");
  const [message, setMessage] = useState("");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState<DocumentAskResult | null>(null);
  const [thread, setThread] = useState<DocumentAskTurn[]>([]);
  const [followUp, setFollowUp] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [slideHtml, setSlideHtml] = useState<string>("");
  const [expectedPages, setExpectedPages] = useState<number | null>(null);
  const [converting, setConverting] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [showComments, setShowComments] = useState(true);
  const [savingComment, setSavingComment] = useState(false);
  const [savedCommentId, setSavedCommentId] = useState<string | null>(null);

  const manifest: DocumentManifest | null = detail?.manifest ?? null;
  const slides = manifest?.slides ?? [];
  const currentSlide = slides[slideIndex] ?? null;

  const refreshList = useCallback(async () => {
    try {
      await ensureApiToken();
      setDocs(await listDocuments());
    } catch {
      /* signed out */
    }
  }, []);

  const openDoc = useCallback(
    async (docId: string, opts?: { resetSlide?: boolean }) => {
      setError(null);
      setBusy(true);
      try {
        await ensureApiToken();
        const data = await getDocument(docId);
        setDetail(data);
        if (opts?.resetSlide !== false) {
          setSlideIndex(0);
          setSelection(null);
          setReply(null);
          setThread([]);
          setFollowUp("");
        }
        setConverting(data.manifest.status === "converting");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const removeDoc = useCallback(
    async (docId: string) => {
      const label =
        docs.find((d) => d.doc_id === docId)?.title ||
        detail?.manifest.title ||
        docId;
      if (
        !window.confirm(
          `Delete “${label}”? This removes the converted slides permanently.`,
        )
      ) {
        return;
      }
      setDeletingId(docId);
      setError(null);
      try {
        await ensureApiToken();
        await deleteDocument(docId);
        if (detail?.doc_id === docId) {
          setDetail(null);
          setReply(null);
          setThread([]);
          setFollowUp("");
          setSelection(null);
          setSlideHtml("");
          setFocusMode(false);
        }
        await refreshList();
        setStatus("Document deleted");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setDeletingId(null);
      }
    },
    [detail?.doc_id, detail?.manifest.title, docs, refreshList],
  );

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data;
      if (!data || data.type !== "nig-block-select") return;
      setSelection({
        slideId: String(data.slideId || currentSlide?.id || ""),
        blockId: String(data.blockId || ""),
        blockType: String(data.blockType || "other"),
        text: String(data.text || ""),
        imageSrc: data.imageSrc ? String(data.imageSrc) : null,
      });
      if (data.blockType === "figure") setAction("explain_figure");
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [currentSlide?.id]);

  useEffect(() => {
    if (!focusMode) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setFocusMode(false);
      if (e.key === "ArrowLeft") {
        setSlideIndex((i) => Math.max(0, i - 1));
        setSelection(null);
      }
      if (e.key === "ArrowRight") {
        setSlideIndex((i) => Math.min(Math.max(slides.length - 1, 0), i + 1));
        setSelection(null);
      }
    }
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [focusMode, slides.length]);

  useEffect(() => {
    let cancelled = false;
    async function loadSlide() {
      if (!currentSlide?.html_url) {
        setSlideHtml("");
        return;
      }
      try {
        const token = await getApiToken();
        const url = assetUrl(currentSlide.html_url);
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error("Failed to load slide HTML");
        let html = await res.text();
        html = html.replace(
          /(\b(?:src|href)=["'])(\/api\/jobs\/[^"']+)(["'])/g,
          (_m, pre: string, path: string, post: string) => {
            if (path.includes("access_token=")) return `${pre}${path}${post}`;
            const sep = path.includes("?") ? "&" : "?";
            return `${pre}${path}${sep}access_token=${encodeURIComponent(token)}${post}`;
          },
        );
        if (!cancelled) setSlideHtml(html);
      } catch (err) {
        if (!cancelled) {
          setSlideHtml("");
          setError((err as Error).message);
        }
      }
    }
    void loadSlide();
    return () => {
      cancelled = true;
    };
  }, [currentSlide?.html_url, slideIndex]);

  async function onUpload(file: File | null) {
    if (!file) return;
    setUploading(true);
    setConverting(true);
    setError(null);
    setExpectedPages(null);
    setStatus("Uploading… converting page-by-page");
    setDetail(null);
    setReply(null);
    setSelection(null);
    setSlideIndex(0);
    setFocusMode(false);

    let docId: string | null = null;

    const ensureShell = (data: Record<string, unknown> | null | undefined) => {
      const id = String(data?.doc_id || docId || "");
      if (!id) return;
      docId = id;
      setDetail((prev) => {
        if (prev?.doc_id === id) return prev;
        const title = String(data?.title || file.name);
        return {
          doc_id: id,
          annotations: [],
          manifest: {
            doc_id: id,
            title,
            source_filename: file.name,
            source_ext: file.name.includes(".")
              ? `.${file.name.split(".").pop()}`
              : "",
            status: "converting",
            slide_count: 0,
            slides: [],
            blocks: {},
            created_at: new Date().toISOString(),
          },
        };
      });
    };

    const onEvent = (event: PipelineEvent) => {
      const data = (event.data || {}) as Record<string, unknown>;
      if (typeof data.expected_pages === "number") {
        setExpectedPages(data.expected_pages);
      }
      if (event.type === "status") {
        setStatus(event.message);
        ensureShell(data);
      }
      if (event.type === "slide_ready") {
        ensureShell(data);
        const slide = data.slide as DocumentSlide | undefined;
        if (!slide?.id) return;
        setStatus(event.message);
        setDetail((prev) => {
          if (!prev) return prev;
          const exists = prev.manifest.slides.some((s) => s.id === slide.id);
          const nextSlides = exists
            ? prev.manifest.slides.map((s) => (s.id === slide.id ? slide : s))
            : [...prev.manifest.slides, slide].sort(
                (a, b) => a.index - b.index,
              );
          return {
            ...prev,
            manifest: {
              ...prev.manifest,
              title: String(data.title || prev.manifest.title),
              status: "converting",
              slide_count: nextSlides.length,
              slides: nextSlides,
            },
          };
        });
      }
      if (event.type === "complete") {
        setStatus(event.message);
        setConverting(false);
        const id = String(data.doc_id || docId || "");
        if (id) void openDoc(id, { resetSlide: false });
      }
      if (event.type === "error") {
        setError(event.message);
        setConverting(false);
      }
    };

    try {
      await ensureApiToken();
      await uploadDocumentStream(file, onEvent);
      await refreshList();
    } catch (err) {
      setError((err as Error).message);
      setStatus(null);
      setConverting(false);
    } finally {
      setUploading(false);
    }
  }

  async function runAsk() {
    if (!manifest || !currentSlide) return;
    setBusy(true);
    setError(null);
    setSavedCommentId(null);
    setFollowUp("");
    try {
      const result = await askDocument(manifest.doc_id, {
        action,
        slide_id: selection?.slideId || currentSlide.id,
        block_id: selection?.blockId || null,
        message,
        language,
        save_as_comment: false,
      });
      const userText = message.trim() || ACTION_LABEL[action] || action;
      setReply(result);
      setThread([
        { role: "user", content: userText },
        { role: "assistant", content: result.reply },
      ]);
      setSavedCommentId(result.comment_id || null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runFollowUp() {
    if (!manifest || !currentSlide || !reply?.reply) return;
    const q = followUp.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    setSavedCommentId(null);
    try {
      const conversation = [
        ...thread,
        { role: "user" as const, content: q },
      ].slice(-10);
      const result = await askDocument(manifest.doc_id, {
        action: "freeform",
        slide_id: reply.slide_id || selection?.slideId || currentSlide.id,
        block_id: reply.block_id || selection?.blockId || null,
        message: q,
        language,
        save_as_comment: false,
        prior_reply: reply.reply,
        conversation,
      });
      setReply(result);
      setThread([
        ...conversation,
        { role: "assistant", content: result.reply },
      ]);
      setFollowUp("");
      setMessage(q);
      setAction("freeform");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveReplyAsComment() {
    if (!manifest || !currentSlide || !reply?.reply) return;
    setSavingComment(true);
    setError(null);
    try {
      const saved = await saveDocumentComment(manifest.doc_id, {
        slide_id: reply.slide_id || currentSlide.id,
        block_id: reply.block_id || selection?.blockId || null,
        action: reply.action,
        message,
        reply: reply.reply,
        author: "user+llm",
      });
      setSavedCommentId(saved.id);
      setReply({ ...reply, comment_id: saved.id });
      setShowComments(true);
      const fresh = await getDocument(manifest.doc_id);
      setDetail(fresh);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingComment(false);
    }
  }

  async function removeComment(commentId: string) {
    if (!manifest) return;
    if (!window.confirm("Remove this comment from the slide?")) return;
    try {
      await deleteDocumentComment(manifest.doc_id, commentId);
      if (savedCommentId === commentId) setSavedCommentId(null);
      const fresh = await getDocument(manifest.doc_id);
      setDetail(fresh);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const annotations: DocumentAnnotation[] = useMemo(
    () =>
      (detail?.annotations || []).filter((a) => a.slide_id === currentSlide?.id),
    [detail?.annotations, currentSlide?.id],
  );

  const studio =
    manifest && currentSlide ? (
      <DocumentStudio
        focusMode={focusMode}
        manifest={manifest}
        slides={slides}
        slideIndex={slideIndex}
        currentSlide={currentSlide}
        slideHtml={slideHtml}
        converting={converting}
        expectedPages={expectedPages}
        busy={busy}
        deleting={deletingId === manifest.doc_id}
        selection={selection}
        action={action}
        message={message}
        language={language}
        reply={reply}
        thread={thread}
        followUp={followUp}
        annotations={annotations}
        showMoreActions={showMoreActions}
        showComments={showComments}
        savingComment={savingComment}
        savedCommentId={savedCommentId}
        onPrev={() => {
          setSlideIndex((i) => Math.max(0, i - 1));
          setSelection(null);
        }}
        onNext={() => {
          setSlideIndex((i) => Math.min(slides.length - 1, i + 1));
          setSelection(null);
        }}
        onSelectSlide={(i) => {
          setSlideIndex(i);
          setSelection(null);
          setSavedCommentId(null);
          setReply(null);
          setThread([]);
          setFollowUp("");
        }}
        onBack={() => {
          setDetail(null);
          setReply(null);
          setThread([]);
          setFollowUp("");
          setSelection(null);
          setFocusMode(false);
          setSavedCommentId(null);
        }}
        onFocusToggle={() => setFocusMode((v) => !v)}
        onDelete={() => void removeDoc(manifest.doc_id)}
        onAction={setAction}
        onMessage={setMessage}
        onLanguage={setLanguage}
        onRun={() => void runAsk()}
        onFollowUp={setFollowUp}
        onRunFollowUp={() => void runFollowUp()}
        onToggleMore={() => setShowMoreActions((v) => !v)}
        onToggleComments={() => setShowComments((v) => !v)}
        onClearSelection={() => setSelection(null)}
        onSaveComment={() => void saveReplyAsComment()}
        onDeleteComment={(id) => void removeComment(id)}
      />
    ) : null;

  if (focusMode && studio) {
    return (
      <div className="fixed inset-0 z-[80] flex flex-col bg-[var(--bg-deep)]">
        <div className="pointer-events-none absolute inset-0 opacity-40 grid-haze" />
        <div className="relative z-10 flex min-h-0 flex-1 flex-col">
          {studio}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-7 px-4 py-8 sm:px-6">
      <header className="animate-rise space-y-3">
        <p className="text-xs uppercase tracking-[0.18em] text-[var(--ink-muted)]">
          Understand
        </p>
        <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)] sm:text-4xl">
          Interrogate any deck
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-[var(--ink-muted)]">
          Upload a lecture PDF or slide deck. Click any section for
          explanations, quizzes, figure readouts, and more.
        </p>
      </header>

      <section className="animate-rise rounded-2xl border border-[var(--line)] bg-[var(--surface)]/80 p-5 backdrop-blur-sm">
        <label className="flex cursor-pointer flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <div className="text-sm font-medium text-[var(--ink)]">
              Upload a document
            </div>
            <div className="text-xs text-[var(--ink-muted)]">
              PDF · PPTX · DOCX · XLSX · images · Markdown
            </div>
          </div>
          <input
            type="file"
            className="text-sm text-[var(--ink-muted)] file:mr-3 file:rounded-lg file:border-0 file:bg-[var(--accent)] file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-[var(--on-accent)]"
            accept=".pdf,.pptx,.ppt,.docx,.doc,.xlsx,.xls,.html,.htm,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp,.tif,.tiff,.gif,.bmp,.asciidoc,.adoc"
            disabled={uploading}
            onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
          />
        </label>
        {(status || uploading) && (
          <p className="mt-4 text-xs text-[var(--ink-muted)]">
            {uploading && !status ? "Converting…" : status}
          </p>
        )}
        {error && (
          <p className="mt-3 whitespace-pre-wrap rounded-lg border border-[var(--danger-line)] bg-[var(--danger-bg)] px-3 py-2 text-xs text-[var(--danger-ink)]">
            {error}
          </p>
        )}
      </section>

      {docs.length > 0 && !manifest && (
        <section className="animate-rise space-y-3">
          <h2 className="text-sm font-medium text-[var(--ink)]">Your decks</h2>
          <ul className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)]/70">
            {docs.map((d) => (
              <li
                key={d.doc_id}
                className="flex items-stretch gap-1 border-b border-[var(--line)] last:border-b-0"
              >
                <button
                  type="button"
                  onClick={() => void openDoc(d.doc_id)}
                  className="flex min-w-0 flex-1 items-center justify-between gap-3 px-4 py-3.5 text-left transition hover:bg-[var(--surface-inset)]"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-[var(--ink)]">
                      {d.title || d.source_filename || d.doc_id}
                    </span>
                    <span className="text-xs text-[var(--ink-muted)]">
                      {d.slide_count ?? 0} slides · {d.status || "ready"}
                    </span>
                  </span>
                  <span className="text-xs font-medium text-[var(--accent)]">
                    Open
                  </span>
                </button>
                <button
                  type="button"
                  disabled={deletingId === d.doc_id}
                  onClick={() => void removeDoc(d.doc_id)}
                  className="shrink-0 px-3 text-xs text-[var(--danger-ink)] transition hover:bg-[var(--danger-bg)] disabled:opacity-40"
                >
                  {deletingId === d.doc_id ? "…" : "Delete"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {studio}
    </div>
  );
}

function DocumentStudio(props: {
  focusMode: boolean;
  manifest: DocumentManifest;
  slides: DocumentSlide[];
  slideIndex: number;
  currentSlide: DocumentSlide;
  slideHtml: string;
  converting: boolean;
  expectedPages: number | null;
  busy: boolean;
  deleting: boolean;
  selection: BlockSelection | null;
  action: DocumentAskAction;
  message: string;
  language: string;
  reply: DocumentAskResult | null;
  thread: DocumentAskTurn[];
  followUp: string;
  annotations: DocumentAnnotation[];
  showMoreActions: boolean;
  showComments: boolean;
  savingComment: boolean;
  savedCommentId: string | null;
  onPrev: () => void;
  onNext: () => void;
  onSelectSlide: (i: number) => void;
  onBack: () => void;
  onFocusToggle: () => void;
  onDelete: () => void;
  onAction: (a: DocumentAskAction) => void;
  onMessage: (v: string) => void;
  onLanguage: (v: string) => void;
  onRun: () => void;
  onFollowUp: (v: string) => void;
  onRunFollowUp: () => void;
  onToggleMore: () => void;
  onToggleComments: () => void;
  onClearSelection: () => void;
  onSaveComment: () => void;
  onDeleteComment: (id: string) => void;
}) {
  const {
    focusMode,
    manifest,
    slides,
    slideIndex,
    currentSlide,
    slideHtml,
    converting,
    expectedPages,
    busy,
    deleting,
    selection,
    action,
    message,
    language,
    reply,
    thread,
    followUp,
    annotations,
    showMoreActions,
    showComments,
    savingComment,
    savedCommentId,
    onPrev,
    onNext,
    onSelectSlide,
    onBack,
    onFocusToggle,
    onDelete,
    onAction,
    onMessage,
    onLanguage,
    onRun,
    onFollowUp,
    onRunFollowUp,
    onToggleMore,
    onToggleComments,
    onClearSelection,
    onSaveComment,
    onDeleteComment,
  } = props;

  const progressLabel =
    converting || manifest.status === "converting"
      ? expectedPages
        ? `${slides.length}/${expectedPages}`
        : "…"
      : null;

  return (
    <section
      className={
        focusMode
          ? "grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-3 p-3 sm:p-4"
          : "flex flex-1 flex-col gap-4"
      }
    >
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)]/70 px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-[family-name:var(--font-display)] text-lg tracking-tight text-[var(--ink)] sm:text-xl">
              {manifest.title}
            </h2>
            {progressLabel && (
              <span className="rounded-full bg-[var(--accent)]/15 px-2 py-0.5 text-[11px] font-medium text-[var(--accent)]">
                Converting {progressLabel}
              </span>
            )}
            {focusMode && (
              <span className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[11px] text-[var(--ink-muted)]">
                Focus · Esc
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-[var(--ink-muted)]">
            {currentSlide.title || `Slide ${slideIndex + 1}`} · {slideIndex + 1}{" "}
            / {slides.length}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <ToolbarButton onClick={onPrev} disabled={slideIndex <= 0}>
            ←
          </ToolbarButton>
          <ToolbarButton
            onClick={onNext}
            disabled={slideIndex >= slides.length - 1}
          >
            →
          </ToolbarButton>
          <ToolbarButton onClick={onFocusToggle} accent>
            {focusMode ? "Exit focus" : "Focus"}
          </ToolbarButton>
          {!focusMode && (
            <ToolbarButton onClick={onBack}>All decks</ToolbarButton>
          )}
          <ToolbarButton onClick={onDelete} danger disabled={deleting}>
            {deleting ? "…" : "Delete"}
          </ToolbarButton>
        </div>
      </header>

      <div
        className={
          focusMode
            ? "grid min-h-0 gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.9fr)]"
            : "grid min-h-[32rem] gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.85fr)]"
        }
      >
        <div className="flex min-h-0 flex-col gap-3">
          <div
            className={
              focusMode
                ? "relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-[var(--line)] bg-white shadow-[0_20px_60px_rgba(0,0,0,0.25)]"
                : "relative min-h-[26rem] flex-1 overflow-hidden rounded-2xl border border-[var(--line)] bg-white shadow-[0_12px_40px_rgba(0,0,0,0.18)]"
            }
          >
            {slideHtml ? (
              <iframe
                key={`${currentSlide.id}-${slideIndex}`}
                title={currentSlide.title}
                srcDoc={slideHtml}
                className="h-full min-h-[26rem] w-full bg-white lg:min-h-0"
                sandbox="allow-scripts allow-same-origin"
              />
            ) : (
              <div className="flex h-full min-h-[16rem] items-center justify-center text-sm text-[var(--ink-muted)]">
                {busy ? "Loading slide…" : "No slide HTML yet"}
              </div>
            )}
          </div>

          <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:thin]">
            {slides.map((s, i) => (
              <button
                key={s.id}
                type="button"
                title={s.title}
                onClick={() => onSelectSlide(i)}
                className={`shrink-0 rounded-xl border px-2.5 py-1.5 text-left transition ${
                  i === slideIndex
                    ? "border-[var(--accent)] bg-[var(--accent)]/12 text-[var(--ink)]"
                    : "border-[var(--line)] bg-[var(--surface)]/50 text-[var(--ink-muted)] hover:border-[var(--ink-muted)] hover:text-[var(--ink)]"
                }`}
              >
                <span className="block text-[10px] uppercase tracking-wide opacity-70">
                  {i + 1}
                </span>
                <span className="block max-w-[7.5rem] truncate text-xs">
                  {s.title || `Slide ${i + 1}`}
                </span>
              </button>
            ))}
          </div>
        </div>

        <aside
          className={`flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-panel)] ${
            focusMode ? "" : ""
          }`}
        >
          <AssistantPanel
            selection={selection}
            action={action}
            message={message}
            language={language}
            busy={busy}
            reply={reply}
            thread={thread}
            followUp={followUp}
            annotations={annotations}
            showMoreActions={showMoreActions}
            showComments={showComments}
            savingComment={savingComment}
            savedCommentId={savedCommentId}
            onAction={onAction}
            onMessage={onMessage}
            onLanguage={onLanguage}
            onRun={onRun}
            onFollowUp={onFollowUp}
            onRunFollowUp={onRunFollowUp}
            onToggleMore={onToggleMore}
            onToggleComments={onToggleComments}
            onClearSelection={onClearSelection}
            onSaveComment={onSaveComment}
            onDeleteComment={onDeleteComment}
          />
        </aside>
      </div>
    </section>
  );
}

function ToolbarButton({
  children,
  onClick,
  disabled,
  accent,
  danger,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  accent?: boolean;
  danger?: boolean;
}) {
  const tone = danger
    ? "text-[var(--danger-ink)] hover:bg-[var(--danger-bg)]"
    : accent
      ? "border-[var(--accent)]/35 bg-[var(--accent)]/12 text-[var(--accent)] hover:bg-[var(--accent)]/18"
      : "text-[var(--ink)] hover:bg-[var(--surface-inset)]";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-lg border border-[var(--line)] px-2.5 py-1.5 text-xs transition disabled:opacity-35 ${tone}`}
    >
      {children}
    </button>
  );
}

function AssistantPanel(props: {
  selection: BlockSelection | null;
  action: DocumentAskAction;
  message: string;
  language: string;
  busy: boolean;
  reply: DocumentAskResult | null;
  thread: DocumentAskTurn[];
  followUp: string;
  annotations: DocumentAnnotation[];
  showMoreActions: boolean;
  showComments: boolean;
  savingComment: boolean;
  savedCommentId: string | null;
  onAction: (a: DocumentAskAction) => void;
  onMessage: (v: string) => void;
  onLanguage: (v: string) => void;
  onRun: () => void;
  onFollowUp: (v: string) => void;
  onRunFollowUp: () => void;
  onToggleMore: () => void;
  onToggleComments: () => void;
  onClearSelection: () => void;
  onSaveComment: () => void;
  onDeleteComment: (id: string) => void;
}) {
  const {
    selection,
    action,
    message,
    language,
    busy,
    reply,
    thread,
    followUp,
    annotations,
    showMoreActions,
    showComments,
    savingComment,
    savedCommentId,
    onAction,
    onMessage,
    onLanguage,
    onRun,
    onFollowUp,
    onRunFollowUp,
    onToggleMore,
    onToggleComments,
    onClearSelection,
    onSaveComment,
    onDeleteComment,
  } = props;

  const isReplySaved = Boolean(
    savedCommentId || (reply?.comment_id && reply.comment_id),
  );

  const actions = showMoreActions
    ? [...PRIMARY_ACTIONS, ...MORE_ACTIONS]
    : PRIMARY_ACTIONS;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-[var(--line)] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-[family-name:var(--font-display)] text-base tracking-tight text-[var(--ink)]">
            Assistant
          </h3>
          <span className="text-[11px] text-[var(--ink-muted)]">
            {ACTION_LABEL[action] || action}
          </span>
        </div>
        {selection ? (
          <div className="mt-2 rounded-xl border border-[var(--accent)]/25 bg-[var(--accent)]/8 px-3 py-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--accent)]">
                  {selection.blockType}
                </div>
                <p className="mt-0.5 line-clamp-3 text-xs leading-relaxed text-[var(--ink)]">
                  {selection.text || "Selected figure"}
                </p>
              </div>
              <button
                type="button"
                onClick={onClearSelection}
                className="shrink-0 text-[11px] text-[var(--ink-muted)] hover:text-[var(--ink)]"
              >
                Clear
              </button>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs leading-relaxed text-[var(--ink-muted)]">
            Click a block on the slide, or ask about the whole slide.
          </p>
        )}
      </div>

      <div className="space-y-3 border-b border-[var(--line)] px-4 py-3">
        <div className="flex flex-wrap gap-1.5">
          {actions.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => onAction(a.id)}
              className={`rounded-full px-2.5 py-1 text-[11px] transition ${
                action === a.id
                  ? "bg-[var(--accent)] text-[var(--on-accent)]"
                  : "bg-[var(--surface-inset)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
              }`}
            >
              {a.label}
            </button>
          ))}
          <button
            type="button"
            onClick={onToggleMore}
            className="rounded-full px-2.5 py-1 text-[11px] text-[var(--ink-muted)] underline-offset-2 hover:text-[var(--ink)] hover:underline"
          >
            {showMoreActions ? "Less" : "More"}
          </button>
        </div>

        <textarea
          value={message}
          onChange={(e) => onMessage(e.target.value)}
          rows={2}
          placeholder="Add a question or note…"
          className="w-full resize-none rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2.5 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-muted)] focus:border-[var(--accent)]"
        />

        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-[var(--ink-muted)]">
            Lang
            <input
              value={language}
              onChange={(e) => onLanguage(e.target.value)}
              className="w-12 rounded-md border border-[var(--line)] bg-[var(--surface-inset)] px-1.5 py-1 text-[var(--ink)]"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={onRun}
            className="ml-auto rounded-xl bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--on-accent)] transition hover:opacity-95 disabled:opacity-50"
          >
            {busy ? "Thinking…" : "Ask"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {reply ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--ink-muted)]">
                Reply · {ACTION_LABEL[reply.action] || reply.action}
                {thread.length > 2 ? ` · ${Math.floor(thread.length / 2)} turns` : ""}
              </h4>
              <div className="flex flex-wrap items-center gap-1.5">
                {isReplySaved ? (
                  <span className="rounded-full bg-[var(--accent)]/15 px-2.5 py-1 text-[11px] font-medium text-[var(--accent)]">
                    Saved on slide
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={savingComment}
                    onClick={onSaveComment}
                    className="rounded-full border border-[var(--accent)]/40 bg-[var(--accent)]/12 px-2.5 py-1 text-[11px] font-medium text-[var(--accent)] disabled:opacity-50"
                  >
                    {savingComment ? "Saving…" : "Save as comment"}
                  </button>
                )}
              </div>
            </div>
            {thread.length > 2 && (
              <ol className="space-y-2 border-b border-[var(--line)] pb-3">
                {thread.slice(0, -1).map((turn, i) => (
                  <li
                    key={`${turn.role}-${i}`}
                    className="text-xs leading-relaxed text-[var(--ink-muted)]"
                  >
                    <span className="font-medium text-[var(--ink)]">
                      {turn.role === "user" ? "You" : "Assistant"}:{" "}
                    </span>
                    {turn.role === "assistant" ? (
                      <MarkdownView
                        content={turn.content}
                        className="mt-1 text-[0.85rem] text-[var(--ink-muted)]"
                      />
                    ) : (
                      <span>{turn.content}</span>
                    )}
                  </li>
                ))}
              </ol>
            )}
            <MarkdownView content={reply.reply} />
            {reply.video_prompt && (
              <Link
                href={`/?prompt=${encodeURIComponent(reply.video_prompt)}`}
                className="inline-flex rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/10 px-3 py-1.5 text-xs font-medium text-[var(--accent)]"
              >
                Open in Create
              </Link>
            )}
            <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] p-2.5">
              <label className="block text-[10px] uppercase tracking-[0.12em] text-[var(--ink-muted)]">
                Ask about this reply
              </label>
              <textarea
                value={followUp}
                onChange={(e) => onFollowUp(e.target.value)}
                rows={2}
                placeholder="Follow up on the answer…"
                className="mt-1.5 w-full resize-none rounded-lg border border-[var(--line)] bg-[var(--surface-panel)] px-2.5 py-2 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-muted)] focus:border-[var(--accent)]"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    onRunFollowUp();
                  }
                }}
              />
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  disabled={busy || !followUp.trim()}
                  onClick={onRunFollowUp}
                  className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-[var(--on-accent)] disabled:opacity-50"
                >
                  {busy ? "Thinking…" : "Follow up"}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex h-full min-h-[8rem] items-center justify-center text-center text-xs leading-relaxed text-[var(--ink-muted)]">
            Ask something, then save the answer as a comment on this slide.
          </div>
        )}
      </div>

      <div className="border-t border-[var(--line)]">
        <button
          type="button"
          onClick={onToggleComments}
          className="flex w-full items-center justify-between px-4 py-2.5 text-left text-xs text-[var(--ink-muted)] hover:bg-[var(--surface-inset)]"
        >
          <span>
            Slide comments · {annotations.length}
          </span>
          <span>{showComments ? "Hide" : "Show"}</span>
        </button>
        {showComments && (
          <ul className="max-h-52 space-y-2 overflow-y-auto px-4 pb-3">
            {annotations.length === 0 ? (
              <li className="rounded-xl border border-dashed border-[var(--line)] px-3 py-3 text-center text-[11px] text-[var(--ink-muted)]">
                No saved comments on this slide yet.
              </li>
            ) : (
              annotations
                .slice()
                .reverse()
                .map((a) => (
                  <li
                    key={a.id}
                    className="rounded-xl border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2.5"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--accent)]">
                          {ACTION_LABEL[a.action] || a.action}
                        </div>
                        {a.message && (
                          <div className="mt-1 text-xs text-[var(--ink-muted)]">
                            Q: {a.message}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => onDeleteComment(a.id)}
                        className="shrink-0 text-[11px] text-[var(--danger-ink)] hover:underline"
                      >
                        Remove
                      </button>
                    </div>
                    <div className="mt-2 max-h-40 overflow-y-auto">
                      <MarkdownView
                        content={a.reply}
                        className="text-[0.85rem]"
                      />
                    </div>
                  </li>
                ))
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
