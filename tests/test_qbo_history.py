from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.types import VendorAccountStat


def test_vendor_account_history_empty_by_default():
    qbo = FakeQboConnector()
    assert qbo.vendor_account_history("111", "V1") == []


def test_seed_and_read_account_history():
    qbo = FakeQboConnector()
    qbo.seed_account_history("111", "V1", [
        VendorAccountStat(account_id="A1", account_name="Supplies", count=3),
        VendorAccountStat(account_id="A2", account_name="Office", count=1),
    ])
    stats = qbo.vendor_account_history("111", "V1")
    assert [s.account_name for s in stats] == ["Supplies", "Office"]
    assert stats[0].count == 3
    # realm-scoped
    assert qbo.vendor_account_history("222", "V1") == []
