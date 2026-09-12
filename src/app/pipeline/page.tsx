import { AppHeader } from "@/components/AppHeader";
import { PaperPipeline } from "@/components/PaperPipeline";

export default function PipelinePage() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-hidden bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col">
        <PaperPipeline />
      </div>
    </main>
  );
}
