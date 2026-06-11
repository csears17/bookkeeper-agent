from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.types import BillProposal


def _proposal():
    return BillProposal(
        client_key="habit-pilates", client_display="Habit Pilates", company_realm="111",
        vendor_name="ACME", is_new_vendor=False, total=Decimal("250.00"), currency="USD",
        txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30), doc_number="INV-100",
        proposed_account_name="Supplies", confidence=0.9, reasoning="precedent",
        pdf_filename="invoice.pdf",
    )


def test_post_proposal_records_and_returns_ref():
    slack = FakeSlackConnector()
    ref = slack.post_proposal("C-APPROVALS", _proposal())
    assert ref.channel == "C-APPROVALS" and ref.ts
    assert len(slack.posted) == 1
    channel, proposal = slack.posted[0]
    assert channel == "C-APPROVALS" and proposal.vendor_name == "ACME"


def test_post_receipt_records_thread():
    slack = FakeSlackConnector()
    parent = slack.post_proposal("C-APPROVALS", _proposal())
    slack.post_receipt("C-APPROVALS", "Posted bill B1 to Habit Pilates", thread_ts=parent.ts)
    assert slack.receipts == [("C-APPROVALS", "Posted bill B1 to Habit Pilates", parent.ts)]


def test_timestamps_are_unique():
    slack = FakeSlackConnector()
    a = slack.post_proposal("C", _proposal())
    b = slack.post_proposal("C", _proposal())
    assert a.ts != b.ts
