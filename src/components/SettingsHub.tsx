"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import {
  deleteProviderKey,
  disconnectYoutube,
  ensureApiToken,
  fetchKeys,
  fetchYoutubeStatus,
  saveProviderKey,
  saveProviderPrefs,
  validateProviderKey,
  youtubeConnectUrl,
  type KeysState,
  type ProviderCatalogItem,
  type YoutubeStatus,
} from "@/lib/api";

function SignInGate({ title, body }: { title: string; body: string }) {
  return (
    <section className="relative mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-6 py-16 text-center">
      <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
        {title}
      </h1>
      <p className="mx-auto mt-4 max-w-md text-sm text-[var(--ink-muted)]">{body}</p>
      <Link
        href="/login?callbackUrl=/settings"
        className="mt-10 inline-flex self-center rounded-full bg-[var(--accent)] px-8 py-3.5 text-base font-semibold text-[var(--on-accent)] transition hover:brightness-110"
      >
        Continue with Google
      </Link>
    </section>
  );
}

export function SettingsHub() {
  const { status } = useSession();
  const [keys, setKeys] = useState<KeysState | null>(null);
  const [youtube, setYoutube] = useState<YoutubeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(async () => {
    await ensureApiToken();
    const [k, y] = await Promise.all([fetchKeys(), fetchYoutubeStatus()]);
    setKeys(k);
    setYoutube(y);
  }, []);

  useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    void reload().catch((err) => {
      if (!cancelled) setError((err as Error).message);
    });
    return () => {
      cancelled = true;
    };
  }, [status, reload]);

  if (status === "loading") {
    return (
      <section className="mx-auto w-full max-w-3xl px-6 py-16">
        <p className="text-sm text-[var(--ink-muted)]">Checking session…</p>
      </section>
    );
  }

  if (status !== "authenticated") {
    return (
      <SignInGate
        title="Settings"
        body="Sign in to add your own provider keys and connect YouTube."
      />
    );
  }

  return (
    <section className="relative mx-auto w-full max-w-3xl px-6 py-12">
      <p className="text-sm text-[var(--ink-muted)]">Account</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
        Settings
      </h1>
      <p className="mt-3 max-w-2xl text-[var(--ink-muted)]">
        Bring your own API keys for any OpenAI-compatible provider, then connect
        YouTube so paper pipelines can publish explainer videos to your channel.
      </p>

      {error ? (
        <p className="mt-6 rounded-xl border border-[var(--danger-line)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-ink)]">
          {error}
        </p>
      ) : null}

      <YoutubeCard
        status={youtube}
        busy={busy}
        setBusy={setBusy}
        setError={setError}
        onChange={setYoutube}
      />

      <ProvidersCard
        state={keys}
        busy={busy}
        setBusy={setBusy}
        setError={setError}
        onChange={setKeys}
      />
    </section>
  );
}

function YoutubeCard({
  status,
  busy,
  setBusy,
  setError,
  onChange,
}: {
  status: YoutubeStatus | null;
  busy: string | null;
  setBusy: (v: string | null) => void;
  setError: (v: string | null) => void;
  onChange: (v: YoutubeStatus) => void;
}) {
  async function connect() {
    setBusy("youtube");
    setError(null);
    try {
      const { url } = await youtubeConnectUrl(window.location.origin, "/settings");
      window.location.href = url;
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
    }
  }

  async function disconnect() {
    setBusy("youtube");
    setError(null);
    try {
      onChange(await disconnectYoutube());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-10 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
      <h2 className="text-sm font-semibold text-[var(--ink)]">YouTube</h2>
      <p className="mt-2 text-sm text-[var(--ink-muted)]">
        A separate Google grant for upload. Login stays as-is — this only
        publishes <code className="text-[var(--ink)]">final.mp4</code> to your
        channel.
      </p>
      {status?.connected ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-[var(--ink)]">
            Connected
            {status.channel_title ? (
              <span className="text-[var(--ink-muted)]">
                {" "}
                · {status.channel_title}
              </span>
            ) : null}
          </p>
          <button
            type="button"
            disabled={busy === "youtube"}
            onClick={() => void disconnect()}
            className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:text-[var(--ink)] disabled:opacity-50"
          >
            Disconnect
          </button>
        </div>
      ) : (
        <div className="mt-4">
          {status && !status.configured ? (
            <p className="mb-3 text-sm text-[var(--accent-hot)]">
              Google OAuth is not configured on this server. Set{" "}
              <code>AUTH_GOOGLE_ID</code> and <code>AUTH_GOOGLE_SECRET</code>,
              enable YouTube Data API v3, and add the redirect URI{" "}
              <code>/api/youtube/callback</code>.
            </p>
          ) : null}
          <button
            type="button"
            disabled={busy === "youtube" || status?.configured === false}
            onClick={() => void connect()}
            className="rounded-full bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-[var(--on-accent)] transition hover:brightness-110 disabled:opacity-50"
          >
            Connect YouTube
          </button>
        </div>
      )}
    </section>
  );
}

