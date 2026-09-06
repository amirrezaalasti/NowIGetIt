"use client";

import { useMemo, useState } from "react";
import { gradeQuiz, type QuizPaper } from "@/lib/api";

type Props = {
  itemId: string;
  paper: QuizPaper;
};

export function QuizRunner({ itemId, paper }: Props) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Awaited<ReturnType<typeof gradeQuiz>> | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const question = paper.questions[index];
  const graded = useMemo(() => {
    if (!result) return null;
    return Object.fromEntries(result.questions.map((q) => [q.question_id, q]));
  }, [result]);

  async function onSubmit() {
    setBusy(true);
    setError(null);
    try {
      const payload = paper.questions.map((q) => ({
        question_id: q.id,
        answer: answers[q.id] ?? null,
      }));
      const gradedResult = await gradeQuiz(itemId, payload);
      setResult(gradedResult);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!question) {
    return <p className="text-sm text-[var(--ink-muted)]">No questions.</p>;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
          Quiz · {index + 1} / {paper.questions.length}
        </p>
        <h2 className="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-tight">
          {paper.title}
        </h2>
        {paper.intro ? (
          <p className="mt-2 text-sm text-[var(--ink-muted)]">{paper.intro}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1">
        {paper.questions.map((q, i) => {
          const mark = graded?.[q.id];
          return (
            <button
              key={q.id}
              type="button"
              onClick={() => setIndex(i)}
              className={`h-8 w-8 rounded-lg text-xs ${
                i === index
                  ? "bg-[var(--accent)] text-[var(--on-accent)]"
                  : mark
                    ? mark.correct
                      ? "bg-[var(--accent)]/20 text-[var(--accent)]"
                      : "bg-[var(--danger-bg)] text-[var(--danger-ink)]"
                    : answers[q.id]
                      ? "bg-[var(--surface)] text-[var(--ink)]"
                      : "border border-[var(--line)] text-[var(--ink-muted)]"
              }`}
            >
              {i + 1}
            </button>
          );
        })}
      </div>

      <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5">
        <p className="text-xs uppercase tracking-[0.12em] text-[var(--ink-muted)]">
          {question.difficulty || "question"} · {question.type.replace("_", " ")}
        </p>
        <p className="mt-2 text-lg leading-snug text-[var(--ink)]">
          {question.prompt}
        </p>
        <div className="mt-4 space-y-2">
          {question.type === "numeric" || question.type === "short_answer" ? (
            <input
              value={answers[question.id] || ""}
              onChange={(e) =>
                setAnswers((prev) => ({ ...prev, [question.id]: e.target.value }))
              }
              className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-sm"
              placeholder={
                question.type === "numeric" ? "Number" : "Short answer"
              }
            />
          ) : (
            (question.choices || []).map((c) => (
              <label
                key={c.id}
                className={`flex cursor-pointer items-start gap-2 rounded-xl border px-3 py-2 text-sm ${
                  answers[question.id] === c.id
                    ? "border-[var(--accent)]"
                    : "border-[var(--line)]"
                }`}
              >
                <input
                  type="radio"
                  name={question.id}
                  checked={answers[question.id] === c.id}
                  onChange={() =>
                    setAnswers((prev) => ({ ...prev, [question.id]: c.id }))
                  }
                  className="mt-1"
                />
                <span>{c.text}</span>
              </label>
            ))
          )}
        </div>
        {graded?.[question.id] ? (
          <div className="mt-4 rounded-xl bg-[var(--surface-inset)] px-3 py-3 text-sm">
            <p
              className={
                graded[question.id].correct
                  ? "text-[var(--accent)]"
                  : "text-[var(--danger-ink)]"
              }
            >
              {graded[question.id].correct ? "Correct" : "Not quite"}
            </p>
            <p className="mt-1 leading-relaxed text-[var(--ink)]">
              {graded[question.id].explanation}
            </p>
          </div>
        ) : question.hint ? (
          <p className="mt-3 text-sm text-[var(--ink-muted)]">{question.hint}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={index === 0}
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          className="rounded-lg border border-[var(--line)] px-4 py-2 text-sm disabled:opacity-40"
        >
          Back
        </button>
        <button
          type="button"
          disabled={index >= paper.questions.length - 1}
          onClick={() =>
            setIndex((i) => Math.min(paper.questions.length - 1, i + 1))
          }
          className="rounded-lg border border-[var(--line)] px-4 py-2 text-sm disabled:opacity-40"
        >
          Next
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onSubmit()}
          className="rounded-full bg-[var(--accent)] px-6 py-2 text-sm font-semibold text-[var(--on-accent)] disabled:opacity-40"
        >
          {busy ? "Scoring…" : result ? "Score again" : "Score quiz"}
        </button>
        {result ? (
          <p className="text-sm text-[var(--ink)]">
            {result.correct_count}/{result.total} ·{" "}
            {Math.round(result.score * 100)}%
            {result.passed ? " · passed" : ""}
          </p>
        ) : null}
      </div>
      {error ? (
        <p className="text-sm text-[var(--danger-ink)]">{error}</p>
      ) : null}
    </div>
  );
}
