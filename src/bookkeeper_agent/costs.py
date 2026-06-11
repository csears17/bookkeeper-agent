from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import CostRecord

# USD per token. cache_write = 1.25x input, cache_read = 0.1x input.
_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {
        "input": 5.0 / 1_000_000,
        "output": 25.0 / 1_000_000,
        "cache_write": 6.25 / 1_000_000,
        "cache_read": 0.5 / 1_000_000,
    },
}


class SpendCapExceeded(Exception):
    """Raised when the month's Claude spend has reached the configured cap."""


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    if model not in _PRICES:
        raise KeyError(f"no price table for model {model!r}")
    p = _PRICES[model]
    return (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_creation_input_tokens * p["cache_write"]
        + cache_read_input_tokens * p["cache_read"]
    )


def _current_ym() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class CostMeter:
    """Tracks monthly Claude spend in the DB and enforces a hard cap.

    Usage in the agentic loop:
        meter.check_cap()          # before a model call; raises SpendCapExceeded at 100%
        resp = client.messages.create(...)
        meter.record(model, **resp.usage_as_kwargs, request_id=resp._request_id)
    """

    def __init__(self, engine: Engine, monthly_cap: float, warn_ratio: float = 0.75):
        self._engine = engine
        self.monthly_cap = monthly_cap
        self.warn_ratio = warn_ratio

    def month_total(self, ym: str | None = None) -> float:
        ym = ym or _current_ym()
        with session_scope(self._engine) as s:
            total = s.execute(
                select(func.coalesce(func.sum(CostRecord.usd), 0.0)).where(CostRecord.ym == ym)
            ).scalar_one()
        return float(total)

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        request_id: str | None = None,
        capability: str | None = None,
        ym: str | None = None,
    ) -> float:
        ym = ym or _current_ym()
        usd = cost_usd(
            model,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
        )
        with session_scope(self._engine) as s:
            s.add(CostRecord(
                ym=ym,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                usd=usd,
                request_id=request_id,
                capability=capability,
            ))
        return usd

    def check_cap(self, ym: str | None = None) -> None:
        ym = ym or _current_ym()
        total = self.month_total(ym)
        if total >= self.monthly_cap:
            raise SpendCapExceeded(
                f"month {ym} spend ${total:.2f} has reached cap ${self.monthly_cap:.2f}"
            )

    def status(self, ym: str | None = None) -> dict:
        ym = ym or _current_ym()
        total = self.month_total(ym)
        ratio = (total / self.monthly_cap) if self.monthly_cap else 0.0
        return {
            "ym": ym,
            "total": total,
            "cap": self.monthly_cap,
            "ratio": ratio,
            "warn": ratio >= self.warn_ratio,
            "exceeded": total >= self.monthly_cap,
        }
