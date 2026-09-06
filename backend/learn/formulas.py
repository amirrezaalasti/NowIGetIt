"""Restricted arithmetic evaluator for interactive-lab expressions.

The LLM writes formulas in terms of slider parameters (`v`, `theta`, `g`, …)
plus `x` / `t` for plots. Those strings are evaluated on the server (grading)
and in the browser (live viz). This module is the Python side: AST walk only,
no `eval`, no attribute access, no names outside the allowlist.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

ALLOWED_FUNCS: dict[str, Any] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "ln": math.log,
    "log10": math.log10,
    "abs": abs,
    "min": min,
    "max": max,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "pow": pow,
    "hypot": math.hypot,
    "radians": math.radians,
    "degrees": math.degrees,
}

CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

_BIN: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


def normalize_expr(expr: str) -> str:
    """Caret power and degree sign → Python; keep the rest intact."""
    text = (expr or "").strip().replace("^", "**").replace("°", "")
    return text


def extract_names(expr: str) -> set[str]:
    """Free names referenced by an expression (not functions/constants)."""
    tree = ast.parse(normalize_expr(expr), mode="eval")
    names: set[str] = set()

    class Walk(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
            names.add(node.id)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            if isinstance(node.func, ast.Name):
                for arg in node.args:
                    self.visit(arg)
                for kw in node.keywords:
                    self.visit(kw.value)
            else:
                self.generic_visit(node)

    Walk().visit(tree)
    return {n for n in names if n not in ALLOWED_FUNCS and n not in CONSTANTS}


def eval_expr(expr: str, variables: dict[str, float]) -> float:
    """Evaluate a restricted arithmetic expression. Raises ValueError on bad input."""
    text = normalize_expr(expr)
    if not text:
        raise ValueError("empty expression")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {expr}") from exc
    value = _eval_node(tree.body, variables)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expression did not produce a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("expression produced a non-finite number")
    return number


def try_eval(expr: str, variables: dict[str, float], default: float = 0.0) -> float:
    try:
        return eval_expr(expr, variables)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return default


def _eval_node(node: ast.AST, variables: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("only numeric literals are allowed")
    if isinstance(node, ast.Name):
        if node.id in variables:
            return float(variables[node.id])
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp):
        op = _BIN.get(type(node.op))
        if op is None:
            raise ValueError("unsupported operator")
        return float(op(_eval_node(node.left, variables), _eval_node(node.right, variables)))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise ValueError("unsupported unary operator")
        return float(op(_eval_node(node.operand, variables)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
            raise ValueError("unsupported function")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        args = [_eval_node(a, variables) for a in node.args]
        result = ALLOWED_FUNCS[node.func.id](*args)
        return float(result)
    if isinstance(node, ast.Compare):
        # Allow a < b < c style for goals like "range > 30".
        left = _eval_node(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, variables)
            ok = False
            if isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.Eq):
                ok = abs(left - right) < 1e-9
            elif isinstance(op, ast.NotEq):
                ok = abs(left - right) >= 1e-9
            else:
                raise ValueError("unsupported comparison")
            if not ok:
                return 0.0
            left = right
        return 1.0
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, variables) for v in node.values]
        if isinstance(node.op, ast.And):
            return 1.0 if all(values) else 0.0
        if isinstance(node.op, ast.Or):
            return 1.0 if any(values) else 0.0
        raise ValueError("unsupported boolean operator")
    raise ValueError(f"unsupported expression node: {type(node).__name__}")
