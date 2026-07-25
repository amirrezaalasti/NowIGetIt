import { BrandLogo } from "@/components/BrandLogo";
import { Generator } from "@/components/Generator";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UsageMeter } from "@/components/UsageMeter";
import { UserMenu } from "@/components/UserMenu";

export default function Home() {
  return (
    <main className="relative flex flex-1 flex-col overflow-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />

      <div className="relative z-20 mx-auto flex w-full max-w-3xl items-start justify-between gap-4 px-6 pt-6">
        <UsageMeter />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <UserMenu />
        </div>
      </div>

      <header className="relative z-10 mx-auto w-full max-w-3xl px-6 pt-8 sm:pt-10">
        <div className="animate-rise">
          <BrandLogo size="md" withWordmark priority />
        </div>
        <h1 className="animate-rise-delay mt-5 max-w-xl text-lg leading-snug text-[var(--ink-muted)] sm:text-xl">
          Prompt in. Scene plan, visual QA, voice — until the idea clicks.
        </h1>
      </header>

      <div className="relative z-10">
        <Generator />
      </div>
    </main>
  );
}
