from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.qbo import QboConnector
from bookkeeper_agent.connectors.qbo_http import HttpxQboConnector, QboApiError
from bookkeeper_agent.connectors.types import Attachment, BillDraft, BillLine, VendorDraft

REALM = "111"


class _StubHttp:
    def __init__(self):
        self.calls = []
        self._responses = {}

    def queue(self, key, response):
        self._responses[key] = response

    def __call__(self, method, url, *, access_token, params=None, json=None, files=None, data=None):
        self.calls.append({"method": method, "url": url, "access_token": access_token,
                           "params": params, "json": json, "files": files, "data": data})
        for key, resp in self._responses.items():
            if key in url or (params and key in str(params)):
                return resp
        return {}


def _conn(http, token="AT"):
    return HttpxQboConnector(lambda realm: token, base_url="https://sandbox-quickbooks.api.intuit.com",
                             http=http)


def test_satisfies_protocol():
    assert isinstance(_conn(_StubHttp()), QboConnector)


def test_find_vendor_queries_and_parses():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Vendor": [{"Id": "7", "DisplayName": "ACME"}]}})
    v = _conn(http).find_vendor(REALM, "ACME")
    assert v.id == "7" and v.display_name == "ACME"
    call = http.calls[0]
    assert call["method"] == "GET" and f"/v3/company/{REALM}/query" in call["url"]
    assert call["access_token"] == "AT"
    assert "ACME" in str(call["params"])


def test_find_vendor_none_when_empty():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {}})
    assert _conn(http).find_vendor(REALM, "Nobody") is None


def test_list_accounts_parses():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Account": [
        {"Id": "33", "Name": "Supplies", "AccountType": "Expense"}]}})
    accts = _conn(http).list_accounts(REALM)
    assert accts[0].id == "33" and accts[0].name == "Supplies" and accts[0].account_type == "Expense"


def test_find_duplicate_bill_matches_doc_and_total():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Bill": [
        {"Id": "90", "DocNumber": "INV-100", "TotalAmt": 250.0,
         "VendorRef": {"value": "7"}}]}})
    dup = _conn(http).find_duplicate_bill(REALM, "7", "INV-100", Decimal("250.00"))
    assert dup is not None and dup.id == "90"
    assert _conn(http).find_duplicate_bill(REALM, "7", "INV-100", Decimal("999.00")) is None


def test_create_vendor_posts_and_parses():
    http = _StubHttp()
    http.queue("/vendor", {"Vendor": {"Id": "12", "DisplayName": "New Co"}})
    v = _conn(http).create_vendor(REALM, VendorDraft(display_name="New Co"))
    assert v.id == "12" and v.display_name == "New Co"
    call = http.calls[0]
    assert call["method"] == "POST" and call["url"].endswith(f"/v3/company/{REALM}/vendor")
    assert call["json"]["DisplayName"] == "New Co"


def test_create_bill_builds_single_line_and_parses():
    http = _StubHttp()
    http.queue("/bill", {"Bill": {"Id": "55", "DocNumber": "INV-100", "TotalAmt": 250.0,
                                  "VendorRef": {"value": "7"}}})
    draft = BillDraft(vendor_id="7", txn_date=date(2026, 6, 1), total=Decimal("250.00"),
                      lines=(BillLine(amount=Decimal("250.00"), account_id="33", description="Supplies"),),
                      due_date=date(2026, 6, 30), doc_number="INV-100")
    bill = _conn(http).create_bill(REALM, draft)
    assert bill.id == "55" and bill.total == Decimal("250.00")
    body = http.calls[0]["json"]
    assert body["VendorRef"]["value"] == "7"
    assert body["TxnDate"] == "2026-06-01" and body["DueDate"] == "2026-06-30"
    assert body["DocNumber"] == "INV-100"
    line = body["Line"][0]
    assert line["DetailType"] == "AccountBasedExpenseLineDetail"
    assert line["AccountBasedExpenseLineDetail"]["AccountRef"]["value"] == "33"
    assert float(line["Amount"]) == 250.0


def test_attach_pdf_uploads_multipart():
    http = _StubHttp()
    http.queue("/upload", {"AttachableResponse": [{"Attachable": {"Id": "att1"}}]})
    _conn(http).attach_pdf(REALM, "55", Attachment("invoice.pdf", "application/pdf", b"%PDF"))
    call = http.calls[0]
    assert call["method"] == "POST" and call["url"].endswith(f"/v3/company/{REALM}/upload")
    assert call["files"] is not None


def test_recent_bills_for_vendor_filters_client_side_no_vendorref_sql():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Bill": [
        {"Id": "1", "TotalAmt": 10.0, "DocNumber": "A", "VendorRef": {"value": "7"}},
        {"Id": "2", "TotalAmt": 20.0, "DocNumber": "B", "VendorRef": {"value": "9"}},
        {"Id": "3", "TotalAmt": 30.0, "DocNumber": "C", "VendorRef": {"value": "7"}},
    ]}})
    bills = _conn(http).recent_bills_for_vendor(REALM, "7")
    assert [b.id for b in bills] == ["1", "3"]
    # must NOT filter by VendorRef in the SQL (QBO doesn't reliably support it)
    assert "VendorRef" not in str(http.calls[0]["params"])


def test_vendor_account_history_aggregates_account_usage():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Bill": [
        {"Id": "1", "VendorRef": {"value": "7"}, "Line": [
            {"AccountBasedExpenseLineDetail": {"AccountRef": {"value": "33", "name": "Supplies"}}}]},
        {"Id": "2", "VendorRef": {"value": "7"}, "Line": [
            {"AccountBasedExpenseLineDetail": {"AccountRef": {"value": "33", "name": "Supplies"}}}]},
        {"Id": "3", "VendorRef": {"value": "9"}, "Line": [  # other vendor, ignored
            {"AccountBasedExpenseLineDetail": {"AccountRef": {"value": "44", "name": "Rent"}}}]},
    ]}})
    stats = _conn(http).vendor_account_history(REALM, "7")
    assert len(stats) == 1
    assert stats[0].account_id == "33" and stats[0].account_name == "Supplies" and stats[0].count == 2


def test_find_duplicate_bill_queries_by_docnumber_not_vendorref():
    http = _StubHttp()
    http.queue("query", {"QueryResponse": {"Bill": [
        {"Id": "90", "DocNumber": "INV-100", "TotalAmt": 250.0, "VendorRef": {"value": "7"}}]}})
    _conn(http).find_duplicate_bill(REALM, "7", "INV-100", Decimal("250.00"))
    params = str(http.calls[0]["params"])
    assert "DocNumber" in params and "VendorRef" not in params


def test_attach_pdf_per_file_fault_raises():
    http = _StubHttp()
    http.queue("/upload", {"AttachableResponse": [{"Fault": {"Error": [{"Message": "FileTooLarge"}]}}]})
    with pytest.raises(QboApiError, match="FileTooLarge"):
        _conn(http).attach_pdf(REALM, "55", Attachment("x.pdf", "application/pdf", b"%PDF"))


def test_api_error_raises():
    http = _StubHttp()
    http.queue("query", {"Fault": {"Error": [{"Message": "AuthenticationFailed"}]}})
    with pytest.raises(QboApiError, match="AuthenticationFailed"):
        _conn(http).find_vendor(REALM, "ACME")
