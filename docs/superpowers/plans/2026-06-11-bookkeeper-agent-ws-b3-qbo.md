# Bookkeeper Agent — WS-B3 Real QuickBooks Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the real QuickBooks Online side — the **"Connect to QuickBooks" OAuth login flow** (authorize URL → code exchange → store encrypted refresh token + realm), automatic **token refresh**, and the real `HttpxQboConnector` satisfying the WS-B1 `QboConnector` Protocol (vendor match, accounts, vendor history, duplicate check, create vendor/bill, attach PDF). All offline-testable via injected HTTP; live verification is a single "Connect" against the Intuit sandbox.

**Architecture:** Onboarding is **login, not key entry** — the operator registers one Intuit app (client id/secret in `.env`); each QB company is added by an OAuth "Connect" (login → authorize), which stores only an encrypted refresh token + realm via the WS-C2 `TokenStore`. `QboOAuth` builds the authorize URL and exchanges/refreshes tokens (HTTP injected). `QboTokenManager` turns a realm into a current access token (load refresh token → refresh → cache access in-memory to expiry → persist rotated refresh token). `HttpxQboConnector` makes QBO API v3 calls using a per-realm access token from the manager, with the HTTP transport injected so every method is unit-tested against canned QBO JSON with no network.

**Tech Stack:** Python 3.12, `httpx` (already pinned), existing deps. Builds on WS-B1 (`QboConnector` Protocol + domain types) and WS-C2 (`TokenStore`).

This is WS-B3 of the reprioritized roadmap (spec §9b). After it: the Slack-drop adapter + Socket Mode runner + WS-C4 write-gate → first usable drop→approve→QBO flow. Spec: `docs/superpowers/specs/2026-06-11-bookkeeper-agent-bills-from-email-design.md`. Redirect URI is fixed at `http://localhost:8000/qbo/callback`.

---

## File structure (created by this plan)

```
src/bookkeeper_agent/connectors/
  qbo_oauth.py    # NEW: QboOAuthConfig, QboTokens, QboOAuth (authorize_url / exchange_code / refresh)
  qbo_tokens.py   # NEW: QboTokenManager (realm -> current access token; persists rotated refresh)
  qbo_http.py     # NEW: HttpxQboConnector (the 8 QboConnector methods over QBO API v3)
tests/
  test_qbo_oauth.py
  test_qbo_tokens.py
  test_qbo_http.py
```

---

## Task 1: QBO OAuth (authorize URL, code exchange, refresh)

**Files:**
- Create: `src/bookkeeper_agent/connectors/qbo_oauth.py`
- Test: `tests/test_qbo_oauth.py`

- [ ] **Step 1: Write the failing test**

