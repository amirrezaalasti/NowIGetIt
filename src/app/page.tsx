import { Suspense } from "react";
import { AppHeader } from "@/components/AppHeader";
import { BrandLogo } from "@/components/BrandLogo";
import { Generator } from "@/components/Generator";

export default function Home() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-clip bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col">
        <Suspense
          fallback={
            <section className="relative mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-6 py-24">
              <BrandLogo size="lg" />
              <p className="mt-6 text-sm text-[var(--ink-muted)]" role="status">
                Loading…
              </p>
            </section>
          }
        >
          <Generator />
        </Suspense>
      </div>
    </main>
  );
}