function ProvidersCard({
  state,
  busy,
  setBusy,
  setError,
  onChange,
}: {
  state: KeysState | null;
  busy: string | null;
  setBusy: (v: string | null) => void;
  setError: (v: string | null) => void;
  onChange: (v: KeysState) => void;
}) {
  const [selected, setSelected] = useState("openrouter");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  const provider: ProviderCatalogItem | undefined = state?.providers.find(
    (item) => item.id === selected,
  );
  const saved = state?.keys.find((item) => item.provider === selected);

  async function save() {
    if (!provider) return;
    setBusy("save");
    setError(null);
    try {
      await saveProviderKey(
        selected,
        apiKey,
        selected === "custom" ? baseUrl : baseUrl || undefined,
      );
      setApiKey("");
      onChange(await fetchKeys());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function validate() {
    setBusy("validate");
    setError(null);
    try {
      await validateProviderKey(
        selected,
        apiKey || undefined,
        selected === "custom" ? baseUrl : baseUrl || undefined,
      );
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
      return;
    }
    setBusy(null);
  }

  async function remove() {
    setBusy("delete");
    setError(null);
    try {
      onChange(await deleteProviderKey(selected));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function setPref(patch: { llm_provider?: string; tts_provider?: string }) {
    setBusy("prefs");
    setError(null);
    try {
      onChange(await saveProviderPrefs(patch));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="mt-8 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
      <h2 className="text-sm font-semibold text-[var(--ink)]">
        Bring your own key
      </h2>
      <p className="mt-2 text-sm text-[var(--ink-muted)]">
        Keys are encrypted at rest and never sent back in full. If you save a
        key, that provider is billed instead of the shared platform quota.
      </p>

      {state ? (
        <p className="mt-3 text-xs text-[var(--ink-muted)]">
          LLM: {state.active.llm_ready ? state.active.llm_model : "not configured"}
          {state.active.using_own_llm_key ? " (your key)" : " (platform)"}
          {" · "}
          TTS: {state.active.tts_ready ? state.active.tts_model : "not configured"}
          {state.active.using_own_tts_key ? " (your key)" : " (platform)"}
        </p>
      ) : (
        <p className="mt-3 text-sm text-[var(--ink-muted)]">Loading keys…</p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm text-[var(--ink-muted)]">
          LLM provider
          <select
            className="mt-1 w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-[var(--ink)]"
            value={state?.prefs.llm_provider || "openrouter"}
            disabled={!state || busy === "prefs"}
            onChange={(e) => void setPref({ llm_provider: e.target.value })}
          >
            {(state?.providers || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-[var(--ink-muted)]">
          TTS provider
          <select
            className="mt-1 w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-[var(--ink)]"
            value={state?.prefs.tts_provider || "openrouter"}
            disabled={!state || busy === "prefs"}
            onChange={(e) => void setPref({ tts_provider: e.target.value })}
          >
            {(state?.providers || [])
              .filter((item) => item.kind === "both" || item.kind === "tts")
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
          </select>
        </label>
      </div>

      <div className="mt-6">
        <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
          Saved keys
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(state?.providers || []).map((item) => {
            const isOn = state?.keys.some((k) => k.provider === item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setSelected(item.id);
                  setBaseUrl(item.base_url);
                }}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  selected === item.id
                    ? "border-[var(--accent)] bg-[var(--surface-strong)] text-[var(--ink)]"
                    : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink)]"
                }`}
              >
                {item.label}
                {isOn ? " · saved" : ""}
              </button>
            );
          })}
        </div>
      </div>

      {provider ? (
        <div className="mt-5 space-y-3">
          <p className="text-sm text-[var(--ink-muted)]">{provider.notes}</p>
          {provider.docs_url ? (
            <a
              href={provider.docs_url}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-[var(--accent)] underline-offset-2 hover:underline"
            >
              Get an API key
            </a>
          ) : null}
          {saved ? (
            <p className="text-sm text-[var(--ink)]">
              Saved key {saved.hint}
            </p>
          ) : (
            <p className="text-sm text-[var(--ink-muted)]">No key saved yet.</p>
          )}
          <input
            type="password"
            autoComplete="off"
            placeholder={provider.placeholder || "API key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          />
          {(selected === "custom" || provider.base_url) && (
            <input
              type="url"
              placeholder={provider.base_url || "https://api.example.com/v1"}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
            />
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!apiKey || busy !== null}
              onClick={() => void save()}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-[var(--on-accent)] disabled:opacity-50"
            >
              Save key
            </button>
            <button
              type="button"
              disabled={busy !== null || (!apiKey && !saved)}
              onClick={() => void validate()}
              className="rounded-lg border border-[var(--line)] px-4 py-2 text-sm text-[var(--ink-muted)] hover:text-[var(--ink)] disabled:opacity-50"
            >
              Test
            </button>
            {saved ? (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void remove()}
                className="rounded-lg border border-[var(--danger-line)] px-4 py-2 text-sm text-[var(--danger-ink)] disabled:opacity-50"
              >
                Remove
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
