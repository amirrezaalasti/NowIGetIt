import type { Metadata } from "next";
import { AppHeader } from "@/components/AppHeader";
import { ExamplesGallery } from "@/components/ExamplesGallery";

export const metadata: Metadata = {
  title: "Examples — Now I Get It",
  description:
    "Explainer videos, a looping GIF clip, a quiz, and an interactive lab, all generated from a chat through the Now I Get It MCP connector.",
};

export default function ExamplesPage() {
  return (
    <main className="relative flex flex-1 flex-col overflow-x-clip bg-atmosphere">
      <div className="pointer-events-none absolute inset-0 grid-haze" aria-hidden />
      <AppHeader />
      <div className="relative z-10 flex flex-1 flex-col">
        <ExamplesGallery />
      </div>
    </main>
  );
}
