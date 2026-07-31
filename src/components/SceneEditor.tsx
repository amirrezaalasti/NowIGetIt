"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  applySceneEdits,
  fetchSceneElements,
  type SceneElement,
  type SceneElementEdit,
} from "@/lib/api";

const MANIM_X_RANGE = 14.2;
const MANIM_Y_RANGE = 8.0;
const MANIM_X_MIN = -7.1;
const MANIM_Y_MAX = 4.0;

function manimToCanvas(
  mx: number,
  my: number,
  canvasW: number,
  canvasH: number,
): { cx: number; cy: number } {
  const cx = ((mx - MANIM_X_MIN) / MANIM_X_RANGE) * canvasW;
  const cy = ((MANIM_Y_MAX - my) / MANIM_Y_RANGE) * canvasH;
  return { cx, cy };
}

function canvasToManim(
  cx: number,
  cy: number,
  canvasW: number,
  canvasH: number,
): { mx: number; my: number } {
  const mx = (cx / canvasW) * MANIM_X_RANGE + MANIM_X_MIN;
  const my = MANIM_Y_MAX - (cy / canvasH) * MANIM_Y_RANGE;
  return { mx, my };
}

function manimSizeToCanvas(
  mw: number,
  mh: number,
  canvasW: number,
  canvasH: number,
): { cw: number; ch: number } {
  const cw = (mw / MANIM_X_RANGE) * canvasW;
  const ch = (mh / MANIM_Y_RANGE) * canvasH;
  return { cw, ch };
}

type CanvasElement = SceneElement & {
  cx: number;
  cy: number;
  cw: number;
  ch: number;
  dirty: boolean;
  appear_time?: number;
  disappear_time?: number;
};

