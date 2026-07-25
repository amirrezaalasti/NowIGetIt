"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { UsageMeter } from "@/components/UsageMeter";

/** Account menu for signed-in users. Sign-in CTA lives in the generator / login. */
export function UserMenu() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status === "loading") {
    return (
      <div className="h-9 w-9 animate-pulse rounded-full bg-[rgba(255,255,255,0.06)]" />
    );
  }

  if (!session?.user) {
    return (
      <Link
        href="/login"
        className="rounded-md border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)]"
      >
        Sign in
      </Link>
    );
  }

  const name = session.user.name || "Account";

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-full border border-[var(--line)] py-1 pl-1 pr-2.5 transition hover:border-[var(--accent)]"
      >
        {session.user.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={session.user.image}
            alt=""
            className="h-7 w-7 rounded-full"
            referrerPolicy="no-referrer"
          />
        ) : (
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--surface)] text-xs text-[var(--ink)]">
            {name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="hidden max-w-[8rem] truncate text-sm text-[var(--ink)] sm:inline">
          {name}
        </span>
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-72 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--bg-mid)] shadow-xl shadow-black/25"
        >
          <div className="border-b border-[var(--line)] px-4 py-3">
            <p className="truncate text-sm text-[var(--ink)]">{name}</p>
            {session.user.email ? (
              <p className="truncate text-xs text-[var(--ink-muted)]">
                {session.user.email}
              </p>
            ) : null}
          </div>

          <div className="px-3 py-3">
            <UsageMeter variant="menu" />
          </div>

          <div className="border-t border-[var(--line)] p-2">
            <button
              type="button"
              role="menuitem"
              onClick={() => signOut({ callbackUrl: "/" })}
              className="w-full rounded-lg px-3 py-2 text-left text-sm text-[var(--ink-muted)] transition hover:bg-[var(--surface)] hover:text-[var(--ink)]"
            >
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
