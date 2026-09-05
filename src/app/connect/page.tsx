import { headers } from "next/headers";
import { AppHeader } from "@/components/AppHeader";
import { googleAuthConfigured } from "@/lib/mcp/oauth";

export const dynamic = "force-dynamic";

async function connectorUrl(): Promise<string> {
  const h = await headers();
  const host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
  const proto =
    h.get("x-forwarded-proto") ||
    (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  return `${proto}://${host}/api/mcp`;
}

async function googleCallback(): Promise<string> {
  const h = await headers();
  const host = h.get("x-forwarded-host") || h.get("host") || "localhost:3000";
  const proto =
    h.get("x-forwarded-proto") ||
    (host.includes("localhost") || host.startsWith("127.") ? "http" : "https");
  return `${proto}://${host}/api/auth/callback/google`;
}

export default async function ConnectPage() {
  const url = await connectorUrl();
  const callback = await googleCallback();
  const oauthReady = googleAuthConfigured();

  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 mx-auto w-full max-w-2xl px-6 py-12">
        <p className="text-sm text-[var(--ink-muted)]">ChatGPT · Claude · Cursor</p>
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
          Use Now I Get It in chat
        </h1>
        <p className="mt-4 text-[var(--ink-muted)]">
          Add this connector once and sign in with Google when the chat app asks. Videos
          land in your Library on this site — no API key to paste.
        </p>

        <section className="mt-8 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
          <h2 className="text-sm font-semibold text-[var(--ink)]">Connector URL</h2>
          <code className="mt-3 block break-all rounded-xl bg-[var(--surface-inset)] px-3 py-2 text-sm text-[var(--accent)]">
            {url}
          </code>
          {oauthReady ? (
            <p className="mt-3 text-sm text-[var(--ink-muted)]">
              Auth is <strong className="text-[var(--ink)]">OAuth</strong>. Leave client ID
              and secret empty (register automatically). Do not paste a bearer token.
            </p>
          ) : (
            <p className="mt-3 text-sm text-[var(--ink-muted)]">
              Google OAuth is not configured on this server, so chat clients cannot sign
              you in. Set <code>AUTH_GOOGLE_ID</code> and <code>AUTH_GOOGLE_SECRET</code>.
            </p>
          )}
        </section>

        <section className="mt-8 rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 text-sm text-[var(--ink-muted)]">
          <h2 className="text-sm font-semibold text-[var(--ink)]">Google redirect URI</h2>
          <p className="mt-2">
            In Google Cloud Console → Credentials → your OAuth client, add:
          </p>
          <code className="mt-3 block break-all rounded-xl bg-[var(--surface-inset)] px-3 py-2 text-[var(--accent)]">
            {callback}
          </code>
        </section>

        <section className="mt-8 space-y-4 text-sm leading-6 text-[var(--ink-muted)]">
          <h2 className="text-base font-semibold text-[var(--ink)]">ChatGPT</h2>
          <ol className="list-decimal space-y-2 pl-5">
            <li>Settings → Security and login → turn on Developer mode.</li>
            <li>Open Plugins / Connectors → add a custom connector.</li>
            <li>
              Paste the URL above. Auth: OAuth. No client ID or token. ChatGPT will open
              Google sign-in.
            </li>
            <li>Start a new chat and enable Now I Get It from the tools menu.</li>
          </ol>

          <h2 className="pt-4 text-base font-semibold text-[var(--ink)]">Claude</h2>
          <ol className="list-decimal space-y-2 pl-5">
            <li>claude.ai → Customize → Connectors → Add custom connector.</li>
            <li>Paste the same URL.</li>
            <li>
              In the OAuth client modal: <strong className="text-[var(--ink)]">No client ID — register automatically</strong>.
              Leave client ID, secret, and extra headers empty.
            </li>
            <li>Enable the connector, then sign in with Google when Claude opens this site.</li>
          </ol>

          <h2 className="pt-4 text-base font-semibold text-[var(--ink)]">What you can ask</h2>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              “Make a short video explaining Fourier transforms for undergrads.” You will
              see the storyboard first and can ask for changes before it renders.
            </li>
            <li>“Revise the storyboard to add a concrete numeric example, then render.”</li>
            <li>
              “Study this lecture PDF” (public file URL) then “quiz me on slide 4.”
            </li>
          </ul>
        </section>
      </div>
    </main>
  );
}
