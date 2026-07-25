import { AppHeader } from "@/components/AppHeader";
import { DebugInspector } from "@/components/DebugInspector";

export default function LibraryPage() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col pt-8">
        <DebugInspector activeJobId={null} />
      </div>
    </main>
  );
}
