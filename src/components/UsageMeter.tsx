"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { ensureApiToken, fetchMe, type UsageSnapshot } from "@/lib/api";

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
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const hot = pct >= 90;
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-[var(--ink-muted)]">
        <span>{label}</span>
        <span>
          {label.startsWith("Storage")
            ? `${formatBytes(used)} / ${formatBytes(limit)}`
            : label.startsWith("Tokens")
              ? `${formatTokens(used)} / ${formatTokens(limit)}`
              : `${used} / ${limit}`}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            background: hot ? "var(--accent-hot)" : "var(--accent)",
          }}
        />
      </div>
    </div>
  );
}

export function UsageMeter() {
  const { status } = useSession();
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "authenticated") {
      setUsage(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await ensureApiToken();
        const me = await fetchMe();
        if (!cancelled) {
          setUsage(me.usage);
          setError(
            me.supabase_configured
              ? null
              : "Supabase not configured on API (set SUPABASE_SERVICE_ROLE_KEY)",
          );
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  if (status !== "authenticated") return null;

  if (error && !usage) {
    return (
      <p className="text-xs text-[var(--ink-muted)]">{error}</p>
    );
  }

  if (!usage) return null;

  return (
    <div className="w-full max-w-xs space-y-2.5 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-3">
      <p className="text-[10px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
        This month
      </p>
      <Bar
        label="Generations"
        used={usage.llm.requests_used}
        limit={usage.llm.requests_limit}
      />
      <Bar
        label="Tokens"
        used={usage.llm.tokens_used}
        limit={usage.llm.tokens_limit}
      />
      <Bar
        label="Storage"
        used={usage.storage.bytes_used}
        limit={usage.storage.bytes_limit}
      />
    </div>
  );
}
