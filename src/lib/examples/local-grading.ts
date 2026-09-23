/**
 * Client-side graders for the public /examples page.
 *
 * The Learn API grades quizzes and checks lab goals server-side for items in a
 * user's Library. Showcase items are static and public, so these functions
 * mirror backend/learn/quiz.py (grade_paper) and backend/learn/interactive.py
 * (evaluate_goal) closely enough that the same UI components can run without
 * a session.
 */

import type {
  InteractiveLesson,
  LabPhase,
  QuizPaper,
  QuizQuestion,
  gradeQuiz,
  submitLabProgress,
} from "@/lib/api";
import { tryEval } from "@/lib/learn/expr";

export type QuizAnswer = {
  question_id: string;
  answer: string | number | boolean | null;
};
export type QuizGradeResult = Awaited<ReturnType<typeof gradeQuiz>>;

export type LabProgressBody = {
  phase_id: string;
  params: Record<string, number>;
  answers: Record<string, string>;
  completed_phases: string[];
};
export type LabProgressResult = Awaited<ReturnType<typeof submitLabProgress>>;

function truthy(value: unknown): boolean {
  const text = String(value).trim().toLowerCase();
  return text === "true" || text === "t" || text === "yes" || text === "1" || text === "correct";
}

function normalizeText(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function isCorrect(question: QuizQuestion, given: QuizAnswer["answer"]): boolean {
  if (given === null || given === undefined || given === "") return false;
  const expected = String(question.correct).trim();
  if (question.type === "numeric") {
    const value = Number(String(given).replace(/,/g, "").trim());
    const target = Number(expected.replace(/,/g, "").trim());
    if (!Number.isFinite(value) || !Number.isFinite(target)) return false;
    let tolerance = Number(question.numeric_tolerance ?? 0);
    if (!(tolerance > 0)) tolerance = Math.max(0.01, Math.abs(target) * 0.02);
    return Math.abs(value - target) <= tolerance;
  }
  if (question.type === "true_false") return truthy(given) === truthy(expected);
  if (question.type === "short_answer") {
    const g = normalizeText(String(given));
    const e = normalizeText(expected);
    return g === e || (e.length > 0 && g.includes(e));
  }
  return String(given).trim().toLowerCase() === expected.toLowerCase();
}

export function gradeQuizLocally(paper: QuizPaper, answers: QuizAnswer[]): QuizGradeResult {
  const byId = new Map(answers.map((a) => [a.question_id, a.answer] as const));
  let correctCount = 0;
  const questions = paper.questions.map((q) => {
    const ok = isCorrect(q, byId.get(q.id) ?? null);
    if (ok) correctCount += 1;
    return {
      question_id: q.id,
      correct: ok,
      expected: q.correct,
      explanation: q.explanation,
      hint: ok ? "" : q.hint,
    };
  });
  const total = Math.max(paper.questions.length, 1);
  const score = correctCount / total;
  return {
    id: "",
    score,
    correct_count: correctCount,
    total,
    passed: score >= (paper.pass_score || 0.7),
    questions,
  };
}

function computeReadouts(
  lesson: InteractiveLesson,
  params: Record<string, number>,
): Record<string, number> {
  const merged: Record<string, number> = Object.fromEntries(
    lesson.parameters.map((p) => [p.id, p.default]),
  );
  for (const [key, value] of Object.entries(params)) {
    if (Number.isFinite(value)) merged[key] = value;
  }
  const out: Record<string, number> = {};
  for (const readout of lesson.readouts) {
    out[readout.id] = tryEval(readout.expr, merged);
  }
  return out;
}

function evaluateGoal(
  phase: LabPhase,
  params: Record<string, number>,
  answers: Record<string, string>,
  baseline: Record<string, number>,
  readouts: Record<string, number>,
): [boolean, string] {
  const goal = phase.goal;
  if (goal.type === "observe" || goal.type === "acknowledge") {
    return [true, phase.success || "Onward."];
  }
  if (goal.type === "change_param") {
    const key = goal.param || "";
    const current = Number(params[key] ?? 0);
    const start = Number(baseline[key] ?? current);
    if (Math.abs(current - start) + 1e-9 >= Number(goal.min_delta || 0)) {
      return [true, phase.success || "You changed it — watch what the picture did."];
    }
    return [false, phase.hint || `Move ${key} more — the picture has to change.`];
  }
  if (goal.type === "target") {
    const got = readouts[goal.readout || ""];
    if (got === undefined || !Number.isFinite(got)) {
      return [false, "That readout isn't available."];
    }
    const value = Number(goal.value ?? 0);
    const tolerance = Number(goal.tolerance ?? 1);
    if (Math.abs(got - value) <= tolerance) return [true, phase.success || "Hit the mark."];
    return [
      false,
      phase.hint || `${goal.readout} is ${got.toPrecision(3)}; aim for ${value} ± ${tolerance}.`,
    ];
  }
  if (goal.type === "quiz" && goal.quiz) {
    const given = (answers[phase.id] || answers[goal.quiz.prompt] || "").trim().toLowerCase();
    const expected = (goal.quiz.correct || "").trim().toLowerCase();
    if (!expected && !goal.quiz.choices?.length) {
      return [true, goal.quiz.explanation || phase.success || "Onward."];
    }
    if (given && given === expected) {
      return [true, goal.quiz.explanation || phase.success || "That's it."];
    }
    if (given) return [false, goal.quiz.explanation || phase.hint || "Not quite — try again."];
    return [false, phase.hint || "Answer the question to continue."];
  }
  return [false, phase.hint || "Keep going."];
}

export function checkLabProgressLocally(
  lesson: InteractiveLesson,
  body: LabProgressBody,
  baseline: Record<string, number>,
): LabProgressResult {
  const phase = lesson.phases.find((p) => p.id === body.phase_id);
  if (!phase) throw new Error(`unknown phase: ${body.phase_id}`);
  const readouts = computeReadouts(lesson, body.params);
  const [met, message] = evaluateGoal(phase, body.params, body.answers, baseline, readouts);
  const completed = [...body.completed_phases];
  if (met && !completed.includes(phase.id)) completed.push(phase.id);
  return {
    id: "",
    phase_id: phase.id,
    goal_met: met,
    message,
    readouts,
    completed_phases: completed,
  };
}
