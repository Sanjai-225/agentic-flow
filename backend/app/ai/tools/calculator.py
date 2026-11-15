"""Safe arithmetic evaluator for the agent's calculator tool.

A hand-written tokenizer + recursive-descent parser. Nothing is passed to
``eval``/``exec``; only numbers, + - * / // % **, parentheses, unary minus,
a fixed set of functions and the constants ``pi`` and ``e`` are understood.
Expression length, nesting depth, exponent size and result magnitude are bounded.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, List, Tuple, Union

Number = Union[int, float]
MAX_EXPRESSION_CHARS = 500
MAX_DEPTH = 40
MAX_EXPONENT = 1000
MAX_MAGNITUDE = 1e300

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|(\*\*|//|[-+*/%(),])|([A-Za-z_]\w*))")

FUNCTIONS: Dict[str, Tuple[Callable[..., Number], int, int]] = {
    "abs": (abs, 1, 1),
    "round": (lambda x, n=0: round(x, int(n)), 1, 2),
    "min": (min, 1, 50),
    "max": (max, 1, 50),
    "sqrt": (math.sqrt, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "log": (lambda x, base=math.e: math.log(x, base), 1, 2),
    "log10": (math.log10, 1, 1),
    "sum": (lambda *xs: sum(xs), 1, 200),
    "avg": (lambda *xs: sum(xs) / len(xs), 1, 200),
}
CONSTANTS: Dict[str, float] = {"pi": math.pi, "e": math.e}


class CalculatorError(ValueError):
    pass


def _tokenize(expr: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    pos = 0
    text = expr.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise CalculatorError(f"Unexpected character {text[pos]!r} at position {pos}.")
        number, op, name = match.groups()
        if number is not None:
            tokens.append(("num", number))
        elif op is not None:
            tokens.append(("op", op))
        elif name is not None:
            tokens.append(("name", name))
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return tokens


class _Parser:
    def __init__(self, tokens: List[Tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def peek(self) -> Tuple[str, str]:
        return self.tokens[self.i] if self.i < len(self.tokens) else ("end", "")

    def take(self, value: str) -> bool:
        if self.peek() == ("op", value):
            self.i += 1
            return True
        return False

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalculatorError("Expression is nested too deeply.")

    def parse(self) -> Number:
        value = self.expr()
        if self.peek()[0] != "end":
            raise CalculatorError(f"Unexpected token {self.peek()[1]!r}.")
        return value

    def expr(self) -> Number:
        value = self.term()
        while True:
            if self.take("+"):
                value = _check(value + self.term())
            elif self.take("-"):
                value = _check(value - self.term())
            else:
                return value

    def term(self) -> Number:
        value = self.unary()
        while True:
            if self.take("*"):
                value = _check(value * self.unary())
            elif self.take("//"):
                divisor = self.unary()
                _nonzero(divisor)
                value = _check(value // divisor)
            elif self.take("/"):
                divisor = self.unary()
                _nonzero(divisor)
                value = _check(value / divisor)
            elif self.take("%"):
                divisor = self.unary()
                _nonzero(divisor)
                value = _check(value % divisor)
            else:
                return value

    def unary(self) -> Number:
        if self.take("-"):
            self.enter()
            try:
                return -self.unary()
            finally:
                self.depth -= 1
        if self.take("+"):
            return self.unary()
        return self.power()

    def power(self) -> Number:
        base = self.atom()
        if self.take("**"):
            exponent = self.unary()  # right-associative
            if abs(exponent) > MAX_EXPONENT:
                raise CalculatorError(f"Exponent {exponent} is too large (max {MAX_EXPONENT}).")
            try:
                return _check(base ** exponent)
            except (OverflowError, ZeroDivisionError) as exc:
                raise CalculatorError(f"Cannot compute {base} ** {exponent}.") from exc
        return base

    def atom(self) -> Number:
        kind, value = self.peek()
        if kind == "num":
            self.i += 1
            number = _check(float(value))
            return int(value) if not any(c in value for c in ".eE") else number
        if kind == "op" and value == "(":
            self.i += 1
            self.enter()
            result = self.expr()
            self.depth -= 1
            if not self.take(")"):
                raise CalculatorError("Missing closing parenthesis.")
            return result
        if kind == "name":
            self.i += 1
            if value in CONSTANTS:
                return CONSTANTS[value]
            if value not in FUNCTIONS:
                raise CalculatorError(f"Unknown name {value!r}. Allowed functions: {', '.join(FUNCTIONS)}.")
            fn, min_args, max_args = FUNCTIONS[value]
            if not self.take("("):
                raise CalculatorError(f"Function {value} must be called with parentheses.")
            self.enter()
            args: List[Number] = []
            if not self.take(")"):
                while True:
                    args.append(self.expr())
                    if self.take(")"):
                        break
                    if not self.take(","):
                        raise CalculatorError(f"Expected ',' or ')' in call to {value}.")
            self.depth -= 1
            if not min_args <= len(args) <= max_args:
                raise CalculatorError(f"{value} takes {min_args}-{max_args} arguments, got {len(args)}.")
            try:
                return _check(fn(*args))
            except (ValueError, ZeroDivisionError, OverflowError) as exc:
                raise CalculatorError(f"{value}{tuple(args)} is undefined: {exc}") from exc
        raise CalculatorError("Expected a number, '(' or a function." if kind != "end" else "Unexpected end of expression.")


def _nonzero(value: Number) -> None:
    if value == 0:
        raise CalculatorError("Division by zero.")


def _check(value: Number) -> Number:
    if isinstance(value, complex):
        raise CalculatorError("The result is not a real number.")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculatorError("The result is not a finite number.")
    if abs(value) > MAX_MAGNITUDE:
        raise CalculatorError("The result is too large.")
    return value


def evaluate_expression(expression: str) -> Number:
    if not expression or not expression.strip():
        raise CalculatorError("The expression is empty.")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculatorError(f"The expression is longer than {MAX_EXPRESSION_CHARS} characters.")
    return _Parser(_tokenize(expression)).parse()
