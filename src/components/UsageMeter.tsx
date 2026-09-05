"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  ensureApiToken,
  fetchMe,
  setStorageMode,
  type UsageSnapshot,
} from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function Bar({ used, limit, label }: { used: number; limit: number; label: string }) {
  const unlimited = limit <= 0;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100));
  const hot = !unlimited && pct >= 90;
  const value =
    label.startsWith("Storage")
      ? unlimited
        ? formatBytes(used)
        : `${formatBytes(used)} / ${formatBytes(limit)}`
      : label.startsWith("Tokens")
        ? unlimited
          ? formatTokens(used)
          : `${formatTokens(used)} / ${formatTokens(limit)}`
        : unlimited
          ? String(used)
          : `${used} / ${limit}`;
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-[var(--ink-muted)]">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      {unlimited ? null : (
        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-strong)]">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${pct}%`,
              background: hot ? "var(--accent-hot)" : "var(--accent)",
            }}
          />
        </div>
      )}
    </div>
  );
}

type Props = {
  /** Compact bars for the account menu (default). */
  variant?: "menu" | "inline";
};

const FETCH_TIMEOUT_MS = 12_000;

type AccountState = {
  usage: UsageSnapshot | null;
  storageMode: "local" | "mongo" | "supabase";
  supabaseAvailable: boolean;
};

export function UsageMeter({ variant = "menu" }: Props) {
  const { status } = useSession();
  const [account, setAccount] = useState<AccountState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (status !== "authenticated") {
      setAccount(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    setLoading(true);
    setError(null);

    void (async () => {
      try {
        await ensureApiToken();
        const me = await fetchMe(controller.signal);
        if (cancelled) return;
        setAccount({
          usage: me.usage,
          storageMode: me.storage_mode || (me.supabase_configured ? "supabase" : "local"),
          supabaseAvailable: Boolean(me.supabase_available),
        });
        setError(null);
      } catch (err) {
        if (cancelled) return;
        if ((err as Error).name === "AbortError") {
          setError("Usage timed out — API busy");
        } else {
          setError((err as Error).message || "Failed to load usage");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [status]);

  async function onToggle(mode: "local" | "mongo" | "supabase") {
    if (!account || saving || mode === account.storageMode) return;
    setSaving(true);
    setError(null);
    try {
      const result = await setStorageMode(mode);
      setAccount((prev) =>
        prev
          ? {
              ...prev,
              storageMode: result.storage_mode,
              supabaseAvailable: result.supabase_available,
            }
          : prev,
      );
    } catch (err) {
      setError((err as Error).message || "Could not switch storage");
    } finally {
      setSaving(false);
    }
  }

  if (status !== "authenticated") return null;

  if (loading && !account) {
    return (
      <p className="text-xs text-[var(--ink-muted)]">Loading account…</p>
    );
  }

  if (error && !account) {
    return <p className="text-xs text-[var(--ink-muted)]">{error}</p>;
  }

  if (!account) return null;

  const local = account.storageMode === "local";
  const mongo = account.storageMode === "mongo";
  const usage = account.usage;
  const canUseCloud = account.supabaseAvailable;
  const unlimited = local || mongo || Boolean(usage?.unlimited);

  return (
    <div className={variant === "inline" ? "w-full max-w-xs space-y-2.5" : "space-y-2.5"}>
      <p className="text-[10px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
        {mongo ? "MongoDB Atlas" : local ? "SQLite + files" : "This month"}
      </p>
      {mongo ? (
        <p className="text-xs leading-relaxed text-[var(--ink-muted)]">
          Library and usage live in MongoDB. Videos stay as files on disk.
          Monthly quotas are off.
        </p>
      ) : local ? (
        <p className="text-xs leading-relaxed text-[var(--ink-muted)]">
          Library, usage, and videos are stored on this computer. No cloud
          database. Monthly quotas are off.
        </p>
      ) : null}
      {usage ? (
        <>
          <Bar
            label="Generations"
            used={usage.llm.requests_used}
            limit={unlimited ? 0 : usage.llm.requests_limit}
          />
          <Bar
            label="Tokens"
            used={usage.llm.tokens_used}
            limit={unlimited ? 0 : usage.llm.tokens_limit}
          />
          <Bar
            label="Storage"
            used={usage.storage.bytes_used}
            limit={unlimited ? 0 : usage.storage.bytes_limit}
          />
        </>
      ) : null}
      {canUseCloud ? (
        <label className="flex cursor-pointer items-start gap-2 pt-1 text-xs text-[var(--ink-muted)]">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={local}
            disabled={saving}
            onChange={(e) => onToggle(e.target.checked ? "local" : "supabase")}
          />
          <span>Save on this computer only (skip Supabase)</span>
        </label>
      ) : mongo ? null : (
        <p className="text-[10px] leading-relaxed text-[var(--ink-muted)]">
          Cloud database is off. Jobs are stored in SQLite plus local files.
        </p>
      )}
      {error ? (
        <p className="text-[10px] text-[var(--ink-muted)]">{error}</p>
      ) : null}
    </div>
  );
}
