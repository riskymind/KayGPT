"""Calculator tool backed by an AST evaluator (no eval()).

Only numeric literals, arithmetic operators, whitelisted `math` functions/constants and a few
builtins are allowed. Exponents and factorials are bounded so model-generated input cannot
hang the worker.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool

MAX_EXPRESSION_LENGTH = 500
MAX_EXPONENT = 1000
MAX_FACTORIAL = 1000
MAX_RESULT_DIGITS = 4300  # CPython's int->str limit

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MATH_FUNCS = {
    name: getattr(math, name)
    for name in (
        "sqrt",
        "cbrt",
        "exp",
        "log",
        "log2",
        "log10",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "sinh",
        "cosh",
        "tanh",
        "degrees",
        "radians",
        "floor",
        "ceil",
        "fabs",
        "hypot",
        "gcd",
        "lcm",
        "comb",
        "perm",
        "factorial",
        "trunc",
        "isqrt",
    )
    if hasattr(math, name)
}
_COMBINATORIC = {math.factorial, math.comb, math.perm}
_BUILTIN_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": lambda *a: sum(a),
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


class CalculatorError(ValueError):
    pass


def _check_number(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CalculatorError("Only numeric results are supported.")
    if isinstance(value, int) and value.bit_length() > MAX_RESULT_DIGITS * 4:
        raise CalculatorError("Result is too large.")
    return value


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError(f"Exponent too large (max {MAX_EXPONENT}).")
        return _check_number(_BIN_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "math"
    ):
        if node.attr in _CONSTANTS:
            return _CONSTANTS[node.attr]
        raise CalculatorError(f"Unknown constant math.{node.attr}.")
    if isinstance(node, ast.Call) and not node.keywords:
        func = _resolve_function(node.func)
        args = [_eval(arg) for arg in node.args]
        if func in _COMBINATORIC and any(abs(a) > MAX_FACTORIAL for a in args):
            raise CalculatorError(f"Argument too large (max {MAX_FACTORIAL}).")
        return _check_number(func(*args))
    raise CalculatorError(f"Unsupported expression element: {type(node).__name__}.")


def _resolve_function(node: ast.AST) -> Callable[..., Any]:
    if isinstance(node, ast.Name):
        name = node.id
        func = _BUILTIN_FUNCS.get(name) or _MATH_FUNCS.get(name)
    elif (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "math"
    ):
        name = node.attr
        func = _MATH_FUNCS.get(name)
    else:
        raise CalculatorError("Unsupported function call.")
    if func is None:
        raise CalculatorError(f"Unknown function {name}.")
    return func


def safe_eval(expression: str) -> int | float:
    expression = expression.strip().replace("^", "**").replace("\u00d7", "*").replace("\u00f7", "/")
    if not expression:
        raise CalculatorError("Empty expression.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculatorError("Expression is too long.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError("Invalid expression syntax.") from exc
    try:
        result = _eval(tree)
    except ZeroDivisionError as exc:
        raise CalculatorError("Division by zero.") from exc
    except (OverflowError, ValueError, TypeError) as exc:
        if isinstance(exc, CalculatorError):
            raise
        raise CalculatorError(f"Math error: {exc}") from exc
    return result  # type: ignore[no-any-return]


def format_result(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    return str(value)


def build_calculator_tool() -> BaseTool:
    @tool
    def calculator(expression: str) -> str:
        """Evaluate a math expression and return the numeric result.

        Supports + - * / // % ** (or ^), parentheses, constants pi, e, tau and functions such as
        sqrt, log, sin, cos, factorial, round, abs, min, max. Example: "125 * 48 / 6", "sqrt(16)".
        """
        try:
            return format_result(safe_eval(expression))
        except CalculatorError as exc:
            return f"Calculation error: {exc}"

    return calculator
