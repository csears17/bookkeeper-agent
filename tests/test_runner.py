from datetime import date
from decimal import Decimal

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.qbo import FakeQboConnector
from bookkeeper_agent.connectors.slack import FakeSlackConnector
from bookkeeper_agent.connectors.types import Account, Attachment, Vendor
from bookkeeper_agent.llm.client import FakeLlmClient
from bookkeeper_agent.llm.types import BillExtraction, CategorySuggestion
from bookkeeper_agent.pipeline.process import BillsPipeline, IntakeOutcome
from bookkeeper_agent.pipeline.store import PendingBillRepo
from bookkeeper_agent.pipeline.writegate import ApprovalGate, WriteOutcome
from bookkeeper_agent.runner import on_block_action, on_client_pick, on_file_drop

REALM = "111"
CLIENTS = {
    "habit-pilates": ClientConfig(key="habit-pilates", display_name="Habit Pilates",
                                  provider="google", mailbox="habit@unionstreet.io",
                                  qbo_realm_id=REALM, autonomy_level=0),
}


class _Slack(FakeSlackConnector):
    """FakeSlackConnector + the drop/picker methods the runner needs."""

    def __init__(self, file_content=b"%PDF"):
        super().__init__()
        self.pickers: list[tuple[str, str]] = []
        self._file_content = file_content
        self.file_infos: list[str] = []

    def post_picker(self, channel, file_id, clients):
        self.pickers.append((channel, file_id))
        return None

    def download_file(self, url):
        return self._file_content

    def file_info(self, file_id):
        self.file_infos.append(file_id)
        return {"name": "invoice.pdf", "mimetype": "application/pdf",
                "url_private": "https://files.slack.com/x"}


def _pipeline(engine, slack):
    qbo = FakeQboConnector()
    qbo.seed_account(REALM, Account(id="A1", name="Supplies", account_type="Expense"))
    llm = FakeLlmClient(
        extraction=BillExtraction(is_bill=True, vendor_name="ACME", total=Decimal("250.00"),
                                  txn_date=date(2026, 6, 1), doc_number="INV-1"),
        suggestion=CategorySuggestion(account_id="A1", account_name="Supplies",
                                      confidence=0.9, reasoning="x"))
    return BillsPipeline(llm=llm, qbo=qbo, slack=slack, pending_repo=PendingBillRepo(engine),
                         engine=engine, approval_channel="C-APPROVALS")


def _file_event(text):
    return {"type": "message", "channel": "C-DROPS", "user": "U1", "text": text,
            "files": [{"id": "F1", "name": "invoice.pdf", "mimetype": "application/pdf",
                       "url_private": "https://files.slack.com/x"}]}


def test_file_drop_with_clear_client_proposes_a_bill(engine):
    slack = _Slack()
    pipeline = _pipeline(engine, slack)
    out = on_file_drop(_file_event("this is for habit pilates"), CLIENTS, slack, pipeline)
    assert out == "processed"
    assert len(slack.posted) == 1  # a proposal card was posted
    assert slack.pickers == []


def test_file_drop_with_unclear_client_posts_picker(engine):
    slack = _Slack()
    pipeline = _pipeline(engine, slack)
    out = on_file_drop(_file_event("no client named here"), CLIENTS, slack, pipeline)
    assert out == "picker_posted"
    assert slack.pickers == [("C-DROPS", "F1")]
    assert slack.posted == []  # no proposal until a client is chosen


def test_client_pick_fetches_file_and_proposes(engine):
    slack = _Slack()
    pipeline = _pipeline(engine, slack)
    payload = {
        "user": {"id": "U1"}, "channel": {"id": "C-DROPS"}, "message": {"ts": "1.0"},
        "actions": [{"action_id": "pick_client", "block_id": "drop:F1",
                     "selected_option": {"value": "habit-pilates"}}],
    }
    out = on_client_pick(payload, CLIENTS, slack, pipeline)
    assert out == "processed"
    assert slack.file_infos == ["F1"]
    assert len(slack.posted) == 1


def test_on_block_action_routes_to_gate(engine):
    # seed a pending bill + a Slack card ref, then approve via a block action
    repo = PendingBillRepo(engine)
    pid = repo.create(client_key="habit-pilates", company_realm=REALM,
                      source_mailbox="C-DROPS", source_message_id="F1",
                      vendor_name="ACME", is_new_vendor=False, vendor_id="V1",
                      total=Decimal("250.00"), currency="USD",
                      proposed_account_id="A1", proposed_account_name="Supplies",
                      pdf_filename="invoice.pdf", pdf_bytes=b"%PDF")
    repo.set_status(pid, "pending", slack_channel="C-APPROVALS", slack_ts="9.9")
    qbo = FakeQboConnector()
    qbo.seed_vendor(REALM, Vendor(id="V1", display_name="ACME"))
    gate = ApprovalGate(qbo=qbo, slack=FakeSlackConnector(), pending_repo=repo, engine=engine)
    payload = {"user": {"id": "U1"}, "channel": {"id": "C-APPROVALS"}, "message": {"ts": "9.9"},
               "actions": [{"action_id": "approve_bill"}]}
    result = on_block_action(payload, gate)
    assert result.outcome == WriteOutcome.POSTED
    # a non-approve/reject action returns None (so the picker handler can take it)
    picker_payload = {"actions": [{"action_id": "pick_client"}]}
    assert on_block_action(picker_payload, gate) is None
