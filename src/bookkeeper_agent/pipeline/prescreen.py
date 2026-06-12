from __future__ import annotations

from bookkeeper_agent.connectors.types import EmailMessage

# Words/phrases that suggest an accounts-payable item. Lowercase; matched as substrings.
_AP_KEYWORDS = (
    "invoice",
    "bill",
    "amount due",
    "payment due",
    "balance due",
    "past due",
    "statement",
    "remittance",
    "payable",
    "net 30",
    "net 15",
)


def is_candidate_fields(subject: str, snippet: str, attachments) -> bool:
    """Field-based pre-screen used by both the EmailMessage wrapper and the
    pipeline (which works on a normalized BillIntake, not an EmailMessage)."""
    for att in attachments:
        if att.mime_type == "application/pdf" or att.mime_type.startswith("image/"):
            return True
    text = f"{subject}\n{snippet}".lower()
    return any(keyword in text for keyword in _AP_KEYWORDS)


def is_candidate(email: EmailMessage) -> bool:
    """Cheap, local, no-AI gate on an email. See is_candidate_fields."""
    return is_candidate_fields(email.subject, email.snippet, email.attachments)
