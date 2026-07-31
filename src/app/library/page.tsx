import { Suspense } from "react";
import { AppHeader } from "@/components/AppHeader";
import { DebugInspector } from "@/components/DebugInspector";

function LibraryFallback() {
  return (
    <div className="mx-auto w-full max-w-6xl px-6 pb-28 pt-4">
      <div className="mb-6 h-24 animate-pulse rounded-xl bg-[var(--surface)]" />
      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-[4.5rem] animate-pulse rounded-xl bg-[var(--surface)]"
            />
          ))}
        </div>
        <div className="min-h-[22rem] animate-pulse rounded-2xl bg-[var(--surface)]" />
      </div>
    </div>
  );
}

export default function LibraryPage() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col pt-8">
        <Suspense fallback={<LibraryFallback />}>
          <DebugInspector activeJobId={null} />
        </Suspense>
      </div>
    </main>
  );
}
