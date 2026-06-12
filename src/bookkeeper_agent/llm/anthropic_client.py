from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from bookkeeper_agent.costs import CostMeter
from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


class _ExtractionSchema(BaseModel):
    is_bill: bool
    classification_confidence: float = 0.0
    vendor_name: str | None = None
    doc_number: str | None = None
    txn_date: str | None = None  # ISO date "YYYY-MM-DD"
    due_date: str | None = None
    total: str | None = None  # plain decimal string, e.g. "250.00"
    currency: str = "USD"
    line_hint: str | None = None


class _CategorySchema(BaseModel):
    account_id: str
    account_name: str
    confidence: float
    reasoning: str


_EXTRACT_SYSTEM = (
    "You are an accounts-payable assistant. Decide whether an email is a vendor "
    "bill or invoice (an account payable). If it is, extract the fields from the "
    "email and any attached invoice. If it is NOT a payable (newsletter, receipt "
    "for an already-paid card charge, personal mail, statement), set is_bill=false "
    "and leave the other fields null. Dates must be ISO YYYY-MM-DD. total must be a "
    "plain decimal string like \"250.00\". Never invent values — use null when unsure."
)

_CATEGORIZE_SYSTEM = (
    "You categorize accounts-payable bills using the client's own chart of accounts "
    "and how they booked prior bills. Choose the single best account_id that is "
    "present in the provided chart of accounts. Give a confidence between 0 and 1 and "
    "a brief reasoning, citing precedent when it applies."
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    if not result.is_finite():
        return None
    return result


class AnthropicLlmClient:
    """Real LlmClient backed by Claude. The anthropic client is injected so this
    is unit-testable offline. Every call checks the spend cap first and records
    token cost after."""

    def __init__(self, client, model: str, cost_meter: CostMeter, capability: str = "bills"):
        self._client = client
        self._model = model
        self._cost = cost_meter
        self._capability = capability

    def _email_content(self, ctx: EmailContext) -> list[dict]:
        blocks: list[dict] = []
        for att in ctx.attachments:
            data = base64.standard_b64encode(att.content).decode()
            if att.mime_type == "application/pdf":
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": data},
                })
            elif att.mime_type.startswith("image/"):
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": att.mime_type, "data": data},
                })
            # other attachment types are ignored for extraction
        blocks.append({
            "type": "text",
            "text": f"From: {ctx.sender}\nSubject: {ctx.subject}\n\n{ctx.body_text}",
        })
        return blocks

    def _record(self, resp) -> None:
        u = resp.usage
        self._cost.record(
            self._model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(resp, "_request_id", None),
            capability=self._capability,
        )

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction:
        self._cost.check_cap()
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            system=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": self._email_content(ctx)}],
            output_format=_ExtractionSchema,
        )
        self._record(resp)
        p = resp.parsed_output
        return BillExtraction(
            is_bill=p.is_bill,
            classification_confidence=p.classification_confidence,
            vendor_name=p.vendor_name,
            doc_number=p.doc_number,
            txn_date=_parse_date(p.txn_date),
            due_date=_parse_date(p.due_date),
            total=_parse_decimal(p.total),
            currency=p.currency or "USD",
            line_hint=p.line_hint,
        )

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion:
        self._cost.check_cap()
        accounts_txt = "\n".join(f"- {a.id}: {a.name} ({a.account_type})" for a in ctx.accounts)
        precedents_txt = "\n".join(f"- {p}" for p in ctx.precedents) or "(no prior bills for this vendor)"
        prompt = (
            f"Vendor: {ctx.vendor_name}\n"
            f"Amount: {ctx.total}\n"
            f"Line hint: {ctx.line_hint or ''}\n\n"
            f"Chart of accounts:\n{accounts_txt}\n\n"
            f"How this client booked prior bills from this vendor:\n{precedents_txt}\n\n"
            "Choose the single best account_id from the chart for this bill."
        )
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=_CATEGORIZE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=_CategorySchema,
        )
        self._record(resp)
        p = resp.parsed_output
        return CategorySuggestion(
            account_id=p.account_id,
            account_name=p.account_name,
            confidence=p.confidence,
            reasoning=p.reasoning,
        )
