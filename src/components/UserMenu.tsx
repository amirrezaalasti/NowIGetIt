"use client";

import { signOut, useSession } from "next-auth/react";

/** Account menu for signed-in users. Sign-in CTA lives in the generator section. */
export function UserMenu() {
  const { data: session, status } = useSession();

  if (status === "loading") {
    return (
      <div className="h-9 w-24 animate-pulse rounded-full bg-[rgba(255,255,255,0.06)]" />
    );
  }

  if (!session?.user) {
    return null;
  }

  return (
    <div className="flex items-center gap-3">
      {session.user.image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={session.user.image}
          alt=""
          className="h-8 w-8 rounded-full border border-[var(--line)]"
          referrerPolicy="no-referrer"
        />
      ) : null}
      <div className="hidden text-right sm:block">
        <p className="text-sm text-[var(--ink)]">
          {session.user.name || "Signed in"}
        </p>
        {session.user.email ? (
          <p className="text-xs text-[var(--ink-muted)]">{session.user.email}</p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => signOut({ callbackUrl: "/" })}
        className="rounded-full border border-[var(--line)] px-3 py-1.5 text-xs text-[var(--ink-muted)] transition hover:border-[var(--accent-hot)] hover:text-[var(--ink)]"
      >
        Sign out
      </button>
    </div>
  );
}
