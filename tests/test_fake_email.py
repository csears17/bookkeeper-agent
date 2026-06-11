from datetime import datetime, timezone

from bookkeeper_agent.connectors.email import FakeEmailConnector
from bookkeeper_agent.connectors.types import Attachment, EmailMessage


def _msg(mailbox, mid, dt, with_pdf=True):
    atts = (Attachment("invoice.pdf", "application/pdf", b"%PDF"),) if with_pdf else ()
    return EmailMessage(
        id=mid, mailbox=mailbox, sender="v@acme.com", subject="Invoice",
        internal_date=dt, snippet="hi", attachments=atts,
    )


def test_list_message_ids_filters_by_after_and_sorts():
    conn = FakeEmailConnector()
    box = "habit@unionstreet.io"
    conn.add(_msg(box, "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    conn.add(_msg(box, "m2", datetime(2026, 6, 3, tzinfo=timezone.utc)))
    conn.add(_msg(box, "m3", datetime(2026, 6, 2, tzinfo=timezone.utc)))

    after = int(datetime(2026, 6, 1, 12, tzinfo=timezone.utc).timestamp() * 1000)
    refs = conn.list_message_ids(box, after)
    assert [r.id for r in refs] == ["m3", "m2"]  # m1 excluded (before cutoff), sorted ascending


def test_get_message_returns_full_with_attachments():
    conn = FakeEmailConnector()
    box = "habit@unionstreet.io"
    conn.add(_msg(box, "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    msg = conn.get_message(box, "m1")
    assert msg.subject == "Invoice"
    assert msg.attachments[0].filename == "invoice.pdf"


def test_mailbox_isolation():
    conn = FakeEmailConnector()
    conn.add(_msg("a@unionstreet.io", "m1", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    conn.add(_msg("b@unionstreet.io", "m2", datetime(2026, 6, 1, tzinfo=timezone.utc)))
    refs = conn.list_message_ids("a@unionstreet.io", 0)
    assert [r.id for r in refs] == ["m1"]


def test_get_unknown_raises():
    conn = FakeEmailConnector()
    try:
        conn.get_message("a@unionstreet.io", "nope")
        assert False, "expected KeyError"
    except KeyError:
        pass