export function SceneEditor({
  jobId,
  sceneId,
  initialTimestamp = 0.0,
  onVideoUpdated,
}: {
  jobId: string;
  sceneId: string;
  initialTimestamp?: number;
  onVideoUpdated?: (videoUrl: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [allElements, setAllElements] = useState<CanvasElement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<number>(initialTimestamp);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const dragRef = useRef<{
    elementId: string;
    startCx: number;
    startCy: number;
    startMouseX: number;
    startMouseY: number;
  } | null>(null);

  // Exact 16:9 standard resolution for canvas calculations
  const CANVAS_W = 1280;
  const CANVAS_H = 720;

  const maxSceneDuration = useMemo(() => {
    let maxT = 10.0;
    for (const el of allElements) {
      if (el.appear_time && el.appear_time < 900) {
        maxT = Math.max(maxT, el.appear_time + 2.0);
      }
    }
    return Math.ceil(maxT);
  }, [allElements]);

  const visibleElements = useMemo(() => {
    return allElements.filter((el) => {
      const appear = el.appear_time ?? 0.0;
      const disappear = el.disappear_time ?? 999.0;
      return currentTime >= appear && currentTime <= disappear;
    });
  }, [allElements, currentTime]);

  const loadElements = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSceneElements(jobId, sceneId);
      const mapped: CanvasElement[] = data.elements.map((el) => {
        const { cx, cy } = manimToCanvas(el.x, el.y, CANVAS_W, CANVAS_H);
        const { cw, ch } = manimSizeToCanvas(
          el.width,
          el.height,
          CANVAS_W,
          CANVAS_H,
        );
        return { ...el, cx, cy, cw, ch, dirty: false };
      });
      setAllElements(mapped);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [jobId, sceneId]);

  useEffect(() => {
    void loadElements();
  }, [loadElements]);

  const selected = useMemo(
    () => allElements.find((e) => e.id === selectedId) ?? null,
    [allElements, selectedId],
  );

  const hasDirty = useMemo(
    () => allElements.some((e) => e.dirty),
    [allElements],
  );

  // Render Canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.fillStyle = "#0f1115";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

    // Subtle grid
    ctx.strokeStyle = "#1a1d24";
    ctx.lineWidth = 1;
    for (let x = 0; x <= CANVAS_W; x += CANVAS_W / 14.2) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, CANVAS_H);
      ctx.stroke();
    }
    for (let y = 0; y <= CANVAS_H; y += CANVAS_H / 8) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(CANVAS_W, y);
      ctx.stroke();
    }

    for (const el of visibleElements) {
      ctx.save();
      const isSelected = el.id === selectedId;

      if (el.type === "Text" || el.type === "MathTex" || el.type === "Tex") {
        const fontPt = el.font_size && el.font_size > 0 ? el.font_size : 24;
        const fontPx = Math.min(36, Math.max(12, fontPt * 0.9));

        ctx.font = `${fontPx}px Inter, sans-serif`;
        ctx.fillStyle = el.stroke_color || el.fill_color || "#FFFFFF";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        const textStr = el.text || "";
        ctx.fillText(textStr, el.cx, el.cy);

        const metrics = ctx.measureText(textStr);
        const tw = Math.max(20, metrics.width + 16);
        const th = fontPx + 12;

        if (isSelected) {
          ctx.strokeStyle = "#6366f1";
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(el.cx - tw / 2, el.cy - th / 2, tw, th);
          ctx.setLineDash([]);
          _drawHandles(ctx, el.cx - tw / 2, el.cy - th / 2, tw, th);
        }
      } else if (
        el.type === "Line" ||
        el.type === "Arrow" ||
        el.type === "DashedLine" ||
        el.type === "CurvedArrow"
      ) {
        if (el.start_point && el.end_point) {
          const s = manimToCanvas(el.start_point.x, el.start_point.y, CANVAS_W, CANVAS_H);
          const e = manimToCanvas(el.end_point.x, el.end_point.y, CANVAS_W, CANVAS_H);
          ctx.strokeStyle = el.stroke_color || el.fill_color || "#FFFFFF";
          ctx.lineWidth = Math.max(1.5, el.stroke_width * 1.2);
          ctx.beginPath();
          ctx.moveTo(s.cx, s.cy);
          ctx.lineTo(e.cx, e.cy);
          ctx.stroke();
        }

        if (isSelected) {
          ctx.strokeStyle = "#6366f1";
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(el.cx - el.cw / 2, el.cy - el.ch / 2, el.cw, el.ch);
          ctx.setLineDash([]);
        }
      } else if (el.type === "Circle" || el.type === "Dot") {
        const r = Math.max(2, Math.min(CANVAS_W / 2, Math.max(el.cw, el.ch) / 2));
        ctx.beginPath();
        ctx.arc(el.cx, el.cy, r, 0, Math.PI * 2);

        if (el.fill_color && el.fill_opacity > 0) {
          ctx.fillStyle = el.fill_color;
          ctx.globalAlpha = el.fill_opacity;
          ctx.fill();
          ctx.globalAlpha = 1;
        }
        if (el.stroke_color) {
          ctx.strokeStyle = el.stroke_color;
          ctx.lineWidth = el.stroke_width;
          ctx.stroke();
        }

        if (isSelected) {
          ctx.strokeStyle = "#6366f1";
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(el.cx - r, el.cy - r, r * 2, r * 2);
          ctx.setLineDash([]);
          _drawHandles(ctx, el.cx - r, el.cy - r, r * 2, r * 2);
        }
      } else {
        const rx = el.cx - el.cw / 2;
        const ry = el.cy - el.ch / 2;

        if (el.fill_color && el.fill_opacity > 0) {
          ctx.fillStyle = el.fill_color;
          ctx.globalAlpha = el.fill_opacity;
          ctx.fillRect(rx, ry, el.cw, el.ch);
          ctx.globalAlpha = 1;
        }
        if (el.stroke_color) {
          ctx.strokeStyle = el.stroke_color;
          ctx.lineWidth = el.stroke_width;
          ctx.strokeRect(rx, ry, el.cw, el.ch);
        }

        if (isSelected) {
          ctx.strokeStyle = "#6366f1";
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 4]);
          ctx.strokeRect(rx - 2, ry - 2, el.cw + 4, el.ch + 4);
          ctx.setLineDash([]);
          _drawHandles(ctx, rx, ry, el.cw, el.ch);
        }
      }

      if (el.dirty) {
        ctx.fillStyle = "#f59e0b";
        ctx.beginPath();
        ctx.arc(el.cx + el.cw / 2 + 6, el.cy - el.ch / 2 - 6, 5, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore();
    }
  }, [visibleElements, selectedId]);

  useEffect(() => {
    draw();
  }, [draw]);

  function hitTest(mouseX: number, mouseY: number): CanvasElement | null {
    for (let i = visibleElements.length - 1; i >= 0; i--) {
      const el = visibleElements[i];
      const hw = Math.max(el.cw, 24) / 2;
      const hh = Math.max(el.ch, 24) / 2;
      if (
        mouseX >= el.cx - hw &&
        mouseX <= el.cx + hw &&
        mouseY >= el.cy - hh &&
        mouseY <= el.cy + hh
      ) {
        return el;
      }
    }
    return null;
  }

  function getCanvasPos(e: React.MouseEvent): { x: number; y: number } {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const scaleX = CANVAS_W / rect.width;
    const scaleY = CANVAS_H / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  }

  function handleMouseDown(e: React.MouseEvent) {
    const pos = getCanvasPos(e);
    const hit = hitTest(pos.x, pos.y);

    if (hit) {
      setSelectedId(hit.id);
      dragRef.current = {
        elementId: hit.id,
        startCx: hit.cx,
        startCy: hit.cy,
        startMouseX: pos.x,
        startMouseY: pos.y,
      };
    } else {
      setSelectedId(null);
    }
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!dragRef.current) return;
    const pos = getCanvasPos(e);
    const dx = pos.x - dragRef.current.startMouseX;
    const dy = pos.y - dragRef.current.startMouseY;

    setAllElements((prev) =>
      prev.map((el) => {
        if (el.id !== dragRef.current?.elementId) return el;
        const newCx = dragRef.current.startCx + dx;
        const newCy = dragRef.current.startCy + dy;
        const { mx, my } = canvasToManim(newCx, newCy, CANVAS_W, CANVAS_H);
        return { ...el, cx: newCx, cy: newCy, x: mx, y: my, dirty: true };
      }),
    );
  }

  function handleMouseUp() {
    dragRef.current = null;
  }

  function updateSelected(patch: Partial<CanvasElement>) {
    if (!selectedId) return;
    setAllElements((prev) =>
      prev.map((el) =>
        el.id === selectedId ? { ...el, ...patch, dirty: true } : el,
      ),
    );
  }

  async function handleSave() {
    const dirtyElements = allElements.filter((e) => e.dirty);
    if (dirtyElements.length === 0) return;

    setSaving(true);
    setSaveMessage(null);
    setError(null);

    const edits: SceneElementEdit[] = dirtyElements.map((el) => ({
      variable_name: el.variable_name,
      line_number: el.line_number,
      x: el.x,
      y: el.y,
      width: el.width,
      height: el.height,
      fill_color: el.fill_color ?? undefined,
      fill_opacity: el.fill_opacity,
      stroke_color: el.stroke_color ?? undefined,
      stroke_width: el.stroke_width,
      text: el.text ?? undefined,
      font_size: el.font_size ?? undefined,
    }));

    try {
      const result = await applySceneEdits(jobId, sceneId, edits);

      if (result.video_url) {
        setSaveMessage("Saved & re-rendered!");
        onVideoUpdated?.(result.video_url);
      } else {
        setSaveMessage("Code updated");
      }

      if (result.elements) {
        const mapped: CanvasElement[] = result.elements.map((el) => {
          const { cx, cy } = manimToCanvas(el.x, el.y, CANVAS_W, CANVAS_H);
          const { cw, ch } = manimSizeToCanvas(
            el.width,
            el.height,
            CANVAS_W,
            CANVAS_H,
          );
          return { ...el, cx, cy, cw, ch, dirty: false };
        });
        setAllElements(mapped);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function handleColorChange(field: "fill_color" | "stroke_color", value: string) {
    updateSelected({ [field]: value });
  }

  function handleNumberChange(field: keyof CanvasElement, value: string) {
    const num = parseFloat(value);
    if (isNaN(num)) return;

    if (field === "x" || field === "y") {
      const newX = field === "x" ? num : (selected?.x ?? 0);
      const newY = field === "y" ? num : (selected?.y ?? 0);
      const { cx, cy } = manimToCanvas(newX, newY, CANVAS_W, CANVAS_H);
      updateSelected({ [field]: num, cx, cy } as Partial<CanvasElement>);
    } else if (field === "width" || field === "height") {
      const newW = field === "width" ? num : (selected?.width ?? 1);
      const newH = field === "height" ? num : (selected?.height ?? 1);
      const { cw, ch } = manimSizeToCanvas(newW, newH, CANVAS_W, CANVAS_H);
      updateSelected({ [field]: num, cw, ch } as Partial<CanvasElement>);
    } else {
      updateSelected({ [field]: num } as Partial<CanvasElement>);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-[var(--ink-muted)]">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent mr-2" />
        Loading scene elements…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
            Interactive Editor
          </span>
          <div className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface-panel)] px-3 py-1 text-xs">
            <span className="text-[var(--ink-muted)] text-[11px]">Time:</span>
            <input
              type="range"
              min="0"
              max={maxSceneDuration}
              step="0.5"
              value={currentTime}
              onChange={(e) => setCurrentTime(parseFloat(e.target.value))}
              className="w-28 accent-[var(--accent)] cursor-pointer"
            />
            <span className="font-mono text-[11px] font-medium text-[var(--accent)]">
              {currentTime.toFixed(1)}s
            </span>
          </div>
          <span className="text-[10px] text-[var(--ink-muted)]">
            ({visibleElements.length}/{allElements.length} visible)
          </span>
        </div>

        <div className="flex items-center gap-2">
          {saveMessage && <span className="text-xs text-[var(--accent)]">{saveMessage}</span>}
          {error && <span className="text-xs text-red-400">{error}</span>}
          <button
            type="button"
            onClick={() => void loadElements()}
            className="rounded-lg border border-[var(--line)] px-3 py-1.5 text-[11px] text-[var(--ink-muted)] transition hover:border-[var(--ink)] hover:text-[var(--ink)]"
          >
            Reload
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!hasDirty || saving}
            className="flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-4 py-1.5 text-[11px] font-semibold text-[var(--on-accent)] transition hover:opacity-90 disabled:opacity-40"
          >
            {saving && (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            )}
            {saving ? "Saving…" : "Save & Re-render"}
          </button>
        </div>
      </div>

      {/* Canvas matching exact video player container aspect-video */}
      <div className="relative w-full aspect-video rounded-xl border border-[var(--line)] bg-[var(--surface-video)] overflow-hidden">
        <canvas
          ref={canvasRef}
          width={CANVAS_W}
          height={CANVAS_H}
          className="w-full h-full object-contain cursor-crosshair"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        />
      </div>

      {/* Property Inspector Panel Below Canvas */}
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface)] p-4 space-y-4 text-xs">
        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink)]">
          Properties
        </h4>

        {!selected ? (
          <p className="text-[var(--ink-muted)] italic">
            Select an element on the canvas to edit its properties.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4">
            <div className="space-y-1">
              <p className="font-medium text-[var(--ink)]">
                {selected.type}
                <span className="ml-1 font-mono text-[10px] text-[var(--ink-muted)]">
                  {selected.variable_name}
                </span>
              </p>
            </div>

            {/* Position */}
            <fieldset className="space-y-1.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                Position
              </legend>
              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-0.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">X</span>
                  <input
                    type="number"
                    step="0.1"
                    value={selected.x.toFixed(2)}
                    onChange={(e) => handleNumberChange("x", e.target.value)}
                    className="w-full rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
                <label className="space-y-0.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">Y</span>
                  <input
                    type="number"
                    step="0.1"
                    value={selected.y.toFixed(2)}
                    onChange={(e) => handleNumberChange("y", e.target.value)}
                    className="w-full rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
              </div>
            </fieldset>

            {/* Size */}
            <fieldset className="space-y-1.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                Size
              </legend>
              <div className="grid grid-cols-2 gap-2">
                <label className="space-y-0.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">Width</span>
                  <input
                    type="number"
                    step="0.1"
                    value={selected.width.toFixed(2)}
                    onChange={(e) => handleNumberChange("width", e.target.value)}
                    className="w-full rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
                <label className="space-y-0.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">Height</span>
                  <input
                    type="number"
                    step="0.1"
                    value={selected.height.toFixed(2)}
                    onChange={(e) => handleNumberChange("height", e.target.value)}
                    className="w-full rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
              </div>
            </fieldset>

            {/* Colors */}
            <fieldset className="space-y-1.5">
              <legend className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                Colors
              </legend>
              <div className="flex items-center gap-3 pt-1">
                <label className="flex items-center gap-1.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">Fill</span>
                  <input
                    type="color"
                    value={selected.fill_color || "#000000"}
                    onChange={(e) => handleColorChange("fill_color", e.target.value)}
                    className="h-6 w-8 cursor-pointer rounded border border-[var(--line)] bg-transparent"
                  />
                </label>
                <label className="flex items-center gap-1.5">
                  <span className="text-[var(--ink-muted)] text-[10px]">Stroke</span>
                  <input
                    type="color"
                    value={selected.stroke_color || "#FFFFFF"}
                    onChange={(e) => handleColorChange("stroke_color", e.target.value)}
                    className="h-6 w-8 cursor-pointer rounded border border-[var(--line)] bg-transparent"
                  />
                </label>
              </div>
            </fieldset>

            {/* Text */}
            {(selected.type === "Text" ||
              selected.type === "MathTex" ||
              selected.type === "Tex") && (
              <fieldset className="sm:col-span-2 space-y-1.5">
                <legend className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-muted)]">
                  Text Content
                </legend>
                <div className="flex gap-2">
                  <textarea
                    value={selected.text || ""}
                    onChange={(e) => updateSelected({ text: e.target.value })}
                    rows={1}
                    className="flex-1 rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none resize-none font-mono text-[11px]"
                  />
                  <label className="w-24 space-y-0.5">
                    <input
                      type="number"
                      step="1"
                      min="8"
                      value={selected.font_size ?? 24}
                      onChange={(e) => handleNumberChange("font_size", e.target.value)}
                      className="w-full rounded border border-[var(--line)] bg-[var(--surface-strong)] px-2 py-1 text-[var(--ink)] focus:border-[var(--accent)] focus:outline-none"
                    />
                  </label>
                </div>
              </fieldset>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function _drawHandles(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
) {
  const HANDLE_SIZE = 6;
  ctx.fillStyle = "#6366f1";
  const handles = [
    { x: x, y: y },
    { x: x + w, y: y },
    { x: x, y: y + h },
    { x: x + w, y: y + h },
  ];
  for (const handle of handles) {
    ctx.fillRect(
      handle.x - HANDLE_SIZE / 2,
      handle.y - HANDLE_SIZE / 2,
      HANDLE_SIZE,
      HANDLE_SIZE,
    );
  }
}
