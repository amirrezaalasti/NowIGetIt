"use client";

import "katex/dist/katex.min.css";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

type Props = {
  content: string;
  className?: string;
};

/** Normalize common LLM math wrappers so remark-math/KaTeX can render them. */
export function normalizeMathMarkdown(source: string): string {
  let text = source || "";
  // \[ ... \] → $$ ... $$
  text = text.replace(/\\\[(.+?)\\\]/gs, (_m, inner: string) => `\n$$\n${inner.trim()}\n$$\n`);
  // \( ... \) → $ ... $
  text = text.replace(/\\\((.+?)\\\)/gs, (_m, inner: string) => `$${inner.trim()}$`);
  // ```math ... ``` → $$ ... $$
  text = text.replace(
    /```(?:math|latex)\s*([\s\S]*?)```/gi,
    (_m, inner: string) => `\n$$\n${String(inner).trim()}\n$$\n`,
  );
  return text;
}

export function MarkdownView({ content, className = "" }: Props) {
  const prepared = normalizeMathMarkdown(content);
  return (
    <div className={`nig-md ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
