from datetime import date

from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    BillLine,
    Vendor,
    VendorDraft,
)

REALM = "111"


def test_find_vendor_case_insensitive():
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME Supplies"))
    assert qbo.find_vendor(REALM, "acme supplies").id == "V1"
    assert qbo.find_vendor(REALM, "Unknown") is None


def test_list_accounts_and_realm_isolation():
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    qbo.seed_account("222", Account(id="A9", name="Rent", account_type="Expense"))
    names = [a.name for a in qbo.list_accounts(REALM)]
    assert names == ["Supplies"]


def test_recent_bills_for_vendor():
    qbo = FakeQboConnector()
    qbo.seed_bill(REALM, Bill(id="B1", vendor_id="V1", total=100.0, doc_number="1"))
    qbo.seed_bill(REALM, Bill(id="B2", vendor_id="V2", total=50.0, doc_number="2"))
    bills = qbo.recent_bills_for_vendor(REALM, "V1")
    assert [b.id for b in bills] == ["B1"]


def test_find_duplicate_bill_matches_vendor_doc_total():
    qbo = FakeQboConnector()
    qbo.seed_bill(REALM, Bill(id="B1", vendor_id="V1", total=250.0, doc_number="INV-100"))
    dup = qbo.find_duplicate_bill(REALM, "V1", "INV-100", 250.0)
    assert dup is not None and dup.id == "B1"
    assert qbo.find_duplicate_bill(REALM, "V1", "INV-100", 999.0) is None
    assert qbo.find_duplicate_bill(REALM, "V1", "OTHER", 250.0) is None


def test_create_vendor_allocates_id_and_is_findable():
    qbo = FakeQboConnector()
    v = qbo.create_vendor(REALM, VendorDraft(display_name="New Vendor"))
    assert v.id
    assert qbo.find_vendor(REALM, "new vendor").id == v.id


def test_create_bill_records_draft_and_returns_bill():
    qbo = FakeQboConnector()
    draft = BillDraft(
        vendor_id="V1", txn_date=date(2026, 6, 1), total=250.0,
        lines=(BillLine(amount=250.0, account_id="A1"),), doc_number="INV-100",
    )
    bill = qbo.create_bill(REALM, draft)
    assert bill.id and bill.total == 250.0
    assert qbo.created_bills == [(REALM, draft)]
    # the created bill is now duplicate-detectable
    assert qbo.find_duplicate_bill(REALM, "V1", "INV-100", 250.0).id == bill.id


def test_attach_pdf_records():
    qbo = FakeQboConnector()
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    qbo.attach_pdf(REALM, "B1", att)
    assert qbo.attachments == [(REALM, "B1", att)]
