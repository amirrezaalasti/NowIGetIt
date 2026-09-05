"use client";

import { useEffect, useMemo, useState } from "react";
import { LabVisualizer } from "@/components/LabVisualizer";
import { tryEval } from "@/lib/learn/expr";
import {
  submitLabProgress,
  type InteractiveLesson,
  type LabPhase,
} from "@/lib/api";

type Props = {
  itemId: string;
  lesson: InteractiveLesson;
  initialProgress?: Record<string, unknown>;
};

function defaults(lesson: InteractiveLesson): Record<string, number> {
  return Object.fromEntries(lesson.parameters.map((p) => [p.id, p.default]));
}

export function InteractiveLab({ itemId, lesson, initialProgress }: Props) {
  const [params, setParams] = useState<Record<string, number>>(() => {
    const saved = initialProgress?.params;
    if (saved && typeof saved === "object") {
      return { ...defaults(lesson), ...(saved as Record<string, number>) };
    }
    return defaults(lesson);
  });
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [completed, setCompleted] = useState<string[]>(() =>
    Array.isArray(initialProgress?.completed_phases)
      ? (initialProgress?.completed_phases as string[])
      : [],
  );
  const [baseline, setBaseline] = useState<Record<string, number>>(params);
  const [answer, setAnswer] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fire, setFire] = useState(0);

  const phase: LabPhase | undefined = lesson.phases[phaseIndex];
  const locked = new Set(phase?.locked_params || []);

  useEffect(() => {
    if (!phase) return;
    setAnswer("");
    setMessage(null);
    setBaseline({ ...params });
    if (phase.suggested_params && Object.keys(phase.suggested_params).length) {
      setParams((prev) => ({ ...prev, ...phase.suggested_params }));
    }
    // Entering a phase should snapshot the current sliders, not re-run on every drag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase?.id]);

  const readouts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of lesson.readouts) {
      out[r.id] = tryEval(r.expr, params);
    }
    return out;
  }, [lesson.readouts, params]);

  async function onContinue() {
    if (!phase) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await submitLabProgress(itemId, {
        phase_id: phase.id,
        params,
        answers: answer ? { [phase.id]: answer } : {},
        completed_phases: completed,
      });
      setCompleted(result.completed_phases);
      setMessage(result.message);
      if (result.goal_met) {
        if (phaseIndex < lesson.phases.length - 1) {
          setPhaseIndex((i) => i + 1);
        }
      }
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!phase) {
    return (
      <p className="text-sm text-[var(--ink-muted)]">This lab has no phases.</p>
    );
  }

  const quiz = phase.goal.quiz;
  const done = completed.includes(phase.id) && phaseIndex === lesson.phases.length - 1;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)]">
      <div>
        <LabVisualizer
          key={fire}
          visual={lesson.visual}
          params={params}
          highlightParam={phase.goal.param}
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {lesson.readouts.map((r) => (
            <div
              key={r.id}
              className="rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2"
            >
              <p className="text-[11px] uppercase tracking-[0.12em] text-[var(--ink-muted)]">
                {r.label}
              </p>
              <p className="mt-0.5 font-mono text-lg text-[var(--ink)]">
                {(readouts[r.id] ?? 0).toFixed(r.precision ?? 2)}
                {r.unit ? (
                  <span className="ml-1 text-sm text-[var(--ink-muted)]">
                    {r.unit}
                  </span>
                ) : null}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-5 space-y-4">
          {lesson.parameters.map((p) => {
            const isLocked = locked.has(p.id);
            const moved =
              phase.goal.type === "change_param" &&
              p.id === phase.goal.param &&
              Math.abs((params[p.id] ?? 0) - (baseline[p.id] ?? 0)) >=
                (phase.goal.min_delta || 0);
            return (
              <label key={p.id} className="block">
                <span className="flex items-baseline justify-between gap-2 text-sm">
                  <span className={moved ? "text-[var(--accent)]" : "text-[var(--ink)]"}>
                    {p.label}
                    {p.unit ? ` (${p.unit})` : ""}
                    {isLocked ? " · locked" : ""}
                  </span>
                  <span className="font-mono text-[var(--ink-muted)]">
                    {(params[p.id] ?? p.default).toFixed(
                      p.step < 1 ? 2 : p.step < 10 ? 1 : 0,
                    )}
                  </span>
                </span>
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  disabled={isLocked}
                  value={params[p.id] ?? p.default}
                  onChange={(e) =>
                    setParams((prev) => ({
                      ...prev,
                      [p.id]: Number(e.target.value),
                    }))
                  }
                  className="mt-1 w-full accent-[var(--accent)] disabled:opacity-40"
                />
                {p.description ? (
                  <span className="mt-1 block text-xs text-[var(--ink-muted)]">
                    {p.description}
                  </span>
                ) : null}
              </label>
            );
          })}
        </div>
        {["projectile", "wave", "spring"].includes(lesson.visual.kind) ? (
          <button
            type="button"
            onClick={() => setFire((n) => n + 1)}
            className="mt-4 text-sm text-[var(--ink-muted)] hover:text-[var(--ink)]"
          >
            Replay motion {fire > 0 ? `· ${fire}` : ""}
          </button>
        ) : null}
      </div>

      <aside className="flex flex-col gap-4">
        <ol className="flex flex-wrap gap-1.5">
          {lesson.phases.map((p, i) => {
            const on = i === phaseIndex;
            const ok = completed.includes(p.id);
            return (
              <li key={p.id}>
                <button
                  type="button"
                  disabled={i > phaseIndex && !ok}
                  onClick={() => {
                    if (i <= phaseIndex || ok) setPhaseIndex(i);
                  }}
                  className={`rounded-full px-2.5 py-1 text-[11px] uppercase tracking-[0.08em] ${
                    on
                      ? "bg-[var(--accent)] text-[var(--on-accent)]"
                      : ok
                        ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                        : "bg-[var(--surface)] text-[var(--ink-muted)]"
                  }`}
                >
                  {p.kind}
                </button>
              </li>
            );
          })}
        </ol>
        <div className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-4">
          <p className="text-[11px] uppercase tracking-[0.14em] text-[var(--ink-muted)]">
            Phase {phaseIndex + 1} of {lesson.phases.length}
          </p>
          <h2 className="mt-1 font-[family-name:var(--font-display)] text-2xl tracking-tight">
            {phase.title}
          </h2>
          {lesson.core_question ? (
            <p className="mt-2 text-sm text-[var(--accent-hot)]">
              {lesson.core_question}
            </p>
          ) : null}
          <p className="mt-3 text-sm leading-relaxed text-[var(--ink)]">
            {phase.coach}
          </p>
        </div>

        {quiz ? (
          <div className="space-y-2">
            <p className="text-sm font-medium text-[var(--ink)]">{quiz.prompt}</p>
            {quiz.choices?.length ? (
              quiz.choices.map((c) => (
                <label
                  key={c.id}
                  className={`flex cursor-pointer items-start gap-2 rounded-xl border px-3 py-2 text-sm ${
                    answer === c.id
                      ? "border-[var(--accent)] bg-[var(--surface)]"
                      : "border-[var(--line)]"
                  }`}
                >
                  <input
                    type="radio"
                    name={`q-${phase.id}`}
                    checked={answer === c.id}
                    onChange={() => setAnswer(c.id)}
                    className="mt-1"
                  />
                  <span>{c.text}</span>
                </label>
              ))
            ) : (
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                className="w-full rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] px-3 py-2 text-sm"
                placeholder="Your answer"
              />
            )}
          </div>
        ) : null}

        {message ? (
          <p className="text-sm text-[var(--accent)]">{message}</p>
        ) : phase.hint ? (
          <p className="text-sm text-[var(--ink-muted)]">{phase.hint}</p>
        ) : null}

        <button
          type="button"
          disabled={busy}
          onClick={() => void onContinue()}
          className="rounded-full bg-[var(--accent)] px-6 py-2.5 text-sm font-semibold text-[var(--on-accent)] disabled:opacity-40"
        >
          {busy
            ? "Checking…"
            : done
              ? "You got it"
              : phase.goal.type === "acknowledge"
                ? "Finish"
                : "Check / continue"}
        </button>
        {lesson.payoff && done ? (
          <p className="text-sm leading-relaxed text-[var(--ink-muted)]">
            {lesson.payoff}
          </p>
        ) : null}
      </aside>
    </div>
  );
}
