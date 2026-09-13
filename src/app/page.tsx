import { Suspense } from "react";
import { AppHeader } from "@/components/AppHeader";
import { BrandLogo } from "@/components/BrandLogo";
import { Generator } from "@/components/Generator";
import { SampleExplainer } from "@/components/SampleExplainer";

export default function Home() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col">
        <Suspense
          fallback={
            <section className="relative mx-auto w-full max-w-3xl px-6 py-10 sm:py-16">
              <BrandLogo size="lg" align="start" priority />
              <h1 className="mt-4 max-w-xl text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
                Prompt in. Scene plan, visual QA, voice — until the idea clicks.
              </h1>
              <SampleExplainer className="mt-8" />
              <p className="mt-6 text-sm text-[var(--ink-muted)]">Loading…</p>
            </section>
          }
        >
          <Generator />
        </Suspense>
      </div>
    </main>
  );
}
