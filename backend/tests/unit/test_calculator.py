import pytest

from app.tools.calculator import CalculatorError, build_calculator_tool, format_result, safe_eval


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", 4),
        ("125 * 48 / 6", 1000),
        ("2 ^ 10", 1024),
        ("sqrt(16)", 4),
        ("math.sqrt(16)", 4),
        ("round(math.pi, 2)", 3.14),
        ("max(1, 5, 3)", 5),
        ("sum(1, 2, 3)", 6),
        ("-(3 - 5) * 2", 4),
        ("factorial(5)", 120),
        ("10 // 3 + 10 % 3", 4),
    ],
)
def test_evaluates_math(expression: str, expected: float) -> None:
    assert safe_eval(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "().__class__.__mro__",
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "[1, 2, 3]",
        "'a' * 3",
        "lambda: 1",
        "math.__dict__",
        "x + 1",
        "abs(x=1)",
    ],
)
def test_rejects_non_arithmetic(expression: str) -> None:
    with pytest.raises(CalculatorError):
        safe_eval(expression)


@pytest.mark.parametrize("expression", ["9 ** 9 ** 9", "factorial(100000)", "comb(10**6, 5000)"])
def test_rejects_resource_exhaustion(expression: str) -> None:
    with pytest.raises(CalculatorError):
        safe_eval(expression)


def test_division_by_zero() -> None:
    with pytest.raises(CalculatorError, match="Division by zero"):
        safe_eval("1 / 0")


def test_format_result_drops_trailing_zero() -> None:
    assert format_result(4.0) == "4"
    assert format_result(2.5) == "2.5"


def test_tool_returns_error_text_instead_of_raising() -> None:
    tool = build_calculator_tool()
    assert tool.invoke({"expression": "6 * 7"}) == "42"
    assert tool.invoke({"expression": "import os"}).startswith("Calculation error")
