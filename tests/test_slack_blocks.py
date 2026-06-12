import json
from datetime import date
from decimal import Decimal

from bookkeeper_agent.connectors.slack_blocks import (
    client_picker_blocks,
    proposal_blocks,
    receipt_blocks,
)
from bookkeeper_agent.connectors.types import BillProposal


def _proposal(**over):
    base = dict(
        client_key="habit-pilates", client_display="Habit Pilates", company_realm="111",
        vendor_name="ACME", is_new_vendor=False, total=Decimal("250.00"), currency="USD",
        txn_date=date(2026, 6, 1), due_date=date(2026, 6, 30), doc_number="INV-100",
        proposed_account_name="Supplies", confidence=0.9, reasoning="prior ACME bills booked to Supplies",
        pdf_filename="invoice.pdf",
    )
    base.update(over)
    return BillProposal(**base)


def test_proposal_blocks_shows_company_in_bold_and_has_buttons():
    blocks = proposal_blocks(_proposal())
    text = json.dumps(blocks)
    assert "*Habit Pilates*" in text
    assert "ACME" in text and "250.00" in text and "Supplies" in text and "INV-100" in text
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions) == 1
    action_ids = {e["action_id"] for e in actions[0]["elements"]}
    assert action_ids == {"approve_bill", "reject_bill"}


def test_proposal_blocks_marks_new_vendor():
    text = json.dumps(proposal_blocks(_proposal(is_new_vendor=True)))
    assert "NEW" in text


def test_receipt_blocks_is_plain_section():
    blocks = receipt_blocks("Posted bill B1 to Habit Pilates")
    assert blocks[0]["type"] == "section"
    assert "Posted bill B1" in json.dumps(blocks)


def test_client_picker_blocks_lists_clients():
    blocks = client_picker_blocks([("habit-pilates", "Habit Pilates"), ("2expect", "2Expect LLC")])
    text = json.dumps(blocks)
    assert "Habit Pilates" in text and "2Expect LLC" in text
    selects = [e for b in blocks if b.get("type") in ("actions", "section")
               for e in (b.get("elements", []) + ([b.get("accessory")] if b.get("accessory") else []))
               if isinstance(e, dict) and e.get("type") == "static_select"]
    assert selects, "expected a static_select"
    assert len(selects[0]["options"]) == 2
    assert selects[0]["action_id"] == "pick_client"


def test_client_picker_encodes_file_id_in_block_id():
    blocks = client_picker_blocks([("habit-pilates", "Habit Pilates")], file_id="F1")
    assert blocks[0]["block_id"] == "drop:F1"
