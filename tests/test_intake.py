from datetime import datetime, timezone

from bookkeeper_agent.clients import ClientConfig
from bookkeeper_agent.connectors.types import Attachment, EmailMessage
from bookkeeper_agent.pipeline.intake import BillIntake, intake_from_email
from bookkeeper_agent.pipeline.prescreen import is_candidate, is_candidate_fields


def test_is_candidate_fields_matches_is_candidate():
    atts = (Attachment("a.pdf", "application/pdf", b"%PDF"),)
    assert is_candidate_fields("hi", "there", atts) is True
    assert is_candidate_fields("invoice", "", ()) is True
    assert is_candidate_fields("lunch", "noon", ()) is False
    e = EmailMessage(id="m", mailbox="b", sender="s", subject="lunch",
                     internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                     snippet="noon", attachments=())
    assert is_candidate(e) is False


def test_intake_from_email_binds_company_and_skips_nothing():
    client = ClientConfig(key="habit-pilates", display_name="Habit Pilates",
                          provider="google", mailbox="habit@unionstreet.io",
                          qbo_realm_id="111", autonomy_level=0)
    att = Attachment("invoice.pdf", "application/pdf", b"%PDF")
    email = EmailMessage(id="m1", mailbox="habit@unionstreet.io", sender="v@acme.com",
                         subject="Invoice 100", internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                         snippet="amount due", attachments=(att,))
    intake = intake_from_email(email, client)
    assert isinstance(intake, BillIntake)
    assert intake.source == "email"
    assert intake.source_id == "m1"
    assert intake.source_ref == "habit@unionstreet.io"
    assert intake.client_key == "habit-pilates"
    assert intake.client_display == "Habit Pilates"
    assert intake.company_realm == "111"
    assert intake.sender == "v@acme.com"
    assert intake.subject == "Invoice 100"
    assert intake.body_text == "amount due"
    assert intake.attachments == (att,)
    assert intake.skip_classification is False
