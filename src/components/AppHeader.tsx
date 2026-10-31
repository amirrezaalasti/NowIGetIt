"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";

const NAV = [
  { href: "/", label: "Create" },
  { href: "/examples", label: "Examples" },
  { href: "/pipeline", label: "Pipeline" },
  { href: "/learn", label: "Learn" },
  { href: "/understand", label: "Understand" },
  { href: "/library", label: "Library" },
  { href: "/connect", label: "Connect" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppHeader() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(pathname);

  // Close the mobile menu after navigating.
  if (menuOpen && openedAt !== pathname) {
    setMenuOpen(false);
  }

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <header className="sticky top-0 z-30 border-b border-[var(--line)]/70 bg-[var(--bg-deep)]/70 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-6">
          <Link
            href="/"
            className="flex shrink-0 rounded-lg transition opacity-95 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            aria-label="Now I Get It home"
          >
            <BrandLogo size="sm" />
          </Link>
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary">
            {NAV.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 text-sm transition ${
                    active
                      ? "bg-[var(--surface)] text-[var(--ink)] shadow-[inset_0_-2px_0_var(--accent)]"
                      : "text-[var(--ink-muted)] hover:text-[var(--ink)]"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <ThemeToggle />
          <UserMenu />
          <button
            type="button"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[var(--line)] text-[var(--ink-muted)] transition hover:border-[var(--accent)] hover:text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => {
              setOpenedAt(pathname);
              setMenuOpen((open) => !open);
            }}
          >
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
            >
              {menuOpen ? (
                <path d="M6 6l12 12M18 6L6 18" />
              ) : (
                <path d="M4 7h16M4 12h16M4 17h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {menuOpen && (
        <nav
          id="mobile-nav"
          aria-label="Primary"
          className="animate-rise border-t border-[var(--line)]/70 px-4 pb-4 pt-2 sm:px-6 lg:hidden"
        >
          <ul className="mx-auto grid max-w-6xl grid-cols-2 gap-1 sm:grid-cols-4">
            {NAV.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                    className={`block rounded-lg px-3 py-2.5 text-[15px] transition ${
                      active
                        ? "bg-[var(--surface)] text-[var(--ink)] shadow-[inset_2px_0_0_var(--accent)]"
                        : "text-[var(--ink-muted)] hover:bg-[var(--surface)] hover:text-[var(--ink)]"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </header>
  );
}