`tests/test_qbo_oauth.py`:
```python
from urllib.parse import parse_qs, urlparse

import pytest

from bookkeeper_agent.connectors.qbo_oauth import QboOAuth, QboOAuthConfig, QboTokens

CFG = QboOAuthConfig(
    client_id="ABC", client_secret="secret",
    redirect_uri="http://localhost:8000/qbo/callback", environment="sandbox",
)


def test_authorize_url_has_required_params():
    url = QboOAuth(CFG).authorize_url(state="xyz")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["ABC"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == ["com.intuit.quickbooks.accounting"]
    assert q["redirect_uri"] == ["http://localhost:8000/qbo/callback"]
    assert q["state"] == ["xyz"]
    assert url.startswith("https://appcenter.intuit.com/connect/oauth2?")


class _StubHttp:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def __call__(self, url, *, data, auth, headers):
        self.calls.append({"url": url, "data": data, "auth": auth, "headers": headers})
        return self._response


def test_exchange_code_returns_tokens_and_uses_basic_auth():
    http = _StubHttp({"access_token": "AT", "refresh_token": "RT",
                      "expires_in": 3600, "x_refresh_token_expires_in": 8640000})
    tokens = QboOAuth(CFG, http_post=http).exchange_code(code="the-code")
    assert tokens == QboTokens(access_token="AT", refresh_token="RT", expires_in=3600)
    call = http.calls[0]
    assert call["url"] == "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    assert call["auth"] == ("ABC", "secret")  # client_id:client_secret Basic auth
    assert call["data"]["grant_type"] == "authorization_code"
    assert call["data"]["code"] == "the-code"
    assert call["data"]["redirect_uri"] == "http://localhost:8000/qbo/callback"


def test_refresh_uses_refresh_grant():
    http = _StubHttp({"access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600})
    tokens = QboOAuth(CFG, http_post=http).refresh("old-refresh")
    assert tokens.access_token == "AT2" and tokens.refresh_token == "RT2"
    assert http.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}


def test_token_endpoint_error_raises():
    http = _StubHttp({"error": "invalid_grant"})
    with pytest.raises(QboOAuth.OAuthError, match="invalid_grant"):
        QboOAuth(CFG, http_post=http).refresh("bad")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_oauth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.qbo_oauth'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/qbo_oauth.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

_AUTHORIZE = "https://appcenter.intuit.com/connect/oauth2"
_TOKEN = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_SCOPE = "com.intuit.quickbooks.accounting"


@dataclass(frozen=True)
class QboOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    environment: str = "sandbox"  # "sandbox" | "production"


@dataclass(frozen=True)
class QboTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class QboOAuth:
    """Builds the Connect-to-QuickBooks login URL and exchanges/refreshes tokens.
    The token-endpoint HTTP poster is injected for offline testing."""

    class OAuthError(RuntimeError):
        pass

    def __init__(self, config: QboOAuthConfig, *, http_post: Callable[..., dict] | None = None):
        self._cfg = config
        self._http_post = http_post or self._default_post

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._cfg.client_id,
            "response_type": "code",
            "scope": _SCOPE,
            "redirect_uri": self._cfg.redirect_uri,
            "state": state,
        }
        return f"{_AUTHORIZE}?{urlencode(params)}"

    def exchange_code(self, code: str) -> QboTokens:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_uri,
        })

    def refresh(self, refresh_token: str) -> QboTokens:
        return self._token_request({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })

    def _token_request(self, data: dict) -> QboTokens:
        resp = self._http_post(
            _TOKEN,
            data=data,
            auth=(self._cfg.client_id, self._cfg.client_secret),
            headers={"Accept": "application/json"},
        )
        if "access_token" not in resp:
            raise self.OAuthError(resp.get("error", "unknown_error"))
        return QboTokens(
            access_token=resp["access_token"],
            refresh_token=resp["refresh_token"],
            expires_in=int(resp.get("expires_in", 3600)),
        )

    def _default_post(self, url, *, data, auth, headers) -> dict:
        import httpx

        resp = httpx.post(url, data=data, auth=auth, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_oauth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/qbo_oauth.py tests/test_qbo_oauth.py
git -c commit.gpgsign=false commit -m "feat(ws-b3): QBO OAuth (Connect login URL, code exchange, refresh)"
```

---

## Task 2: QboTokenManager (realm → current access token)

**Files:**
- Create: `src/bookkeeper_agent/connectors/qbo_tokens.py`
- Test: `tests/test_qbo_tokens.py`

- [ ] **Step 1: Write the failing test**

`tests/test_qbo_tokens.py`:
```python
from cryptography.fernet import Fernet

from bookkeeper_agent.connectors.qbo_oauth import QboOAuth, QboOAuthConfig, QboTokens
from bookkeeper_agent.connectors.qbo_tokens import QboTokenManager
from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.security import TokenCipher

CFG = QboOAuthConfig(client_id="ABC", client_secret="secret",
                     redirect_uri="http://localhost:8000/qbo/callback", environment="sandbox")


def _store(engine):
    return TokenStore(engine, TokenCipher([Fernet.generate_key().decode()]))


class _FakeOAuth:
    def __init__(self):
        self.refreshes: list[str] = []
        self._n = 0

    def refresh(self, refresh_token):
        self.refreshes.append(refresh_token)
        self._n += 1
        return QboTokens(access_token=f"AT{self._n}", refresh_token=f"RT{self._n}", expires_in=3600)


def test_save_connection_persists_encrypted_refresh(engine):
    store = _store(engine)
    mgr = QboTokenManager(store, _FakeOAuth())
    mgr.save_connection("111", "RT0")
    assert store.get_secret("qbo", "111") == "RT0"


def test_access_token_refreshes_and_persists_rotated_refresh(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "RT0")
    oauth = _FakeOAuth()
    mgr = QboTokenManager(store, oauth)

    at = mgr.access_token("111")
    assert at == "AT1"
    assert oauth.refreshes == ["RT0"]
    # rotated refresh token persisted for next time
    assert store.get_secret("qbo", "111") == "RT1"


def test_access_token_is_cached_until_expiry(engine):
    store = _store(engine)
    store.put_secret("qbo", "111", "RT0")
    oauth = _FakeOAuth()
    mgr = QboTokenManager(store, oauth)

    first = mgr.access_token("111")
    second = mgr.access_token("111")  # cached — no second refresh
    assert first == second == "AT1"
    assert oauth.refreshes == ["RT0"]  # refreshed once


def test_unknown_realm_raises(engine):
    mgr = QboTokenManager(_store(engine), _FakeOAuth())
    import pytest
    with pytest.raises(KeyError):
        mgr.access_token("999")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.qbo_tokens'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/qbo_tokens.py`:
