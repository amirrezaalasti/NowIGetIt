import { Suspense } from "react";
import { AppHeader } from "@/components/AppHeader";
import { LearnHub } from "@/components/LearnHub";

export default function LearnPage() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col">
        <Suspense
          fallback={
            <div className="px-6 py-16 text-sm text-[var(--ink-muted)]">
              Loading…
            </div>
          }
        >
          <LearnHub />
        </Suspense>
      </div>
    </main>
  );
}
