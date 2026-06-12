from datetime import datetime, timezone

from bookkeeper_agent.connectors.types import Attachment, EmailMessage
from bookkeeper_agent.pipeline.prescreen import is_candidate


def _email(subject, snippet="", attachments=()):
    return EmailMessage(
        id="m1", mailbox="habit@unionstreet.io", sender="x@y.com",
        subject=subject, internal_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        snippet=snippet, attachments=attachments,
    )


def test_pdf_attachment_is_candidate():
    e = _email("anything", attachments=(Attachment("a.pdf", "application/pdf", b"%PDF"),))
    assert is_candidate(e) is True


def test_image_attachment_is_candidate():
    e = _email("photo", attachments=(Attachment("a.png", "image/png", b"x"),))
    assert is_candidate(e) is True


def test_ap_keyword_in_subject_is_candidate_without_attachment():
    assert is_candidate(_email("Your invoice is ready")) is True
    assert is_candidate(_email("Statement of account")) is True


def test_ap_keyword_in_snippet_is_candidate():
    assert is_candidate(_email("Hello", snippet="Total amount due: $250")) is True


def test_no_attachment_no_keyword_is_not_candidate():
    assert is_candidate(_email("Lunch tomorrow?", snippet="see you at noon")) is False


def test_non_pdf_non_image_attachment_without_keyword_is_not_candidate():
    e = _email("notes", attachments=(Attachment("notes.docx",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"x"),))
    assert is_candidate(e) is False