```python
from __future__ import annotations

import time
from dataclasses import dataclass

from bookkeeper_agent.connectors.tokens import TokenStore

_SERVICE = "qbo"
_EXPIRY_SKEW_SECONDS = 120  # refresh a little early


@dataclass
class _CachedAccess:
    token: str
    expires_at: float


class QboTokenManager:
    """Turns a realm into a current access token. The encrypted refresh token is
    the only persisted secret (via TokenStore); access tokens are short-lived and
    cached in memory. A refresh rotates the refresh token, which is re-persisted."""

    def __init__(self, token_store: TokenStore, oauth, *, now=time.monotonic):
        self._store = token_store
        self._oauth = oauth
        self._now = now
        self._cache: dict[str, _CachedAccess] = {}

    def save_connection(self, realm: str, refresh_token: str) -> None:
        """Called by the Connect flow after a successful authorize."""
        self._store.put_secret(_SERVICE, realm, refresh_token)

    def access_token(self, realm: str) -> str:
        cached = self._cache.get(realm)
        if cached is not None and cached.expires_at - _EXPIRY_SKEW_SECONDS > self._now():
            return cached.token

        refresh_token = self._store.get_secret(_SERVICE, realm)
        if refresh_token is None:
            raise KeyError(f"no QBO connection stored for realm {realm!r} — run Connect first")

        tokens = self._oauth.refresh(refresh_token)
        # Persist the rotated refresh token so the next refresh works.
        self._store.put_secret(_SERVICE, realm, tokens.refresh_token)
        self._cache[realm] = _CachedAccess(
            token=tokens.access_token, expires_at=self._now() + tokens.expires_in
        )
        return tokens.access_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_tokens.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/qbo_tokens.py tests/test_qbo_tokens.py
git -c commit.gpgsign=false commit -m "feat(ws-b3): QboTokenManager (realm -> access token, rotated-refresh persistence)"
```

---

## Task 3: HttpxQboConnector (QBO API v3)

**Files:**
- Create: `src/bookkeeper_agent/connectors/qbo_http.py`
- Test: `tests/test_qbo_http.py`

- [ ] **Step 1: Write the failing test**

`tests/test_qbo_http.py`:
```python
from datetime import date
from decimal import Decimal

import pytest

from bookkeeper_agent.connectors.qbo import QboConnector
from bookkeeper_agent.connectors.qbo_http import HttpxQboConnector, QboApiError
from bookkeeper_agent.connectors.types import Attachment, BillDraft, BillLine, VendorDraft

REALM = "111"


class _StubHttp:
    """Records calls; returns queued responses by (method, path-substring)."""

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
    assert "ACME" in str(call["params"])  # the DisplayName filter


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
    # different total -> not a duplicate
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
    assert call["files"] is not None  # multipart upload


def test_api_error_raises():
    http = _StubHttp()
    http.queue("query", {"Fault": {"Error": [{"Message": "AuthenticationFailed"}]}})
    with pytest.raises(QboApiError, match="AuthenticationFailed"):
        _conn(http).find_vendor(REALM, "ACME")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bookkeeper_agent.connectors.qbo_http'`

- [ ] **Step 3: Write minimal implementation**

