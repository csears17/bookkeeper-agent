from datetime import date
from decimal import Decimal

from bookkeeper_agent.db.base import session_scope
from bookkeeper_agent.db.models import Checkpoint, PendingBill


def test_pending_bill_round_trip_exact_decimal_and_pdf(engine):
    with session_scope(engine) as s:
        s.add(PendingBill(
            client_key="habit-pilates", company_realm="111",
            source_mailbox="habit@unionstreet.io", source_message_id="m1",
            vendor_name="ACME", is_new_vendor=True, doc_number="INV-100",
            txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30),
            total=Decimal("250.00"), currency="USD",
            proposed_account_id="A1", proposed_account_name="Supplies",
            confidence=0.9, reasoning="precedent",
            pdf_filename="invoice.pdf", pdf_bytes=b"%PDF-1.4 bytes",
        ))
    with session_scope(engine) as s:
        row = s.query(PendingBill).one()
        assert row.status == "pending"  # default
        assert row.total == Decimal("250.00")  # exact, not 250.0 float
        assert isinstance(row.total, Decimal)
        assert row.pdf_bytes == b"%PDF-1.4 bytes"
        assert row.company_realm == "111"


def test_pending_bill_unique_on_client_and_message(engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with session_scope(engine) as s:
        s.add(PendingBill(client_key="c", company_realm="1", source_mailbox="m",
                          source_message_id="dup", vendor_name="V", total=Decimal("1.00")))
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            s.add(PendingBill(client_key="c", company_realm="1", source_mailbox="m",
                              source_message_id="dup", vendor_name="V2", total=Decimal("2.00")))


def test_checkpoint_round_trip(engine):
    with session_scope(engine) as s:
        s.add(Checkpoint(mailbox="habit@unionstreet.io", last_epoch_ms=1717200000000))
    with session_scope(engine) as s:
        cp = s.query(Checkpoint).one()
        assert cp.mailbox == "habit@unionstreet.io"
        assert cp.last_epoch_ms == 1717200000000
