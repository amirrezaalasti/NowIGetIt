import { auth } from "@/auth";
import { BrandLogo } from "@/components/BrandLogo";
import {
  clientAllowsRedirect,
  issueAuthorizationCode,
  issuerFrom,
  loadClient,
  readPendingAuthorize,
} from "@/lib/mcp/oauth";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";

const PENDING_COOKIE = "mcp_oauth_pending";

async function approve() {
  "use server";
  const session = await auth();
  if (!session?.user?.id) redirect("/login?callbackUrl=/oauth/consent");
  const jar = await cookies();
  const pending = jar.get(PENDING_COOKIE)?.value;
  const query = pending ? await readPendingAuthorize(pending) : null;
  if (!query) redirect("/connect");
  const client = await loadClient(query.client_id);
  if (!client || !clientAllowsRedirect(client, query.redirect_uri)) {
    redirect("/connect");
  }
  const hdrs = await headers();
  const origin = issuerFrom(new Request("https://local.invalid", { headers: hdrs }));
  const code = await issueAuthorizationCode({
    sub: session.user.id,
    email: session.user.email,
    name: session.user.name,
    client_id: query.client_id,
    redirect_uri: query.redirect_uri,
    code_challenge: query.code_challenge,
    resource: query.resource,
    scope: query.scope,
  });
  jar.delete(PENDING_COOKIE);
  const next = new URL(query.redirect_uri);
  next.searchParams.set("code", code);
  if (query.state) next.searchParams.set("state", query.state);
  next.searchParams.set("iss", origin);
  redirect(next.toString());
}

export default async function ConsentPage() {
  const session = await auth();
  if (!session?.user?.id) {
    redirect("/login?callbackUrl=/oauth/consent");
  }
  const pending = (await cookies()).get(PENDING_COOKIE)?.value;
  const query = pending ? await readPendingAuthorize(pending) : null;
  if (!query) {
    return (
      <Shell>
        <h1 className="text-xl font-semibold text-[var(--ink)]">This sign-in expired</h1>
        <p className="mt-2 text-sm text-[var(--ink-muted)]">
          Go back to Claude or ChatGPT and enable the connector again.
        </p>
      </Shell>
    );
  }
  const client = await loadClient(query.client_id);
  if (!client || !clientAllowsRedirect(client, query.redirect_uri)) {
    return (
      <Shell>
        <h1 className="text-xl font-semibold text-[var(--ink)]">Unknown chat client</h1>
        <p className="mt-2 text-sm text-[var(--ink-muted)]">
          Add the connector again and leave the client ID blank so it can register itself.
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <p className="text-sm text-[var(--ink-muted)]">Chat connector</p>
      <h1 className="mt-2 font-[family-name:var(--font-display)] text-3xl tracking-tight text-[var(--ink)]">
        Connect {client.client_name}
      </h1>
      <p className="mt-4 text-[var(--ink-muted)]">
        Videos and study slides created in chat will be saved to{" "}
        <strong className="text-[var(--ink)]">
          {session.user.email || session.user.name || "your Now I Get It library"}
        </strong>
        . Open them later under Library on this site.
      </p>
      <form action={approve} className="mt-8 flex flex-col gap-3">
        <button
          type="submit"
          className="rounded-full bg-[var(--accent)] px-6 py-3 text-sm font-semibold text-[var(--on-accent,#062016)]"
        >
          Allow access
        </button>
        <a
          href="/library"
          className="rounded-full border border-[var(--line)] px-6 py-3 text-center text-sm text-[var(--ink-muted)]"
        >
          Cancel
        </a>
      </form>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="relative flex min-h-full flex-1 flex-col items-center justify-center overflow-hidden bg-atmosphere px-6">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <div className="relative z-10 w-full max-w-md">
        <BrandLogo size="md" />
        <div className="mt-8">{children}</div>
      </div>
    </main>
  );
}
