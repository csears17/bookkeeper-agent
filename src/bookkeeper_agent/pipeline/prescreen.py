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


def is_candidate(email: EmailMessage) -> bool:
    """Cheap, local, no-AI gate. An email is a *candidate* bill if it has a
    PDF or image attachment, OR its subject/snippet contains an AP keyword.

    Only obvious non-bills (no PDF/image attachment AND no AP keyword) are
    dropped here — the LLM makes the real is-this-a-bill decision. Conservative
    on purpose: better to let a non-bill through to the model than to drop a bill.
    """
    for att in email.attachments:
        if att.mime_type == "application/pdf" or att.mime_type.startswith("image/"):
            return True
    text = f"{email.subject}\n{email.snippet}".lower()
    return any(keyword in text for keyword in _AP_KEYWORDS)
