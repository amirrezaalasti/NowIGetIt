"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  ensureApiToken,
  extractSourceFile,
  listSourceLibrary,
  type SourceLibraryItem,
} from "@/lib/api";

export const SOURCE_FILE_ACCEPT =
  ".pdf,.pptx,.ppt,.docx,.doc,.xlsx,.xls,.html,.htm,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp,.tif,.tiff,.gif,.bmp,.asciidoc,.adoc";

export type AttachedSource = {
  localKey: string;
  id: string;
  title: string;
  filename: string;
  charCount: number;
  kind: "source" | "document";
  status: "uploading" | "ready" | "error";
  error?: string;
};

const MAX_ATTACHMENTS = 6;

function formatChars(n: number): string {
  if (n < 1000) return `${n} chars`;
  return `${Math.round(n / 100) / 10}k chars`;
}

export function readySourceIds(items: AttachedSource[]): string[] {
  return items.filter((item) => item.status === "ready" && item.id).map((item) => item.id);
}

export function SourceAttachments({
  items,
  onChange,
  disabled = false,
}: {
  items: AttachedSource[];
  onChange: (
    items: AttachedSource[] | ((prev: AttachedSource[]) => AttachedSource[]),
  ) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [library, setLibrary] = useState<SourceLibraryItem[] | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);

  useEffect(() => {
    if (library !== null) return;
    let cancelled = false;
    void ensureApiToken()
      .then(() => listSourceLibrary(24))
      .then((rows) => {
        if (!cancelled) setLibrary(rows);
      })
      .catch((err) => {
        if (!cancelled) {
          setLibrary([]);
          setLibraryError((err as Error).message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [library]);

  const full = items.length >= MAX_ATTACHMENTS;
  const busy = items.some((item) => item.status === "uploading");

  async function addFiles(files: FileList | File[] | null) {
    if (!files || disabled) return;
    const incoming = Array.from(files);
    if (!incoming.length) return;
    await ensureApiToken();
    const placeholders: AttachedSource[] = incoming.map((file) => ({
      localKey: `tmp_${crypto.randomUUID()}`,
      id: "",
      title: file.name,
      filename: file.name,
      charCount: 0,
      kind: "source",
      status: "uploading",
    }));
    const room = Math.max(0, MAX_ATTACHMENTS - items.length);
    const accepted = placeholders.slice(0, room);
    const filesForAccepted = incoming.slice(0, accepted.length);
    if (!accepted.length) return;
    onChange((prev) => [...prev, ...accepted].slice(0, MAX_ATTACHMENTS));
    const settled = await Promise.all(
      filesForAccepted.map(async (file, index) => {
        const placeholder = accepted[index];
        try {
          const extracted = await extractSourceFile(file);
          const kind: AttachedSource["kind"] =
            extracted.kind === "document" ? "document" : "source";
          const ready: AttachedSource = {
            ...placeholder,
            id: extracted.id,
            title: extracted.title || file.name,
            filename: extracted.filename || file.name,
            charCount: extracted.char_count,
            kind,
            status: "ready",
          };
          return ready;
        } catch (err) {
          const failed: AttachedSource = {
            ...placeholder,
            status: "error",
            error: (err as Error).message,
          };
          return failed;
        }
      }),
    );
    onChange((current) => {
      const next = [...current];
      for (const done of settled) {
        const idx = next.findIndex((item) => item.localKey === done.localKey);
        if (idx >= 0) next[idx] = done;
        else next.push(done);
      }
      return next;
    });
  }

  function attachLibraryItem(item: SourceLibraryItem) {
    if (disabled) return;
    onChange((prev) => {
      if (prev.length >= MAX_ATTACHMENTS) return prev;
      if (prev.some((existing) => existing.id === item.id)) return prev;
      return [
        ...prev,
        {
          localKey: item.id,
          id: item.id,
          title: item.title || item.filename || item.id,
          filename: item.filename || item.title || item.id,
          charCount: 0,
          kind: item.kind === "document" ? "document" : "source",
          status: "ready",
        },
      ];
    });
  }

  function remove(localKey: string) {
    onChange((prev) => prev.filter((item) => item.localKey !== localKey));
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault();
    if (!disabled && !full) setDragOver(true);
  }

  function onDragLeave() {
    setDragOver(false);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragOver(false);
    void addFiles(event.dataTransfer.files);
  }

  const unusedLibrary = (library || []).filter(
    (row) => !items.some((item) => item.id === row.id),
  );

  return (
    <div className="mt-4">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={SOURCE_FILE_ACCEPT}
        className="sr-only"
        disabled={disabled || full}
        onChange={(event) => {
          void addFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`flex flex-wrap items-center gap-3 rounded-xl border border-dashed px-4 py-3 transition ${
          dragOver
            ? "border-[var(--accent)] bg-[var(--accent)]/8"
            : "border-[var(--line)] bg-[var(--surface-inset)]/60"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <button
          type="button"
          disabled={disabled || full || busy}
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--ink)] transition enabled:hover:border-[var(--accent)]/50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M12 17V3" />
            <path d="m7 8 5-5 5 5" />
            <path d="M5 21h14" />
          </svg>
          Attach files
        </button>
        {unusedLibrary.length ? (
          <label className="flex min-w-[10rem] flex-1 items-center gap-2 text-sm text-[var(--ink-muted)]">
            <span className="sr-only">From library</span>
            <select
              disabled={disabled || full}
              defaultValue=""
              onChange={(event) => {
                const id = event.target.value;
                const picked = unusedLibrary.find((row) => row.id === id);
                if (picked) attachLibraryItem(picked);
                event.target.value = "";
              }}
              className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] px-2 py-1.5 text-sm text-[var(--ink)] outline-none disabled:opacity-40"
            >
              <option value="">From library…</option>
              {unusedLibrary.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title || row.filename || row.id}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <p className="text-xs text-[var(--ink-muted)]">
          PDF, slides, notes, or images. Prompt can be empty.
        </p>
      </div>
      {libraryError ? (
        <p className="mt-2 text-xs text-[var(--ink-muted)]">{libraryError}</p>
      ) : null}
      {items.length ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {items.map((item) => (
            <li
              key={item.localKey}
              className="inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3 py-1 text-sm"
            >
              <span className="truncate text-[var(--ink)]">
                {item.filename || item.title}
              </span>
              <span className="shrink-0 text-[11px] text-[var(--ink-muted)]">
                {item.status === "uploading"
                  ? "reading…"
                  : item.status === "error"
                    ? "failed"
                    : item.charCount
                      ? formatChars(item.charCount)
                      : item.kind === "document"
                        ? "library"
                        : "ready"}
              </span>
              <button
                type="button"
                onClick={() => remove(item.localKey)}
                disabled={disabled}
                className="text-[var(--ink-muted)] hover:text-[var(--ink)]"
                aria-label={`Remove ${item.filename}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {items.some((item) => item.status === "error") ? (
        <p className="mt-2 text-xs text-[var(--danger-ink)]">
          {items
            .filter((item) => item.status === "error")
            .map((item) => item.error || `${item.filename} could not be read`)
            .join(" · ")}
        </p>
      ) : null}
    </div>
  );
}
