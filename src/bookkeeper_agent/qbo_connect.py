"""Connect a QuickBooks company (OAuth login) and smoke-test the live API.

Usage (run from the project folder, with .env filled in):

    # 1. Connect a company — opens a browser to log in & authorize:
    .\\.venv\\Scripts\\python.exe -m bookkeeper_agent.qbo_connect

    # 2. Smoke-test the live API against that company (use the realm it printed):
    .\\.venv\\Scripts\\python.exe -m bookkeeper_agent.qbo_connect --smoke <realmId>

Only the encrypted refresh token is stored (in the local DB via TokenStore).
"""
from __future__ import annotations

import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from bookkeeper_agent.connectors.qbo_oauth import QboOAuth, QboOAuthConfig
from bookkeeper_agent.connectors.qbo_tokens import QboTokenManager
from bookkeeper_agent.connectors.tokens import TokenStore
from bookkeeper_agent.db.base import init_db, make_engine
from bookkeeper_agent.security import TokenCipher

REDIRECT_URI = "http://localhost:8000/qbo/callback"
SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
PROD_BASE = "https://quickbooks.api.intuit.com"


def _base_url(environment: str) -> str:
    return PROD_BASE if environment == "production" else SANDBOX_BASE


def _load():
    load_dotenv(".env")
    client_id = os.environ.get("QBO_CLIENT_ID")
    client_secret = os.environ.get("QBO_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("Set QBO_CLIENT_ID and QBO_CLIENT_SECRET in .env first.")
    keys = [k.strip() for k in os.environ.get("TOKEN_ENC_KEYS", "").split(",") if k.strip()]
    if not keys:
        raise SystemExit("Set TOKEN_ENC_KEYS in .env first (the Fernet key).")
    environment = os.environ.get("QBO_ENV", "sandbox")
    engine = make_engine(os.environ.get("DB_PATH", "bookkeeper.db"))
    init_db(engine)
    store = TokenStore(engine, TokenCipher(keys))
    oauth = QboOAuth(QboOAuthConfig(client_id, client_secret, REDIRECT_URI, environment))
    manager = QboTokenManager(store, oauth)
    return engine, store, oauth, manager, environment


def handle_callback(params: dict, expected_state: str, oauth, manager) -> tuple[str, str]:
    """Validate the redirect, exchange the code, persist the encrypted refresh token.
    Returns (realmId, human message). Raises ValueError on a bad callback."""
    state = (params.get("state") or [""])[0]
    if state != expected_state:
        raise ValueError("state mismatch — possible CSRF; aborting")
    code = (params.get("code") or [""])[0]
    realm = (params.get("realmId") or [""])[0]
    if not code or not realm:
        raise ValueError("missing code or realmId in the callback")
    tokens = oauth.exchange_code(code)
    manager.save_connection(realm, tokens.refresh_token)
    return realm, f"Connected QuickBooks company (realm {realm})."


def connect() -> None:
    _engine, _store, oauth, manager, environment = _load()
    state = secrets.token_urlsafe(16)
    url = oauth.authorize_url(state)
    result: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/qbo/callback":
                self.send_response(404)
                self.end_headers()
                return
            try:
                realm, message = handle_callback(parse_qs(parsed.query), state, oauth, manager)
                result["realm"] = realm
                body = (f"<h2>{message}</h2><p>Realm id to put in clients.toml: "
                        f"<b>{realm}</b>. You can close this tab.</p>")
            except Exception as exc:  # noqa: BLE001
                body = f"<h2>Connect failed</h2><p>{exc}</p>"
            result["done"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):  # silence default logging
            pass

    server = HTTPServer(("127.0.0.1", 8000), _Handler)
    print(f"QBO environment: {environment}")
    print("Opening your browser to authorize. If it doesn't open, paste this URL:\n" + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    while not result.get("done"):
        server.handle_request()
    server.server_close()
    if result.get("realm"):
        print(f"\n[OK] Connected. Realm id: {result['realm']}")
        print("Put this as qbo_realm_id for the client in clients.toml.")
    else:
        print("\n[FAILED] No connection captured — see the browser tab for the error.")


def smoke(realm: str) -> None:
    from datetime import date
    from decimal import Decimal

    from bookkeeper_agent.connectors.qbo_http import HttpxQboConnector
    from bookkeeper_agent.connectors.types import Attachment, BillDraft, BillLine, VendorDraft

    _engine, _store, _oauth, manager, environment = _load()
    conn = HttpxQboConnector(manager.access_token, base_url=_base_url(environment))

    accounts = conn.list_accounts(realm)
    print(f"list_accounts -> {len(accounts)} accounts; sample: {[a.name for a in accounts[:5]]}")
    if not accounts:
        raise SystemExit("No accounts returned — check the realm and connection.")
    expense = next((a for a in accounts if a.account_type == "Expense"), accounts[0])

    vendor = conn.create_vendor(realm, VendorDraft(display_name="Bookkeeper Agent Smoke Test"))
    print(f"create_vendor -> {vendor.id} {vendor.display_name}")

    draft = BillDraft(
        vendor_id=vendor.id, txn_date=date.today(), total=Decimal("1.23"),
        lines=(BillLine(amount=Decimal("1.23"), account_id=expense.id, description="smoke test"),),
        doc_number="SMOKE-1",
    )
    bill = conn.create_bill(realm, draft)
    print(f"create_bill -> id {bill.id}, total {bill.total}")

    conn.attach_pdf(realm, bill.id, Attachment("smoke.pdf", "application/pdf", b"%PDF-1.4\n% smoke test\n"))
    print(f"attach_pdf -> attached to bill {bill.id}")
    print("\n[OK] Smoke test complete. Open the test bill in the QBO sandbox UI, confirm the "
          "PDF is attached, then delete the test vendor/bill.")


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--smoke":
        if len(argv) < 2:
            print("usage: python -m bookkeeper_agent.qbo_connect --smoke <realmId>")
            return 2
        smoke(argv[1])
        return 0
    connect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
