import pytest

from bookkeeper_agent.costs import CostMeter, SpendCapExceeded, cost_usd


def test_cost_usd_opus_rates():
    # Opus 4.8: $5/1M input, $25/1M output.
    usd = cost_usd("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0)
    assert usd == pytest.approx(5.0)
    usd = cost_usd("claude-opus-4-8", input_tokens=0, output_tokens=1_000_000)
    assert usd == pytest.approx(25.0)


def test_cost_usd_cache_tiers():
    # cache write = 1.25x input; cache read = 0.1x input.
    usd = cost_usd(
        "claude-opus-4-8",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    assert usd == pytest.approx(6.25 + 0.5)


def test_record_accumulates_month_total(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    assert meter.month_total("2026-06") == pytest.approx(10.0)
    assert meter.month_total("2026-07") == pytest.approx(0.0)


def test_check_cap_raises_at_cap(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=2_000_000, output_tokens=0, ym="2026-06")  # $10
    with pytest.raises(SpendCapExceeded):
        meter.check_cap(ym="2026-06")


def test_check_cap_ok_below_cap(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, ym="2026-06")  # $5
    meter.check_cap(ym="2026-06")  # no raise


def test_status_warn_flag_at_75pct(engine):
    meter = CostMeter(engine, monthly_cap=10.0)
    meter.record("claude-opus-4-8", input_tokens=1_500_000, output_tokens=0, ym="2026-06")  # $7.50
    status = meter.status(ym="2026-06")
    assert status["warn"] is True
    assert status["ratio"] == pytest.approx(0.75)
    assert status["total"] == pytest.approx(7.5)
    assert status["cap"] == 10.0
