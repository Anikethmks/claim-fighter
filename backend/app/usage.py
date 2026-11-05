"""Token and cost accounting for every LLM call.

Providers call `record(...)`; callers wrap work in `track()` to collect the
calls made inside it (works per thread / per background task via
contextvars). Prices are USD per 1M tokens: (input, cached input, output).
Reasoning tokens are billed as output by both providers.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Iterator

# Checked 2026-11-04 (OpenAI pricing page; Anthropic API docs). Override with CF_PRICES in .env, e.g.
# CF_PRICES={"gpt-5.5": [5.0, 0.5, 30.0]}
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "claude-opus-5-5": (4.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 0.20, 10.00),
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
}
PRICES.update({k: tuple(v) for k, v in json.loads(os.getenv("CF_PRICES", "{}")).items()})


@dataclass
class Call:
    step: str
    provider: str
    model: str
    input_tokens: int          # uncached input
    cached_tokens: int         # input served from cache
    output_tokens: int         # includes reasoning
    reasoning_tokens: int
    seconds: float

    @property
    def cost_usd(self) -> float | None:
        if self.provider == "ollama":
            return 0.0
        price = PRICES.get(self.model)
        if price is None:
            return None
        p_in, p_cached, p_out = price
        return (self.input_tokens * p_in + self.cached_tokens * p_cached + self.output_tokens * p_out) / 1_000_000

    def to_dict(self) -> dict:
        return {**asdict(self), "cost_usd": self.cost_usd}


_calls: ContextVar[list[Call] | None] = ContextVar("llm_calls", default=None)
_step: ContextVar[str] = ContextVar("llm_step", default="unknown")


@contextmanager
def track() -> Iterator[list[Call]]:
    calls: list[Call] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


@contextmanager
def step(name: str) -> Iterator[None]:
    token = _step.set(name)
    try:
        yield
    finally:
        _step.reset(token)


def record(provider: str, model: str, input_tokens: int, cached_tokens: int,
           output_tokens: int, reasoning_tokens: int, seconds: float) -> None:
    calls = _calls.get()
    if calls is not None:
        calls.append(Call(_step.get(), provider, model, input_tokens, cached_tokens,
                          output_tokens, reasoning_tokens, round(seconds, 1)))


def total_cost(calls: list[Call]) -> float | None:
    costs = [c.cost_usd for c in calls]
    return None if any(c is None for c in costs) else round(sum(costs), 4)
