from __future__ import annotations

from decimal import Decimal
from typing import Callable

from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    Vendor,
    VendorAccountStat,
    VendorDraft,
)

_MINOR_VERSION = "65"


class QboApiError(RuntimeError):
    """Raised when a QBO API call returns a Fault."""


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


class HttpxQboConnector:
    """Real QboConnector over QBO API v3. `token_for(realm)` yields a current
    access token (QboTokenManager.access_token); the HTTP transport is injected
    so every method is unit-tested against canned QBO JSON with no network."""

    def __init__(self, token_for: Callable[[str], str], *, base_url: str,
                 http: Callable[..., dict] | None = None):
        self._token_for = token_for
        self._base = base_url.rstrip("/")
        self._http = http or self._default_http

    # --- HTTP plumbing ---
    def _default_http(self, method, url, *, access_token, params=None, json=None,
                      files=None, data=None) -> dict:
        import httpx

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        resp = httpx.request(method, url, params=params, json=json, files=files, data=data,
                             headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _call(self, realm, method, path, **kw) -> dict:
        resp = self._http(method, f"{self._base}{path}", access_token=self._token_for(realm), **kw)
        fault = resp.get("Fault")
        if fault:
            errors = fault.get("Error", [{}])
            raise QboApiError(errors[0].get("Message", "unknown_error"))
        return resp

    def _query(self, realm, sql) -> dict:
        resp = self._call(realm, "GET", f"/v3/company/{realm}/query",
                          params={"query": sql, "minorversion": _MINOR_VERSION})
        return resp.get("QueryResponse", {})

    # --- QboConnector protocol ---
    def find_vendor(self, realm, display_name):
        rows = self._query(realm, f"SELECT * FROM Vendor WHERE DisplayName = '{_escape(display_name)}'")
        vendors = rows.get("Vendor", [])
        if not vendors:
            return None
        v = vendors[0]
        return Vendor(id=str(v["Id"]), display_name=v["DisplayName"])

    def list_accounts(self, realm):
        rows = self._query(realm, "SELECT * FROM Account WHERE Active = true MAXRESULTS 1000")
        return [
            Account(id=str(a["Id"]), name=a["Name"], account_type=a.get("AccountType", ""))
            for a in rows.get("Account", [])
        ]

    def recent_bills_for_vendor(self, realm, vendor_id, limit=20):
        rows = self._query(
            realm,
            f"SELECT * FROM Bill WHERE VendorRef = '{_escape(vendor_id)}' "
            f"ORDER BY TxnDate DESC MAXRESULTS {int(limit)}",
        )
        return [
            Bill(id=str(b["Id"]), vendor_id=vendor_id,
                 total=Decimal(str(b.get("TotalAmt", "0"))), doc_number=b.get("DocNumber"))
            for b in rows.get("Bill", [])
        ]

    def vendor_account_history(self, realm, vendor_id):
        rows = self._query(
            realm,
            f"SELECT * FROM Bill WHERE VendorRef = '{_escape(vendor_id)}' "
            "ORDER BY TxnDate DESC MAXRESULTS 50",
        )
        counts: dict[str, list] = {}  # account_id -> [name, count]
        for b in rows.get("Bill", []):
            for line in b.get("Line", []):
                detail = line.get("AccountBasedExpenseLineDetail")
                if not detail:
                    continue
                ref = detail.get("AccountRef", {})
                aid = str(ref.get("value", ""))
                if not aid:
                    continue
                entry = counts.setdefault(aid, [ref.get("name", aid), 0])
                entry[1] += 1
        return [
            VendorAccountStat(account_id=aid, account_name=name, count=count)
            for aid, (name, count) in counts.items()
        ]

    def find_duplicate_bill(self, realm, vendor_id, doc_number, total):
        if not doc_number:
            return None
        rows = self._query(
            realm,
            f"SELECT * FROM Bill WHERE VendorRef = '{_escape(vendor_id)}' "
            f"AND DocNumber = '{_escape(doc_number)}'",
        )
        for b in rows.get("Bill", []):
            if Decimal(str(b.get("TotalAmt", "0"))) == total:
                return Bill(id=str(b["Id"]), vendor_id=vendor_id,
                            total=total, doc_number=doc_number)
        return None

    def create_vendor(self, realm, draft: VendorDraft):
        body: dict = {"DisplayName": draft.display_name}
        if draft.email:
            body["PrimaryEmailAddr"] = {"Address": draft.email}
        resp = self._call(realm, "POST", f"/v3/company/{realm}/vendor",
                          params={"minorversion": _MINOR_VERSION}, json=body)
        v = resp["Vendor"]
        return Vendor(id=str(v["Id"]), display_name=v["DisplayName"])

    def create_bill(self, realm, draft: BillDraft):
        lines = [{
            "Amount": float(line.amount),
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": line.description or "",
            "AccountBasedExpenseLineDetail": {"AccountRef": {"value": line.account_id}},
        } for line in draft.lines]
        body: dict = {
            "VendorRef": {"value": draft.vendor_id},
            "TxnDate": draft.txn_date.isoformat(),
            "CurrencyRef": {"value": draft.currency},
            "Line": lines,
        }
        if draft.due_date:
            body["DueDate"] = draft.due_date.isoformat()
        if draft.doc_number:
            body["DocNumber"] = draft.doc_number
        resp = self._call(realm, "POST", f"/v3/company/{realm}/bill",
                          params={"minorversion": _MINOR_VERSION}, json=body)
        b = resp["Bill"]
        return Bill(id=str(b["Id"]), vendor_id=draft.vendor_id,
                    total=Decimal(str(b.get("TotalAmt", draft.total))), doc_number=b.get("DocNumber"))

    def attach_pdf(self, realm, bill_id, attachment: Attachment):
        import json as _json

        metadata = {
            "AttachableRef": [{"EntityRef": {"type": "Bill", "value": str(bill_id)}}],
            "FileName": attachment.filename,
            "ContentType": attachment.mime_type,
        }
        files = {
            "file_metadata_01": ("metadata.json", _json.dumps(metadata), "application/json"),
            "file_content_01": (attachment.filename, attachment.content, attachment.mime_type),
        }
        self._call(realm, "POST", f"/v3/company/{realm}/upload",
                   params={"minorversion": _MINOR_VERSION}, files=files)
