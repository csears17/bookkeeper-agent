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


def test_decimal_stored_as_text_not_float_end_to_end(engine):
    from decimal import Decimal

    from sqlalchemy import text

    from bookkeeper_agent.db.base import session_scope
    from bookkeeper_agent.db.models import PendingBill

    with session_scope(engine) as s:
        s.add(PendingBill(
            client_key="c", company_realm="1", source_mailbox="m",
            source_message_id="x", vendor_name="V", total=Decimal("0.1"),
        ))
    with session_scope(engine) as s:
        # raw storage is TEXT, exact string — not a float column
        typ, raw = s.execute(
            text("SELECT typeof(total), total FROM pending_bills")
        ).one()
        assert typ == "text"
        assert raw == "0.1"
        # ORM read returns exact Decimal, distinct from the float-derived value
        row = s.query(PendingBill).one()
        assert row.total == Decimal("0.1")
        assert row.total != Decimal(0.1)  # float 0.1 is 0.1000...00555
