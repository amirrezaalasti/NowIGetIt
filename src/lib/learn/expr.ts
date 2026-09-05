/** Restricted arithmetic evaluator matching backend/learn/formulas.py */

const FUNCS: Record<string, (...args: number[]) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  atan2: Math.atan2,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  sqrt: Math.sqrt,
  exp: Math.exp,
  log: Math.log,
  ln: Math.log,
  log10: Math.log10,
  abs: Math.abs,
  min: Math.min,
  max: Math.max,
  floor: Math.floor,
  ceil: Math.ceil,
  round: Math.round,
  pow: Math.pow,
  hypot: Math.hypot,
  radians: (d) => (d * Math.PI) / 180,
  degrees: (r) => (r * 180) / Math.PI,
};

const CONSTS: Record<string, number> = {
  pi: Math.PI,
  e: Math.E,
  tau: Math.PI * 2,
};

type Tok =
  | { t: "n"; v: number }
  | { t: "id"; v: string }
  | { t: "op"; v: string }
  | { t: "lp" }
  | { t: "rp" }
  | { t: "comma" };

function tokenize(src: string): Tok[] {
  const s = src.replace(/\^/g, "**").replace(/°/g, "").trim();
  const out: Tok[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === " " || c === "\t") {
      i += 1;
      continue;
    }
    if (c === "," ) {
      out.push({ t: "comma" });
      i += 1;
      continue;
    }
    if (c === "(") {
      out.push({ t: "lp" });
      i += 1;
      continue;
    }
    if (c === ")") {
      out.push({ t: "rp" });
      i += 1;
      continue;
    }
    if (c === "*" && s[i + 1] === "*") {
      out.push({ t: "op", v: "**" });
      i += 2;
      continue;
    }
    if ("+-*/".includes(c)) {
      out.push({ t: "op", v: c });
      i += 1;
      continue;
    }
    if ((c >= "0" && c <= "9") || c === ".") {
      const m = s.slice(i).match(/^[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?/);
      if (!m) throw new Error("bad number");
      out.push({ t: "n", v: Number(m[0]) });
      i += m[0].length;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      const m = s.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      if (!m) throw new Error("bad name");
      out.push({ t: "id", v: m[0] });
      i += m[0].length;
      continue;
    }
    throw new Error(`unexpected ${c}`);
  }
  return out;
}

export function evalExpr(
  expr: string,
  vars: Record<string, number>,
): number {
  const tokens = tokenize(expr);
  let p = 0;
  const peek = () => tokens[p];
  const take = () => tokens[p++];

  function parsePrimary(): number {
    const tok = take();
    if (!tok) throw new Error("unexpected end");
    if (tok.t === "n") return tok.v;
    if (tok.t === "id") {
      if (peek()?.t === "lp") {
        take();
        const args: number[] = [];
        if (peek() && peek().t !== "rp") {
          args.push(parseAdd());
          while (peek()?.t === "comma") {
            take();
            args.push(parseAdd());
          }
        }
        if (take()?.t !== "rp") throw new Error("missing )");
        const fn = FUNCS[tok.v];
        if (!fn) throw new Error(`unknown function ${tok.v}`);
        return fn(...args);
      }
      if (tok.v in vars) return vars[tok.v];
      if (tok.v in CONSTS) return CONSTS[tok.v];
      throw new Error(`unknown name ${tok.v}`);
    }
    if (tok.t === "op" && tok.v === "-") return -parsePrimary();
    if (tok.t === "op" && tok.v === "+") return parsePrimary();
    if (tok.t === "lp") {
      const v = parseAdd();
      if (take()?.t !== "rp") throw new Error("missing )");
      return v;
    }
    throw new Error("bad expression");
  }

  function parsePow(): number {
    let left = parsePrimary();
    while (peek()?.t === "op" && peek().t === "op" && (peek() as { v: string }).v === "**") {
      take();
      left = Math.pow(left, parsePow());
    }
    return left;
  }

  function parseMul(): number {
    let left = parsePow();
    while (peek()?.t === "op" && (peek() as { v: string }).v && "*/".includes((peek() as { v: string }).v)) {
      const op = (take() as { v: string }).v;
      const right = parsePow();
      left = op === "*" ? left * right : left / right;
    }
    return left;
  }

  function parseAdd(): number {
    let left = parseMul();
    while (peek()?.t === "op" && (peek() as { v: string }).v && "+-".includes((peek() as { v: string }).v)) {
      const op = (take() as { v: string }).v;
      const right = parseMul();
      left = op === "+" ? left + right : left - right;
    }
    return left;
  }

  const value = parseAdd();
  if (p !== tokens.length) throw new Error("trailing tokens");
  if (!Number.isFinite(value)) throw new Error("non-finite");
  return value;
}

export function tryEval(
  expr: string,
  vars: Record<string, number>,
  fallback = 0,
): number {
  try {
    return evalExpr(expr, vars);
  } catch {
    return fallback;
  }
}
