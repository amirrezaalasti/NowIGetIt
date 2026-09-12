"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  clearOpenRouterKey,
  ensureApiToken,
  fetchMe,
  saveOpenRouterKey,
  type OpenRouterKeyStatus,
} from "@/lib/api";

/** Save / clear the signed-in user's OpenRouter API key (BYOK). */
export function OpenRouterKeyPanel() {
  const { status } = useSession();
  const [keyStatus, setKeyStatus] = useState<OpenRouterKeyStatus | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated") {
      setKeyStatus(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        await ensureApiToken();
        const me = await fetchMe();
        if (cancelled) return;
        setKeyStatus(
          me.openrouter_key || {
            configured: false,
            masked_key: null,
            fingerprint: null,
          },
        );
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || "Could not load API key status");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  if (status !== "authenticated") return null;

  async function onSave() {
    const value = draft.trim();
    if (!value || saving) return;
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const result = await saveOpenRouterKey(value);
      setKeyStatus(result);
      setDraft("");
      setSavedMsg("Saved — only your key will be used from now on.");
    } catch (err) {
      setError((err as Error).message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function onClear() {
    if (saving) return;
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const result = await clearOpenRouterKey();
      setKeyStatus(result);
      setSavedMsg("Removed — using the server key again.");
    } catch (err) {
      setError((err as Error).message || "Could not remove key");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2 border-t border-[var(--line)] px-3 py-3">
      <p className="text-[10px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
        OpenRouter API key
      </p>
      <p className="text-xs leading-relaxed text-[var(--ink-muted)]">
        Use your own key for planning, codegen, review, and narration. While it
        is saved, the server API key is not used for your jobs. Get a key at{" "}
        <a
          href="https://openrouter.ai/keys"
          target="_blank"
          rel="noreferrer"
          className="underline decoration-[var(--line)] underline-offset-2 hover:text-[var(--ink)]"
        >
          openrouter.ai/keys
        </a>
        .
      </p>
      {loading ? (
        <p className="text-xs text-[var(--ink-muted)]">Loading…</p>
      ) : keyStatus?.configured ? (
        <p className="text-xs text-[var(--ink)]">
          Active: <span className="font-mono">{keyStatus.masked_key}</span>
        </p>
      ) : (
        <p className="text-xs text-[var(--ink-muted)]">
          No personal key — using the server key.
        </p>
      )}
      <input
        type="password"
        autoComplete="off"
        spellCheck={false}
        placeholder="sk-or-v1-…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--ink)] outline-none placeholder:text-[var(--ink-muted)] focus:border-[var(--accent)]"
      />
      <div className="flex gap-2">
        <button
          type="button"
          disabled={saving || !draft.trim()}
          onClick={() => void onSave()}
          className="rounded-lg bg-[var(--accent)] px-2.5 py-1.5 text-xs font-medium text-[var(--bg)] transition disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save key"}
        </button>
        {keyStatus?.configured ? (
          <button
            type="button"
            disabled={saving}
            onClick={() => void onClear()}
            className="rounded-lg border border-[var(--line)] px-2.5 py-1.5 text-xs text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)] disabled:opacity-40"
          >
            Remove
          </button>
        ) : null}
      </div>
      {savedMsg ? (
        <p className="text-[10px] text-[var(--accent)]">{savedMsg}</p>
      ) : null}
      {error ? (
        <p className="text-[10px] text-[var(--accent-hot)]">{error}</p>
      ) : null}
    </div>
  );
}
