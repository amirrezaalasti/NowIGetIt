"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
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
  type DocumentAskScope,
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

const SLIDE_PRIMARY_ACTIONS: { id: DocumentAskAction; label: string }[] = [
  { id: "explain", label: "Explain" },
  { id: "explain_figure", label: "Figure" },
  { id: "simplify", label: "Simplify" },
  { id: "deepen", label: "Deeper" },
  { id: "quiz", label: "Quiz" },
  { id: "summarize_slide", label: "Summary" },
];

const SLIDE_MORE_ACTIONS: { id: DocumentAskAction; label: string }[] = [
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

const DOC_PRIMARY_ACTIONS: { id: DocumentAskAction; label: string }[] = [
  { id: "summarize_document", label: "Summarize" },
  { id: "explain", label: "Explain" },
  { id: "outline_document", label: "Outline" },
  { id: "key_takeaways", label: "Takeaways" },
  { id: "quiz", label: "Quiz" },
  { id: "deepen", label: "Deeper" },
  { id: "freeform", label: "Ask anything" },
];

const DOC_MORE_ACTIONS: { id: DocumentAskAction; label: string }[] = [
  { id: "critique", label: "Critique" },
  { id: "misconceptions", label: "Misconceptions" },
  { id: "simplify", label: "Simplify" },
  { id: "translate", label: "Translate" },
  { id: "turn_into_video_prompt", label: "Video prompt" },
];

const ACTION_LABEL: Record<string, string> = Object.fromEntries(
  [
    ...SLIDE_PRIMARY_ACTIONS,
    ...SLIDE_MORE_ACTIONS,
    ...DOC_PRIMARY_ACTIONS,
    ...DOC_MORE_ACTIONS,
  ].map((a) => [a.id, a.label]),
);

const FILE_ACCEPT =
  ".pdf,.pptx,.ppt,.docx,.doc,.xlsx,.xls,.html,.htm,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp,.tif,.tiff,.gif,.bmp,.asciidoc,.adoc";

const FORMAT_CHIPS = [
  "PDF",
  "PPTX",
  "DOCX",
  "XLSX",
  "Images",
  "Markdown",
] as const;

const CAPABILITIES = [
  {
    title: "A selection",
    body: "Click a figure, formula, or paragraph and ask about just that block.",
  },
  {
    title: "A slide",
    body: "Explain, simplify, quiz, or pull takeaways from the page in view.",
  },
  {
    title: "The whole deck",
    body: "Summaries, outlines, and critiques across every slide.",
  },
] as const;

export function Understand() {
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);
  const [selection, setSelection] = useState<BlockSelection | null>(null);
  const [action, setAction] = useState<DocumentAskAction>("explain");
  const [askScope, setAskScope] = useState<DocumentAskScope>("slide");
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
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
          setAskScope("slide");
          setAction("explain");
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
      setAskScope("slide");
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
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function onDragOver(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
    if (!uploading) setDragOver(true);
  }

  function onDragLeave(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setDragOver(false);
    }
  }

  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragOver(false);
    if (uploading) return;
    const file = event.dataTransfer.files?.[0] ?? null;
    void onUpload(file);
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
        block_id: askScope === "document" ? null : selection?.blockId || null,
        message,
        language,
        scope: askScope,
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
        block_id:
          askScope === "document"
            ? null
            : reply.block_id || selection?.blockId || null,
        message: q,
        language,
        scope: askScope,
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
        askScope={askScope}
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
          setAskScope("slide");
          setAction("explain");
        }}
        onFocusToggle={() => setFocusMode((v) => !v)}
        onDelete={() => void removeDoc(manifest.doc_id)}
        onAction={setAction}
        onAskScope={(scope) => {
          setAskScope(scope);
          setSelection(null);
          if (scope === "document") {
            setAction("summarize_document");
          } else if (
            action === "summarize_document" ||
            action === "outline_document"
          ) {
            setAction("explain");
          }
        }}
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
    <div
      className={`mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 sm:px-6 ${
        studio ? "py-5 sm:py-6" : "py-8 pb-16 sm:py-10"
      }`}
    >
      {studio ? (
        <>
          {error && (
            <p className="mb-4 whitespace-pre-wrap rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-3 py-2 text-xs text-[var(--danger-ink)]">
              {error}
            </p>
          )}
          {studio}
        </>
      ) : (
        <>
          <header className="animate-rise max-w-2xl">
            <p className="text-[11px] uppercase tracking-[0.16em] text-[var(--ink-muted)]">
              Understand
            </p>
            <h1 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)] sm:text-5xl">
              Interrogate any deck
            </h1>
            <p className="mt-3 max-w-xl text-base leading-relaxed text-[var(--ink-muted)]">
              Upload a lecture PDF or slide deck. Ask about a selection, a slide,
              or the whole document — summaries, explanations, outlines, quizzes,
              and more.
            </p>
          </header>

          <section className="animate-rise-delay mt-8">
            <div className="rounded-2xl has-[:focus-visible]:shadow-[0_0_0_3px_var(--glow)]">
              <input
                ref={fileInputRef}
                id="understand-file"
                type="file"
                className="sr-only"
                accept={FILE_ACCEPT}
                disabled={uploading}
                onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
              />
              <label
                htmlFor="understand-file"
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                aria-busy={uploading}
                className={`group relative flex min-h-[16rem] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed px-6 py-10 text-center transition ${
                  dragOver
                    ? "border-[var(--accent)] bg-[var(--accent)]/8 shadow-[0_0_0_3px_var(--glow)]"
                    : "border-[var(--line)] bg-[var(--surface)]/80 hover:border-[var(--accent)]/45 hover:bg-[var(--surface)] hover:shadow-[0_0_0_3px_var(--glow)]"
                } ${uploading ? "pointer-events-none cursor-wait" : ""}`}
              >
              <span
                className={`flex h-12 w-12 items-center justify-center rounded-2xl border transition ${
                  dragOver
                    ? "border-[var(--accent)]/40 bg-[var(--accent)]/15 text-[var(--accent)]"
                    : "border-[var(--line)] bg-[var(--surface-inset)] text-[var(--ink-muted)] group-hover:border-[var(--accent)]/35 group-hover:text-[var(--accent)]"
                }`}
                aria-hidden
              >
                {uploading ? (
                  <span className="h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                ) : (
                  <svg
                    width="22"
                    height="22"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 17V3" />
                    <path d="m7 8 5-5 5 5" />
                    <path d="M5 21h14" />
                  </svg>
                )}
              </span>
              <span className="mt-4 font-[family-name:var(--font-display)] text-xl tracking-tight text-[var(--ink)] sm:text-2xl">
                {uploading
                  ? "Converting your deck"
                  : dragOver
                    ? "Drop to upload"
                    : "Drop a lecture here"}
              </span>
              <span className="mt-1.5 max-w-sm text-sm leading-relaxed text-[var(--ink-muted)]">
                {uploading
                  ? status || "Uploading and converting page by page…"
                  : "or browse a PDF, slide deck, document, or image"}
              </span>
              {!uploading && (
                <span className="mt-6 inline-flex rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] transition group-hover:brightness-110">
                  Browse files
                </span>
              )}
              {uploading && (
                <span className="mt-6 flex items-center gap-1.5 text-[var(--accent)]">
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce"
                    style={{ animationDelay: "0ms" }}
                  />
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce"
                    style={{ animationDelay: "150ms" }}
                  />
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)] animate-bounce"
                    style={{ animationDelay: "300ms" }}
                  />
                </span>
              )}
              <span className="mt-6 flex flex-wrap items-center justify-center gap-1.5">
                {FORMAT_CHIPS.map((chip) => (
                  <span
                    key={chip}
                    className="rounded-full border border-[var(--line)] bg-[var(--surface-inset)] px-2.5 py-0.5 text-[11px] text-[var(--ink-muted)]"
                  >
                    {chip}
                  </span>
                ))}
              </span>
            </label>
            </div>
            {error && (
              <p className="mt-3 whitespace-pre-wrap rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-3 py-2 text-xs text-[var(--danger-ink)]">
                {error}
              </p>
            )}
          </section>

          {docs.length > 0 ? (
            <section className="animate-rise-delay-2 mt-10 space-y-4">
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="font-[family-name:var(--font-display)] text-xl tracking-tight text-[var(--ink)]">
                  Your decks
                </h2>
                <p className="text-xs text-[var(--ink-muted)]">
                  {docs.length}
                </p>
              </div>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {docs.map((d) => {
                  const convertingDoc = d.status === "converting";
                  return (
                    <li key={d.doc_id}>
                      <article className="group flex h-full flex-col rounded-2xl border border-[var(--line)] bg-[var(--surface)]/80 p-4 transition hover:border-[var(--accent)]/40 hover:bg-[var(--surface)]">
                        <button
                          type="button"
                          onClick={() => void openDoc(d.doc_id)}
                          className="flex min-w-0 flex-1 flex-col text-left"
                        >
                          <span
                            className={`inline-flex w-fit rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] ${
                              convertingDoc
                                ? "bg-[var(--accent-hot)]/15 text-[var(--accent-hot)]"
                                : "bg-[var(--accent)]/12 text-[var(--accent)]"
                            }`}
                          >
                            {d.status || "ready"}
                          </span>
                          <span className="mt-2 line-clamp-2 font-[family-name:var(--font-display)] text-lg leading-snug tracking-tight text-[var(--ink)]">
                            {d.title || d.source_filename || d.doc_id}
                          </span>
                          <span className="mt-1.5 text-xs text-[var(--ink-muted)]">
                            {d.slide_count ?? 0}{" "}
                            {(d.slide_count ?? 0) === 1 ? "slide" : "slides"}
                          </span>
                        </button>
                        <div className="mt-4 flex items-center justify-between gap-2 border-t border-[var(--line)] pt-3">
                          <button
                            type="button"
                            onClick={() => void openDoc(d.doc_id)}
                            className="text-xs font-medium text-[var(--accent)] transition hover:brightness-110"
                          >
                            Open
                          </button>
                          <button
                            type="button"
                            disabled={deletingId === d.doc_id}
                            onClick={() => void removeDoc(d.doc_id)}
                            className="rounded-md px-2 py-1 text-xs text-[var(--danger-ink)] transition hover:bg-[var(--danger-bg)] disabled:opacity-40"
                          >
                            {deletingId === d.doc_id ? "…" : "Delete"}
                          </button>
                        </div>
                      </article>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : (
            <ul className="animate-rise-delay-2 mt-8 grid gap-3 sm:grid-cols-3">
              {CAPABILITIES.map((item) => (
                <li
                  key={item.title}
                  className="rounded-2xl border border-[var(--line)] bg-[var(--surface)]/60 px-4 py-4"
                >
                  <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--accent)]">
                    Ask about
                  </p>
                  <p className="mt-1.5 font-[family-name:var(--font-display)] text-lg tracking-tight text-[var(--ink)]">
                    {item.title}
                  </p>
                  <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-muted)]">
                    {item.body}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
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
  askScope: DocumentAskScope;
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
  onAskScope: (scope: DocumentAskScope) => void;
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
    askScope,
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
    onAskScope,
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
      <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)]/80 px-4 py-3 backdrop-blur-sm">
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

        <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface-panel)] shadow-[0_12px_40px_rgba(0,0,0,0.08)]">
          <AssistantPanel
            selection={selection}
            action={action}
            askScope={askScope}
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
            onAskScope={onAskScope}
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
  askScope: DocumentAskScope;
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
  onAskScope: (scope: DocumentAskScope) => void;
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
    askScope,
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
    onAskScope,
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

  const primary =
    askScope === "document" ? DOC_PRIMARY_ACTIONS : SLIDE_PRIMARY_ACTIONS;
  const more = askScope === "document" ? DOC_MORE_ACTIONS : SLIDE_MORE_ACTIONS;
  const actions = showMoreActions ? [...primary, ...more] : primary;

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

        <div className="mt-2.5 flex rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-0.5">
          <button
            type="button"
            onClick={() => onAskScope("slide")}
            className={`flex-1 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition ${
              askScope === "slide"
                ? "bg-[var(--surface-panel)] text-[var(--ink)] shadow-sm"
                : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
            }`}
          >
            This slide
          </button>
          <button
            type="button"
            onClick={() => onAskScope("document")}
            className={`flex-1 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition ${
              askScope === "document"
                ? "bg-[var(--surface-panel)] text-[var(--ink)] shadow-sm"
                : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
            }`}
          >
            Whole document
          </button>
        </div>

        {askScope === "document" ? (
          <p className="mt-2 text-xs leading-relaxed text-[var(--ink-muted)]">
            Ask about the entire document — summary, outline, explanation, and
            more.
          </p>
        ) : selection ? (
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
          placeholder={
            askScope === "document"
              ? "Ask about the whole document…"
              : "Add a question or note…"
          }
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
            {askScope === "document"
              ? "Ask about the whole document, then save the answer as a comment on this slide."
              : "Ask something, then save the answer as a comment on this slide."}
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
