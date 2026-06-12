from decimal import Decimal

from bookkeeper_agent.db.types import DecimalText


def test_bind_serializes_decimal_to_str():
    t = DecimalText()
    assert t.process_bind_param(Decimal("250.00"), None) == "250.00"
    assert t.process_bind_param(None, None) is None


def test_bind_coerces_non_decimal():
    t = DecimalText()
    assert t.process_bind_param("12.50", None) == "12.50"


def test_result_parses_str_to_decimal_exactly():
    t = DecimalText()
    assert t.process_result_value("250.00", None) == Decimal("250.00")
    assert t.process_result_value("0.1", None) == Decimal("0.1")  # exact, not float 0.1
    assert t.process_result_value(None, None) is None
