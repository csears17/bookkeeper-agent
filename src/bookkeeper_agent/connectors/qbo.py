from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from bookkeeper_agent.connectors.types import (
    Account,
    Attachment,
    Bill,
    BillDraft,
    Vendor,
    VendorAccountStat,
    VendorDraft,
)


@runtime_checkable
class QboConnector(Protocol):
    """QuickBooks Online access, scoped per company (realm). Real impl: WS-B3."""

    def find_vendor(self, realm: str, display_name: str) -> Vendor | None: ...

    def list_accounts(self, realm: str) -> list[Account]: ...

    def recent_bills_for_vendor(self, realm: str, vendor_id: str, limit: int = 20) -> list[Bill]: ...

    def vendor_account_history(self, realm: str, vendor_id: str) -> list["VendorAccountStat"]: ...

    def find_duplicate_bill(
        self, realm: str, vendor_id: str, doc_number: str | None, total: Decimal
    ) -> Bill | None: ...

    def create_vendor(self, realm: str, draft: VendorDraft) -> Vendor: ...

    def create_bill(self, realm: str, draft: BillDraft) -> Bill: ...

    def attach_pdf(self, realm: str, bill_id: str, attachment: Attachment) -> None: ...


class FakeQboConnector:
    """In-memory QboConnector for tests and WS-C pipeline development.

    State is keyed by realm so cross-book isolation can be asserted. ``seed_*``
    methods set up read state; ``created_bills`` / ``created_vendors`` /
    ``attachments`` record writes for assertions.
    """

    def __init__(self) -> None:
        self._vendors: dict[str, dict[str, Vendor]] = {}  # realm -> name.lower() -> Vendor
        self._accounts: dict[str, list[Account]] = {}
        self._bills: dict[str, list[Bill]] = {}
        self._account_history: dict[tuple[str, str], list[VendorAccountStat]] = {}
        self.created_vendors: list[tuple[str, VendorDraft]] = []
        self.created_bills: list[tuple[str, BillDraft]] = []
        self.attachments: list[tuple[str, str, Attachment]] = []
        self._counter = 0

    # --- seed helpers (read state) ---

    def seed_vendor(self, realm: str, vendor: Vendor) -> None:
        self._vendors.setdefault(realm, {})[vendor.display_name.lower()] = vendor

    def seed_account(self, realm: str, account: Account) -> None:
        self._accounts.setdefault(realm, []).append(account)

    def seed_bill(self, realm: str, bill: Bill) -> None:
        self._bills.setdefault(realm, []).append(bill)

    def seed_account_history(self, realm: str, vendor_id: str, stats: list[VendorAccountStat]) -> None:
        self._account_history[(realm, vendor_id)] = list(stats)

    def _alloc(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    # --- QboConnector protocol ---

    def find_vendor(self, realm: str, display_name: str) -> Vendor | None:
        return self._vendors.get(realm, {}).get(display_name.lower())

    def list_accounts(self, realm: str) -> list[Account]:
        return list(self._accounts.get(realm, []))

    def recent_bills_for_vendor(self, realm: str, vendor_id: str, limit: int = 20) -> list[Bill]:
        return [b for b in self._bills.get(realm, []) if b.vendor_id == vendor_id][:limit]

    def vendor_account_history(self, realm: str, vendor_id: str) -> list[VendorAccountStat]:
        return list(self._account_history.get((realm, vendor_id), []))

    def find_duplicate_bill(
        self, realm: str, vendor_id: str, doc_number: str | None, total: Decimal
    ) -> Bill | None:
        for b in self._bills.get(realm, []):
            if (
                b.vendor_id == vendor_id
                and b.doc_number == doc_number
                and b.total == total
            ):
                return b
        return None

    def create_vendor(self, realm: str, draft: VendorDraft) -> Vendor:
        vendor = Vendor(id=self._alloc("V"), display_name=draft.display_name)
        self.seed_vendor(realm, vendor)
        self.created_vendors.append((realm, draft))
        return vendor

    def create_bill(self, realm: str, draft: BillDraft) -> Bill:
        bill = Bill(
            id=self._alloc("B"),
            vendor_id=draft.vendor_id,
            total=draft.total,
            doc_number=draft.doc_number,
        )
        self._bills.setdefault(realm, []).append(bill)
        self.created_bills.append((realm, draft))
        return bill

    def attach_pdf(self, realm: str, bill_id: str, attachment: Attachment) -> None:
        self.attachments.append((realm, bill_id, attachment))