`src/bookkeeper_agent/connectors/qbo_http.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest tests/test_qbo_http.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/bookkeeper_agent/connectors/qbo_http.py tests/test_qbo_http.py
git -c commit.gpgsign=false commit -m "feat(ws-b3): HttpxQboConnector (QBO API v3 read/write/attach)"
```

---

## Task 4: Full-suite green + WS-B3 wrap

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && ./.venv/Scripts/python.exe -m pytest`
Expected: PASS — prior 140 plus WS-B3 (5 + 4 + 9 = 18), i.e. ~158 total. All must pass.

- [ ] **Step 2: Confirm the real connector satisfies the Protocol**

Run:
```bash
cd /c/Users/Cole/bookkeeper-agent && PYTHONPATH=src ./.venv/Scripts/python.exe -c "from bookkeeper_agent.connectors.qbo import QboConnector; from bookkeeper_agent.connectors.qbo_http import HttpxQboConnector; print(isinstance(HttpxQboConnector(lambda r: 'AT', base_url='https://x', http=lambda *a, **k: {}), QboConnector))"
```
Expected: `True`

- [ ] **Step 3: Confirm no live call in the suite**

Run: `cd /c/Users/Cole/bookkeeper-agent && grep -rnE 'httpx\.(post|get|request)\(' tests/ ; echo "exit $?"`
Expected: no matches (HTTP injected everywhere).

- [ ] **Step 4: Confirm clean tree / no secrets tracked**

Run: `git status --porcelain` and `git ls-files | grep -E '\.(env|db)$|clients\.toml'` (expect no matches).

- [ ] **Step 5: Tag the workstream**

```bash
git tag ws-b3
```

---

## Self-review against the spec

- **§6 / UX "just log in"** → `QboOAuth.authorize_url` is the Connect-to-QuickBooks login link; `exchange_code` + `QboTokenManager.save_connection` capture the connection from the redirect. The only one-time manual item is the single app's client id/secret in `.env`; per-company onboarding is a login. ✓
- **§5 secrets / least-privilege** → only the encrypted **refresh token** is persisted (via `TokenStore`, Fernet); access tokens are in-memory and short-lived; scope is `com.intuit.quickbooks.accounting` only; rotated refresh tokens are re-persisted so connections don't break. ✓
- **§4 vendor match / accounts / history / dup / create vendor+bill / attach PDF** → all eight `QboConnector` methods implemented over QBO API v3; `create_bill` builds a single AccountBasedExpenseLineDetail line from the draft; `attach_pdf` uses the `/upload` multipart with an `AttachableRef` to the Bill. ✓
- **money is Decimal** → totals parsed from `TotalAmt` as `Decimal(str(...))`; line `Amount` sent as `float(line.amount)` (QBO is a JSON-number API; values are 2dp). Duplicate match compares `Decimal == Decimal`. ✓
- **offline-testable** → OAuth token endpoint, token refresh, and every connector method use injected HTTP; Task 4 step 3 confirms tests make no live call. ✓
- **WS-B1 `QboConnector` Protocol satisfied** → Task 4 step 2 asserts `isinstance(HttpxQboConnector(...), QboConnector)`. ✓

**Deferred (correctly out of scope here, verified live):** the tiny **Connect web handler** (serves `http://localhost:8000/qbo/callback`, reads `code`+`realmId`+`state`, calls `exchange_code` → `save_connection`) — thin glue; the `sandbox` vs `production` base-URL wiring from config; the **first real "Connect"** against Cole's Intuit sandbox to verify the live token + API shapes. The Slack-drop adapter + Socket Mode runner + WS-C4 write-gate follow.

**Placeholder scan:** none — every code step is complete, runnable code.

**Type consistency:** `HttpxQboConnector` implements all eight `QboConnector` methods with matching signatures and returns the WS-B1 domain types (`Vendor`/`Account`/`Bill`/`VendorAccountStat`); `token_for(realm) -> str` matches `QboTokenManager.access_token`; `QboOAuth.exchange_code/refresh -> QboTokens`; `QboTokenManager.access_token(realm) -> str` / `save_connection(realm, refresh_token)`. SQL string interpolation is escaped via `_escape` (single-quote escaping) — note for the live reviewer: QBO query values are app-controlled (vendor names from extraction), so this is defense-in-depth, not user-facing injection.
```
