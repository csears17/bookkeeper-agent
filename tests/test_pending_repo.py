from datetime import date
from decimal import Decimal

from bookkeeper_agent.pipeline.store import PendingBillRepo


def _fields(**over):
    base = dict(
        client_key="habit-pilates", company_realm="111",
        source_mailbox="habit@unionstreet.io", source_message_id="m1",
        vendor_name="ACME", is_new_vendor=False, vendor_id="V1",
        doc_number="INV-100", txn_date=date(2026, 6, 1), due_date=None,
        total=Decimal("250.00"), currency="USD",
        proposed_account_id="A1", proposed_account_name="Supplies",
        confidence=0.9, reasoning="precedent",
        pdf_filename="invoice.pdf", pdf_bytes=b"%PDF",
    )
    base.update(over)
    return base


def test_create_and_get(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields())
    row = repo.get(pid)
    assert row.vendor_name == "ACME"
    assert row.total == Decimal("250.00")
    assert row.status == "pending"


def test_list_pending_only_returns_pending(engine):
    repo = PendingBillRepo(engine)
    p1 = repo.create(**_fields(source_message_id="m1"))
    p2 = repo.create(**_fields(source_message_id="m2"))
    repo.set_status(p2, "rejected", resolved=True)
    pending = repo.list_pending()
    assert [p.id for p in pending] == [p1]


def test_find_by_message_for_idempotency(engine):
    repo = PendingBillRepo(engine)
    repo.create(**_fields(source_message_id="m9"))
    assert repo.find_by_message("habit-pilates", "m9") is not None
    assert repo.find_by_message("habit-pilates", "nope") is None


def test_set_status_records_resolution_fields(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields())
    repo.set_status(pid, "posted", resolved=True, posted_bill_id="B1",
                    slack_channel="C1", slack_ts="1.0001")
    row = repo.get(pid)
    assert row.status == "posted"
    assert row.posted_bill_id == "B1"
    assert row.slack_channel == "C1" and row.slack_ts == "1.0001"
    assert row.resolved_at is not None


def test_find_by_slack(engine):
    repo = PendingBillRepo(engine)
    pid = repo.create(**_fields(source_message_id="ms"))
    repo.set_status(pid, "pending", slack_channel="C1", slack_ts="9.9")
    found = repo.find_by_slack("C1", "9.9")
    assert found is not None and found.id == pid
    assert repo.find_by_slack("C1", "0.0") is None
