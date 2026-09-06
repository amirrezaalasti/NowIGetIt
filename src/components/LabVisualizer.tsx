"use client";

import { useEffect, useRef } from "react";
import { tryEval } from "@/lib/learn/expr";
import type { LabVisual } from "@/lib/api";

type Props = {
  visual: LabVisual;
  params: Record<string, number>;
  highlightParam?: string;
};

function readCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function worldToScreen(
  x: number,
  y: number,
  bounds: { x0: number; x1: number; y0: number; y1: number },
  w: number,
  h: number,
  pad = 36,
) {
  const nx = (x - bounds.x0) / Math.max(bounds.x1 - bounds.x0, 1e-9);
  const ny = (y - bounds.y0) / Math.max(bounds.y1 - bounds.y0, 1e-9);
  return { sx: pad + nx * (w - pad * 2), sy: h - pad - ny * (h - pad * 2) };
}

export function LabVisualizer({ visual, params, highlightParam }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const timeRef = useRef(0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const surface = canvas;
    const g = ctx;

    let running = true;
    const animate =
      visual.animate !== false &&
      ["projectile", "wave", "spring"].includes(visual.kind);

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = surface.clientWidth;
      const h = surface.clientHeight;
      surface.width = Math.floor(w * dpr);
      surface.height = Math.floor(h * dpr);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    const onResize = () => resize();
    window.addEventListener("resize", onResize);

    function frame(ts: number) {
      if (!running) return;
      timeRef.current = ts / 1000;
      draw(g, surface.clientWidth, surface.clientHeight, timeRef.current);
      if (animate) rafRef.current = requestAnimationFrame(frame);
    }
    draw(g, surface.clientWidth, surface.clientHeight, timeRef.current);
    if (animate) rafRef.current = requestAnimationFrame(frame);

    return () => {
      running = false;
      window.removeEventListener("resize", onResize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visual, params, highlightParam]);

  function draw(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    t: number,
  ) {
    const ink = readCssVar("--ink", "#e8f0ec");
    const muted = readCssVar("--ink-muted", "#9bb0a6");
    const accent = readCssVar("--accent", "#3ecf8e");
    const hot = readCssVar("--accent-hot", "#f0c75e");
    const line = readCssVar("--line", "rgba(232,240,236,0.12)");
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(0,0,0,0.18)";
    ctx.fillRect(0, 0, w, h);

    const kind = visual.kind;
    if (kind === "projectile") {
      drawProjectile(ctx, w, h, t, ink, muted, accent, hot, line);
    } else if (kind === "wave") {
      drawFunction(ctx, w, h, t, ink, muted, accent, line, true);
    } else if (kind === "compound_growth") {
      drawGrowth(ctx, w, h, ink, muted, accent, line);
    } else if (kind === "unit_circle") {
      drawUnitCircle(ctx, w, h, ink, muted, accent, hot);
    } else if (kind === "spring") {
      drawSpring(ctx, w, h, t, ink, muted, accent);
    } else if (kind === "vector_2d") {
      drawVector(ctx, w, h, ink, muted, accent, hot);
    } else if (kind === "geometry") {
      drawGeometry(ctx, w, h, ink, muted, accent, hot, line);
    } else {
      drawFunction(ctx, w, h, t, ink, muted, accent, line, false);
    }
  }

  function boundsForPlot() {
    const x0 = visual.x_min ?? -10;
    const x1 = visual.x_max ?? 10;
    return { x0, x1, y0: visual.y_min ?? -6, y1: visual.y_max ?? 6 };
  }

  function drawAxes(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    bounds: { x0: number; x1: number; y0: number; y1: number },
    muted: string,
    line: string,
  ) {
    ctx.strokeStyle = line;
    ctx.lineWidth = 1;
    const origin = worldToScreen(0, 0, bounds, w, h);
    ctx.beginPath();
    ctx.moveTo(36, origin.sy);
    ctx.lineTo(w - 36, origin.sy);
    ctx.moveTo(origin.sx, 36);
    ctx.lineTo(origin.sx, h - 36);
    ctx.stroke();
    ctx.fillStyle = muted;
    ctx.font = "11px ui-sans-serif, system-ui";
    if (visual.x_label) ctx.fillText(visual.x_label, w - 90, origin.sy - 8);
    if (visual.y_label) ctx.fillText(visual.y_label, origin.sx + 8, 28);
  }

  function drawFunction(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    t: number,
    ink: string,
    muted: string,
    accent: string,
    line: string,
    asWave: boolean,
  ) {
    const x0 = visual.x_min ?? -10;
    const x1 = visual.x_max ?? 10;
    const expr =
      visual.expr ||
      (visual.kind === "slope_line" ? "m*x + b" : asWave ? "A*sin(2*pi*(x/lambda - f*t))" : "x");
    const samples = 220;
    const ys: number[] = [];
    const xs: number[] = [];
    for (let i = 0; i <= samples; i += 1) {
      const x = x0 + ((x1 - x0) * i) / samples;
      xs.push(x);
      ys.push(tryEval(expr, { ...params, x, t }));
    }
    const finite = ys.filter((y) => Number.isFinite(y));
    const yMin =
      visual.y_min ??
      Math.min(-1, ...finite, 0) - 0.4;
    const yMax =
      visual.y_max ??
      Math.max(1, ...finite, 0) + 0.4;
    const bounds = { x0, x1, y0: yMin, y1: yMax };
    drawAxes(ctx, w, h, bounds, muted, line);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < xs.length; i += 1) {
      if (!Number.isFinite(ys[i])) {
        started = false;
        continue;
      }
      const p = worldToScreen(xs[i], ys[i], bounds, w, h);
      if (!started) {
        ctx.moveTo(p.sx, p.sy);
        started = true;
      } else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(visual.title || expr, 16, 22);
  }

  function drawProjectile(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    t: number,
    ink: string,
    muted: string,
    accent: string,
    hot: string,
    line: string,
  ) {
    const v = params.v ?? params.speed ?? 20;
    const thetaDeg = params.theta ?? params.angle ?? 45;
    const g = Math.max(params.g ?? 9.8, 0.2);
    const theta = (thetaDeg * Math.PI) / 180;
    const vx = v * Math.cos(theta);
    const vy = v * Math.sin(theta);
    const tFlight = (2 * vy) / g;
    const range = (v * v * Math.sin(2 * theta)) / g;
    const peak = (vy * vy) / (2 * g);
    const xMax = Math.max(range * 1.15, visual.target_x ? visual.target_x * 1.2 : 10, 10);
    const yMax = Math.max(peak * 1.4, visual.target_y ? visual.target_y + 4 : 6, 6);
    const bounds = { x0: 0, x1: xMax, y0: 0, y1: yMax };
    drawAxes(ctx, w, h, bounds, muted, line);

    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    const steps = 80;
    for (let i = 0; i <= steps; i += 1) {
      const tt = (tFlight * i) / steps;
      const x = vx * tt;
      const y = vy * tt - 0.5 * g * tt * tt;
      const p = worldToScreen(x, Math.max(y, 0), bounds, w, h);
      if (i === 0) ctx.moveTo(p.sx, p.sy);
      else ctx.lineTo(p.sx, p.sy);
    }
    ctx.stroke();

    if (visual.target_x != null) {
      const tgt = worldToScreen(
        visual.target_x,
        visual.target_y ?? 0,
        bounds,
        w,
        h,
      );
      ctx.strokeStyle = hot;
      ctx.beginPath();
      ctx.arc(tgt.sx, tgt.sy, Math.max(8, (visual.target_radius || 1) * 4), 0, Math.PI * 2);
      ctx.stroke();
    }

    const loop = Math.max(tFlight, 0.4);
    const tt = (t % (loop + 0.4));
    const x = vx * Math.min(tt, tFlight);
    const y = Math.max(vy * Math.min(tt, tFlight) - 0.5 * g * Math.min(tt, tFlight) ** 2, 0);
    const ball = worldToScreen(x, y, bounds, w, h);
    ctx.fillStyle = hot;
    ctx.beginPath();
    ctx.arc(ball.sx, ball.sy, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(`range ${range.toFixed(1)}`, 16, 22);
  }

  function drawGrowth(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    ink: string,
    muted: string,
    accent: string,
    line: string,
  ) {
    const principal = params.principal ?? params.P ?? 100;
    const rate = params.rate ?? params.r ?? 0.1;
    const periods = Math.max(1, Math.round(params.periods ?? params.n ?? 8));
    const values = Array.from({ length: periods + 1 }, (_, n) =>
      principal * Math.pow(1 + rate, n),
    );
    const yMax = Math.max(...values) * 1.1;
    const bounds = { x0: -0.5, x1: periods + 0.5, y0: 0, y1: yMax };
    drawAxes(ctx, w, h, bounds, muted, line);
    const barW = ((w - 72) / (periods + 1)) * 0.6;
    values.forEach((val, n) => {
      const p = worldToScreen(n, val, bounds, w, h);
      const base = worldToScreen(n, 0, bounds, w, h);
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(p.sx - barW / 2, p.sy, barW, base.sy - p.sy);
      ctx.globalAlpha = 1;
    });
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(`end ${values[values.length - 1].toFixed(1)}`, 16, 22);
  }

  function drawUnitCircle(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    ink: string,
    muted: string,
    accent: string,
    hot: string,
  ) {
    const thetaDeg = params.theta ?? params.angle ?? 40;
    const theta = (thetaDeg * Math.PI) / 180;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) * 0.32;
    ctx.strokeStyle = muted;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - r - 20, cy);
    ctx.lineTo(cx + r + 20, cy);
    ctx.moveTo(cx, cy - r - 20);
    ctx.lineTo(cx, cy + r + 20);
    ctx.stroke();
    const px = cx + r * Math.cos(theta);
    const py = cy - r * Math.sin(theta);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(px, py);
    ctx.stroke();
    ctx.strokeStyle = hot;
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px, cy);
    ctx.stroke();
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(cx, py);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(
      `sin ${Math.sin(theta).toFixed(2)}   cos ${Math.cos(theta).toFixed(2)}`,
      16,
      22,
    );
  }

  function drawSpring(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    t: number,
    ink: string,
    muted: string,
    accent: string,
  ) {
    const mass = Math.max(params.mass ?? params.m ?? 1, 0.2);
    const k = Math.max(params.k ?? 4, 0.2);
    const A = params.amplitude ?? params.A ?? 40;
    const omega = Math.sqrt(k / mass);
    const x = A * Math.cos(omega * t);
    const cx = w / 2;
    const top = 36;
    const rest = h * 0.45;
    const y = rest + x;
    ctx.strokeStyle = muted;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - 30, top);
    ctx.lineTo(cx + 30, top);
    const coils = 10;
    const coilTop = top + 8;
    for (let i = 0; i <= coils; i += 1) {
      const yy = coilTop + ((y - 24 - coilTop) * i) / coils;
      const xx = cx + (i % 2 === 0 ? -14 : 14);
      if (i === 0) ctx.moveTo(cx, coilTop);
      else ctx.lineTo(xx, yy);
    }
    ctx.lineTo(cx, y - 18);
    ctx.stroke();
    ctx.fillStyle = accent;
    ctx.fillRect(cx - 18, y - 18, 36, 36);
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(`ω ${omega.toFixed(2)}`, 16, 22);
  }

  function drawVector(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    ink: string,
    muted: string,
    accent: string,
    hot: string,
  ) {
    const vx = params.vx ?? (params.mag ?? 3) * Math.cos(((params.theta ?? 30) * Math.PI) / 180);
    const vy = params.vy ?? (params.mag ?? 3) * Math.sin(((params.theta ?? 30) * Math.PI) / 180);
    const span = Math.max(Math.abs(vx), Math.abs(vy), 2) * 1.4;
    const bounds = { x0: -span, x1: span, y0: -span, y1: span };
    drawAxes(ctx, w, h, bounds, muted, readCssVar("--line", "rgba(232,240,236,0.12)"));
    const o = worldToScreen(0, 0, bounds, w, h);
    const tip = worldToScreen(vx, vy, bounds, w, h);
    const xTip = worldToScreen(vx, 0, bounds, w, h);
    const yTip = worldToScreen(0, vy, bounds, w, h);
    ctx.strokeStyle = muted;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(o.sx, o.sy);
    ctx.lineTo(xTip.sx, xTip.sy);
    ctx.lineTo(tip.sx, tip.sy);
    ctx.moveTo(o.sx, o.sy);
    ctx.lineTo(yTip.sx, yTip.sy);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(o.sx, o.sy);
    ctx.lineTo(tip.sx, tip.sy);
    ctx.stroke();
    ctx.fillStyle = hot;
    ctx.beginPath();
    ctx.arc(tip.sx, tip.sy, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = ink;
    ctx.font = "12px ui-sans-serif, system-ui";
    ctx.fillText(`(${vx.toFixed(2)}, ${vy.toFixed(2)})`, 16, 22);
  }

  function drawGeometry(
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    ink: string,
    muted: string,
    accent: string,
    hot: string,
    line: string,
  ) {
    const pts = (visual.points || []).map((pt) => ({
      id: pt.id,
      label: pt.label || pt.id,
      x: tryEval(pt.x, params),
      y: tryEval(pt.y, params),
    }));
    if (!pts.length) return;
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const pad = 1.2;
    const bounds = {
      x0: Math.min(0, ...xs) - pad,
      x1: Math.max(0, ...xs) + pad,
      y0: Math.min(0, ...ys) - pad,
      y1: Math.max(0, ...ys) + pad,
    };
    drawAxes(ctx, w, h, bounds, muted, line);
    const byId = Object.fromEntries(pts.map((p) => [p.id, p]));
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.18;
    for (const fill of visual.fills || []) {
      ctx.beginPath();
      fill.forEach((id, i) => {
        const p = byId[id];
        if (!p) return;
        const s = worldToScreen(p.x, p.y, bounds, w, h);
        if (i === 0) ctx.moveTo(s.sx, s.sy);
        else ctx.lineTo(s.sx, s.sy);
      });
      ctx.closePath();
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    for (const seg of visual.segments || []) {
      const a = byId[seg[0]];
      const b = byId[seg[1]];
      if (!a || !b) continue;
      const sa = worldToScreen(a.x, a.y, bounds, w, h);
      const sb = worldToScreen(b.x, b.y, bounds, w, h);
      ctx.beginPath();
      ctx.moveTo(sa.sx, sa.sy);
      ctx.lineTo(sb.sx, sb.sy);
      ctx.stroke();
    }
    ctx.fillStyle = hot;
    ctx.font = "12px ui-sans-serif, system-ui";
    for (const p of pts) {
      const s = worldToScreen(p.x, p.y, bounds, w, h);
      ctx.beginPath();
      ctx.arc(s.sx, s.sy, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = ink;
      ctx.fillText(p.label, s.sx + 8, s.sy - 8);
      ctx.fillStyle = hot;
    }
  }

  return (
    <canvas
      ref={canvasRef}
      className="h-[min(52vh,28rem)] w-full rounded-2xl border border-[var(--line)] bg-[var(--surface-inset)]"
      role="img"
      aria-label={visual.title || visual.kind}
    />
  );
}
